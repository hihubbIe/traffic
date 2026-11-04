"""Collector: records every source the traffic model needs, each at the pace it actually changes.

Run standalone (python -m app.collector) on an always-on machine, or inside the API process
on a PC (COLLECT_IN_API=true). Jobs are independent: one failing source backs off without
affecting the others, and every run is logged in collector_runs for health checks.

Collection runs 06:00-21:00 local time only; nights add little to a commute model.
Each job downloads first and then writes in one short transaction, so the database is
never locked while waiting on the network.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from . import db
from .config import STATIC_DIR, tomtom_key
from .feeds import cita, dir_est, dir_events, rail, tomtom, weather
from .http import FeedError

log = logging.getLogger("collector")
TZ = ZoneInfo("Europe/Luxembourg")
ACTIVE_FROM, ACTIVE_TO = 6 * 60, 21 * 60  # minutes after midnight, local time


def period(t: datetime) -> str:
    """peak = weekdays 06:00-09:30 and 15:30-19:30; day = rest of 06:00-21:00; off = no collection."""
    hm = t.hour * 60 + t.minute
    if not ACTIVE_FROM <= hm < ACTIVE_TO:
        return "off"
    if t.weekday() < 5 and (hm < 9 * 60 + 30 or 15 * 60 + 30 <= hm < 19 * 60 + 30):
        return "peak"
    return "day"


@dataclass
class Job:
    name: str
    run: Callable[[object], Awaitable[int]]
    every: dict  # period -> minutes between runs ("off" is never collected)
    needs_tomtom: bool = False
    next_at: float = 0.0
    failures: int = 0


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp())


def _first_coord(geom: dict) -> tuple:
    t, c = geom.get("type"), geom.get("coordinates") or []
    if t == "Point" and c:
        return c[0], c[1]
    if t in ("LineString", "MultiPoint") and c:
        return c[0][0], c[0][1]
    if t == "MultiLineString" and c and c[0]:
        return c[0][0][0], c[0][0][1]
    return None, None


# ---------------------------------------------------------------- jobs

async def job_cita_traffic(con) -> int:
    data = await cita.traffic_status()
    if data["errors"]:
        log.warning("cita partial: %s", data["errors"])
    n = 0
    with db.tx(con):
        for s in data["sites"]:
            if not s["time"]:
                continue
            sid = db.site_id(con, "CITA", s["id"], s["road"], s["lat"], s["lon"], s["direction"], {"chainage": s["chainage"]})
            n += con.execute("INSERT OR IGNORE INTO obs_sensor VALUES (?,?,?,?,?)",
                             (sid, _ts(s["time"]), s["speed"], s["flow"], s["occupancy"])).rowcount
    return n


async def job_dir_traffic(con) -> int:
    xml = await dir_est.qtv_if_changed()  # only downloaded when the national file changed
    if xml is None:
        return 0
    stations = dir_est.parse_qtv(xml)
    n = 0
    with db.tx(con):
        for s in stations:
            if s["time"]:
                sid = db.site_id(con, "DIR", s["id"])
                n += con.execute("INSERT OR IGNORE INTO obs_sensor VALUES (?,?,?,?,?)",
                                 (sid, _ts(s["time"]), s["speed"], s["flow"], None)).rowcount
    return n


async def job_cita_events(con) -> int:
    fc = await cita.events()
    with db.tx(con):
        for f in fc["features"]:
            p = f["properties"]
            lon, lat = _first_coord(f["geometry"])
            db.upsert_event(con, "CITA", str(p["id"]), p["kind"], p["road"], lat, lon, p["start"], p["end"], f)
    return len(fc["features"])


async def job_cita_signs(con) -> int:
    fc = await cita.travel_times()
    ts = db.now() // 60 * 60
    n = 0
    with db.tx(con):
        for f in fc["features"]:
            for t in f["properties"]["times"]:
                n += con.execute("INSERT OR IGNORE INTO obs_sign VALUES (?,?,?,?)",
                                 (f["properties"]["name"], t["destination"], ts, t["minutes"])).rowcount
    return n


async def job_dir_events(con) -> int:
    if not dir_events.seen_loaded():
        dir_events.load_seen(r[0] for r in con.execute(
            "SELECT name FROM seen_files WHERE source='DIR' AND ts > ?", (db.now() - 3 * 86400,)))
    events, new_files = await dir_events.new_events()
    with db.tx(con):
        con.executemany("INSERT OR IGNORE INTO seen_files VALUES ('DIR', ?, ?)", [(f, db.now()) for f in new_files])
        con.execute("DELETE FROM seen_files WHERE source='DIR' AND ts < ?", (db.now() - 3 * 86400,))
        for e in events:
            db.upsert_event(con, "DIR", e["id"], e["kind"], e["road"], e["lat"], e["lon"], e["start"], e["end"], e)
    return len(events)


async def job_tomtom_incidents(con) -> int:
    fc = await tomtom.incidents()
    with db.tx(con):
        for f in fc["features"]:
            p = f["properties"]
            lon, lat = _first_coord(f.get("geometry") or {})
            db.upsert_event(con, "TomTom", str(p["id"]), p["category"], ",".join(p["roads"]), lat, lon,
                            p["start"], p["end"], f)
    return len(fc["features"])


async def job_tomtom_routes(con) -> int:
    results = []
    for direction in tomtom.DIRECTIONS:
        data = await tomtom.corridors_now(direction)
        results += [(direction, r) for r in data["results"]]
    ok = [(d, r) for d, r in results if "error" not in r]
    for d, r in results:
        if "error" in r:
            log.warning("route %s %s: %s", r["id"], d, r["error"])
    if not ok:
        raise FeedError(results[0][1]["error"] if results else "no routes")
    ts = db.now()
    n = 0
    with db.tx(con):
        for d, r in ok:
            n += con.execute("INSERT OR IGNORE INTO obs_route VALUES (?,?,?,?,?,?,?,?,?,?)", (
                r["id"], d, ts, r["travel_s"], r["free_s"], r["historic_s"], r["delay_s"], r["length_m"],
                json.dumps(r.get("traffic", [])), json.dumps(r.get("passes", [])))).rowcount
    return n


def load_segments() -> list[dict]:
    path = STATIC_DIR / "segments.json"
    return json.loads(path.read_text(encoding="utf-8"))["segments"] if path.exists() else []


async def job_tomtom_segments(con) -> int:
    ts = db.now()
    samples = []
    for seg in load_segments():
        try:
            samples.append((seg, await tomtom.segment_flow(seg["lon"], seg["lat"])))
        except FeedError as e:
            if "budget" in str(e):
                raise
            log.warning("segment %s: %s", seg["id"], e)
    if not samples:
        raise FeedError("no segment could be read")
    n = 0
    with db.tx(con):
        for seg, f in samples:
            sid = db.site_id(con, "TTSEG", seg["id"], seg.get("road"), seg["lat"], seg["lon"], seg.get("direction"),
                             {"name": seg["name"], "routes": seg.get("routes"), "frc": f["frc"]})
            n += con.execute("INSERT OR IGNORE INTO obs_segment VALUES (?,?,?,?,?,?,?,?)", (
                sid, ts, f["speed"], f["free_speed"], f["travel_s"], f["free_travel_s"], f["confidence"], f["closed"])).rowcount
    return n


async def job_rail(con) -> int:
    trips = await rail.trips()
    alerts = await rail.alerts()
    ts = db.now()
    n = 0
    with db.tx(con):
        for t in trips or []:
            n += con.execute("INSERT OR IGNORE INTO obs_rail VALUES (?,?,?,?,?,?,?)", (
                t["trip"], ts, t["relationship"], t["delay_thionville"], t["max_delay"], t["origin"], t["destination"])).rowcount
        for a in alerts or []:
            start, end = a["periods"][0] if a["periods"] else (None, None)
            db.upsert_event(con, "SNCF", a["id"], f"rail:{a['effect']}", "rail", None, None,
                            str(start) if start else None, str(end) if end else None, a)
    return n + len(alerts or [])


async def job_weather(con) -> int:
    rows = await weather.hourly_past(days=2)  # one daily call covers the last 48 h, nights included
    now_ts = db.now()
    n = 0
    with db.tx(con):
        for w in rows:
            if w["ts"] <= now_ts:  # observed hours only
                n += con.execute("INSERT OR REPLACE INTO obs_weather VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    w["place"], w["ts"], w["temp"], w["precip"], w["rain"], w["snowfall"], w["code"], w["wind"],
                    w["visibility"], w["cloud"])).rowcount
    return n


DAILY = 24 * 60
JOBS = [
    #   name                function               minutes between runs                TomTom
    Job("cita_traffic",     job_cita_traffic,      {"peak": 3, "day": 5}),
    Job("dir_traffic",      job_dir_traffic,       {"peak": 6, "day": 6}),
    Job("cita_events",      job_cita_events,       {"peak": 10, "day": 15}),
    Job("cita_signs",       job_cita_signs,        {"peak": 10, "day": 30}),
    Job("dir_events",       job_dir_events,        {"peak": 60, "day": 60}),
    Job("rail",             job_rail,              {"peak": 5, "day": 15}),
    Job("weather",          job_weather,           {"peak": DAILY, "day": DAILY}),
    Job("tomtom_routes",    job_tomtom_routes,     {"peak": 10, "day": 30}, needs_tomtom=True),
    Job("tomtom_segments",  job_tomtom_segments,   {"peak": 10, "day": 30}, needs_tomtom=True),
    Job("tomtom_incidents", job_tomtom_incidents,  {"peak": 15, "day": 30}, needs_tomtom=True),
]


async def _run(job: Job) -> None:
    con = db.connect()
    t0 = time.monotonic()
    ok, rows, err = 1, 0, None
    token = tomtom.BACKGROUND.set(True)
    try:
        rows = await asyncio.wait_for(job.run(con), timeout=20 * 60)
        job.failures = 0
    except Exception as e:  # any source error: log, back off, keep going
        ok, err = 0, f"{e.__class__.__name__}: {e}"[:500]
        job.failures += 1
        log.warning("%s failed (%d in a row): %s", job.name, job.failures, err)
    finally:
        tomtom.BACKGROUND.reset(token)
        try:
            with db.tx(con):
                con.execute("INSERT INTO collector_runs VALUES (?,?,?,?,?,?)",
                            (db.now(), job.name, ok, rows, int((time.monotonic() - t0) * 1000), err))
        finally:
            con.close()


def _schedule(job: Job, now: float) -> None:
    delay = job.every[period(datetime.now(TZ))] * 60
    if job.failures:  # back off: x2 per consecutive failure, at most 2 h
        delay = min(delay * 2 ** min(job.failures, 6), max(delay, 2 * 3600))
    job.next_at = now + delay


def _resume_from_log() -> None:
    """After a restart, don't repeat jobs that ran recently (e.g. the daily weather call)."""
    con = db.connect()
    try:
        with db.tx(con):
            con.execute("DELETE FROM collector_runs WHERE ts < ?", (db.now() - 90 * 86400,))
        p = period(datetime.now(TZ))
        for job in JOBS:
            last = con.execute("SELECT max(ts) FROM collector_runs WHERE job=? AND ok=1", (job.name,)).fetchone()[0]
            if last:
                job.next_at = last + job.every.get(p, job.every["day"]) * 60
    finally:
        con.close()


async def run_forever() -> None:
    _resume_from_log()
    running: dict[str, asyncio.Task] = {}
    log.info("collector started (06:00-21:00): %s", ", ".join(j.name for j in JOBS))
    while True:
        now = time.time()
        if period(datetime.now(TZ)) != "off":
            for job in JOBS:
                busy = job.name in running and not running[job.name].done()
                if busy or now < job.next_at:
                    continue
                if job.needs_tomtom and not tomtom_key():
                    job.next_at = now + 3600
                    continue
                _schedule(job, now)
                running[job.name] = asyncio.create_task(_run(job))
        await asyncio.sleep(15)


def health() -> dict:
    con = db.connect()
    try:
        since = db.now() - 86400
        out = {}
        for job in JOBS:
            last = con.execute("SELECT ts, ok, error FROM collector_runs WHERE job=? ORDER BY ts DESC LIMIT 1",
                               (job.name,)).fetchone()
            last_ok = con.execute("SELECT max(ts) FROM collector_runs WHERE job=? AND ok=1", (job.name,)).fetchone()[0]
            runs, fails, rows = con.execute(
                "SELECT count(*), coalesce(sum(1 - ok), 0), coalesce(sum(rows), 0) FROM collector_runs "
                "WHERE job=? AND ts>=?", (job.name, since)).fetchone()
            out[job.name] = {"last_run": last[0] if last else None, "last_ok": last_ok,
                             "last_error": last[2] if last and not last[1] else None,
                             "runs_24h": runs, "failures_24h": fails, "rows_24h": rows}
        return {"active_hours": "06:00-21:00", "collecting_now": period(datetime.now(TZ)) != "off", "jobs": out}
    finally:
        con.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
