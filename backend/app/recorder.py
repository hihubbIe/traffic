"""Records live snapshots into a local SQLite file while the app is running.

This is how history accumulates without a permanent collector. The same loop
can later run on a Raspberry Pi (python -m app.recorder) for gap-free data.
"""
import asyncio
import logging
import sqlite3
from datetime import datetime, timezone

from .config import RECORD_TOMTOM, RECORDINGS_DIR, tomtom_key
from .feeds import cita, dir_est, tomtom
from .http import FeedError

log = logging.getLogger("recorder")
DB_PATH = RECORDINGS_DIR / "traffic.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cita_obs (ts TEXT, site TEXT, road TEXT, speed REAL, flow REAL, occupancy REAL,
                                     PRIMARY KEY (site, ts));
CREATE TABLE IF NOT EXISTS cita_sites (site TEXT PRIMARY KEY, road TEXT, lat REAL, lon REAL,
                                       direction TEXT, chainage REAL);
CREATE TABLE IF NOT EXISTS dir_obs (ts TEXT, site TEXT, speed REAL, flow REAL, PRIMARY KEY (site, ts));
CREATE TABLE IF NOT EXISTS corridor_obs (ts TEXT, corridor TEXT, direction TEXT, travel_s REAL,
                                         free_s REAL, historic_s REAL, delay_s REAL, passes TEXT,
                                         PRIMARY KEY (corridor, direction, ts));
CREATE TABLE IF NOT EXISTS events_seen (id TEXT, source TEXT, first_seen TEXT, last_seen TEXT,
                                        kind TEXT, road TEXT, payload TEXT, PRIMARY KEY (id, source));
"""


def connect() -> sqlite3.Connection:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    return con


def stats() -> dict:
    if not DB_PATH.exists():
        return {"recording": False}
    con = connect()
    try:
        out = {}
        for table in ("cita_obs", "dir_obs", "corridor_obs", "events_seen"):
            n, first, last = con.execute(
                f"SELECT COUNT(*), MIN({'first_seen' if table == 'events_seen' else 'ts'}), "
                f"MAX({'last_seen' if table == 'events_seen' else 'ts'}) FROM {table}").fetchone()
            out[table] = {"rows": n, "first": first, "last": last}
        out["size_mb"] = round(DB_PATH.stat().st_size / 1e6, 2)
        return out
    finally:
        con.close()


async def _record_cita(con):
    data = await cita.traffic_status()
    rows, sites = [], []
    for s in data["sites"]:
        if s["time"] is None:
            continue
        rows.append((s["time"], s["id"], s["road"], s["speed"], s["flow"], s["occupancy"]))
        sites.append((s["id"], s["road"], s["lat"], s["lon"], s["direction"], s["chainage"]))
    con.executemany("INSERT OR IGNORE INTO cita_obs VALUES (?,?,?,?,?,?)", rows)
    con.executemany("INSERT OR REPLACE INTO cita_sites VALUES (?,?,?,?,?,?)", sites)


async def _record_dir(con):
    data = await dir_est.stations()
    con.executemany("INSERT OR IGNORE INTO dir_obs VALUES (?,?,?,?)",
                    [(s["time"], s["id"], s["speed"], s["flow"]) for s in data["stations"] if s["time"]])


def _record_events(con, features, source):
    import json
    now = datetime.now(timezone.utc).isoformat()
    for f in features:
        p = f["properties"]
        con.execute(
            "INSERT INTO events_seen VALUES (?,?,?,?,?,?,?) ON CONFLICT(id, source) DO UPDATE SET last_seen=excluded.last_seen",
            (str(p.get("id")), source, now, now, p.get("kind") or p.get("category"),
             p.get("road") or ",".join(p.get("roads") or []), json.dumps(f)))


async def _record_corridors(con):
    import json
    for direction in tomtom.DIRECTIONS:
        data = await tomtom.corridors_now(direction)
        ts = data["fetched"]
        con.executemany("INSERT OR IGNORE INTO corridor_obs VALUES (?,?,?,?,?,?,?,?)", [
            (ts, r["id"], direction, r.get("travel_s"), r.get("free_s"), r.get("historic_s"),
             r.get("delay_s"), json.dumps(r.get("passes", [])))
            for r in data["results"] if "error" not in r])


async def _step(name, fn, con):
    try:
        await fn(con)
        con.commit()
    except (FeedError, Exception) as e:  # keep recording other feeds if one fails
        log.warning("record %s failed: %s", name, e)


async def run_forever():
    con = connect()
    tick = 0
    try:
        while True:
            await _step("cita", _record_cita, con)
            if tick % 6 == 0:  # DIR publishes every 6 min
                await _step("dir", _record_dir, con)
            if tick % 2 == 0:
                async def ev(c):
                    _record_events(c, (await cita.events())["features"], "CITA")
                    if tomtom_key():
                        _record_events(c, (await tomtom.incidents())["features"], "TomTom")
                await _step("events", ev, con)
            if RECORD_TOMTOM and tomtom_key() and tick % 10 == 0:
                await _step("corridors", _record_corridors, con)
            tick += 1
            await asyncio.sleep(60)
    finally:
        con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
