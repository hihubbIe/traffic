"""Matches live DIR Est station ids (qtvDir 'MZO57.5x' etc.) to named count stations.

The official reference gives no positions for DIR Est ids. Each count station has a
known 2024 TMJA per direction (data/static/count_stations.json), so once the recorder
holds full weekdays we compare each id's daily volume per direction to those figures.
The scale between "weekday 05-21h volume" and "TMJA" is calibrated on ids already known.
"""
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import STATIC_DIR
from .db import DB_PATH

TZ = ZoneInfo("Europe/Luxembourg")
DAY_START, DAY_END = 5, 21  # local hours used for the daily volume
SLOT_MIN = 6                # DIR publishes every 6 minutes
MIN_COVERAGE = 0.85
GOOD_COST, GOOD_MARGIN = 0.12, 0.10


def load_count_stations() -> list[dict]:
    fc = json.loads((STATIC_DIR / "count_stations.json").read_text(encoding="utf-8"))
    return [{**f["properties"], "coord": f["geometry"]["coordinates"]} for f in fc["features"]]


def load_assignments() -> dict:
    path = STATIC_DIR / "dir_stations.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"stations": {}}


def save_assignments(data: dict) -> None:
    (STATIC_DIR / "dir_stations.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def station_key(st: dict) -> str:
    return f"{st['road']}@{st['pr']}"


def weekday_volumes() -> tuple[dict, list[str]]:
    """{base_id: {'1': vol, '2': vol}} averaged over qualifying weekdays, and those dates."""
    if not DB_PATH.exists():
        return {}, []
    con = sqlite3.connect(DB_PATH)
    try:
        rows = con.execute("SELECT o.ts, s.ext_id, o.flow FROM obs_sensor o JOIN sites s ON s.id = o.site "
                           "WHERE s.source = 'DIR' AND o.flow IS NOT NULL").fetchall()
    finally:
        con.close()
    slots_needed = (DAY_END - DAY_START) * 60 // SLOT_MIN
    per = defaultdict(dict)  # (site, date) -> {slot: flow}
    for ts, site, flow in rows:
        t = datetime.fromtimestamp(ts, TZ)
        if t.weekday() >= 5 or not (DAY_START <= t.hour < DAY_END):
            continue
        slot = ((t.hour - DAY_START) * 60 + t.minute) // SLOT_MIN
        per[(site, t.date().isoformat())][slot] = flow
    vols = defaultdict(lambda: defaultdict(list))
    dates = set()
    for (site, d), slots in per.items():
        if len(slots) < MIN_COVERAGE * slots_needed:
            continue
        mean_flow = sum(slots.values()) / len(slots)       # veh/h
        vols[site[:-1]][site[-1]].append(mean_flow * (DAY_END - DAY_START))
        dates.add(d)
    return ({b: {s: sum(v) / len(v) for s, v in d.items()} for b, d in vols.items()}, sorted(dates))


def _cost(vol: dict, st: dict, scale: float) -> float:
    terms = []
    for sfx, key in (("1", "tmja_sens1"), ("2", "tmja_sens2")):
        if sfx in vol and st.get(key) and vol[sfx] > 0:
            terms.append(abs(math.log(vol[sfx] / (scale * st[key]))))
    return sum(terms) / len(terms) if terms else math.inf


def propose() -> dict:
    stations = [s for s in load_count_stations() if s.get("tmja")]
    assigned = load_assignments()["stations"]
    vols, dates = weekday_volumes()
    by_key = {station_key(s): s for s in stations}

    # Scale = weekday-volume / TMJA, from ids whose station is already known.
    ratios = []
    for base, a in assigned.items():
        st = by_key.get(a.get("station_key", ""))
        if st and base in vols:
            for sfx, key in (("1", "tmja_sens1"), ("2", "tmja_sens2")):
                if sfx in vols[base] and st.get(key):
                    ratios.append(vols[base][sfx] / st[key])
    status = {"weekdays_recorded": dates, "ids_with_volume": len(vols)}
    if not ratios:
        return {**status, "ready": False, "proposals": [],
                "reason": "Needs at least one full weekday (05:00-21:00) of recordings including a known station."}
    scale = sorted(ratios)[len(ratios) // 2]

    taken = {a.get("station_key") for a in assigned.values()}
    free = [s for s in stations if station_key(s) not in taken]
    cand = []
    for base, vol in vols.items():
        if base in assigned:
            continue
        costs = sorted((_cost(vol, s, scale), station_key(s)) for s in free)
        if costs and math.isfinite(costs[0][0]):
            margin = (costs[1][0] - costs[0][0]) if len(costs) > 1 else 1.0
            cand.append({"id": base, "station_key": costs[0][1], "cost": round(costs[0][0], 3),
                         "margin": round(margin, 3), "volumes": {k: round(v) for k, v in vol.items()}})
    # Greedy: most distinctive first, one id per station.
    cand.sort(key=lambda c: (-c["margin"], c["cost"]))
    used, proposals = set(), []
    for c in cand:
        if c["station_key"] in used:
            continue
        used.add(c["station_key"])
        st = by_key[c["station_key"]]
        c.update({"station": st["name"], "road": st["road"], "pr": st["pr"],
                  "confident": c["cost"] <= GOOD_COST and c["margin"] >= GOOD_MARGIN})
        proposals.append(c)
    return {**status, "ready": True, "scale": round(scale, 4), "proposals": proposals}


def apply_confident() -> int:
    result = propose()
    data = load_assignments()
    n = 0
    for p in result.get("proposals", []):
        if p["confident"]:
            data["stations"][p["id"]] = {
                "station_key": p["station_key"], "source": "auto-match",
                "matched_on": datetime.now(TZ).date().isoformat(), "cost": p["cost"], "margin": p["margin"],
            }
            n += 1
    save_assignments(data)
    return n


if __name__ == "__main__":
    print(json.dumps(propose(), indent=1, ensure_ascii=False))
