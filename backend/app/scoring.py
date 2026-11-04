"""Prediction log and scoring: how far off were the forecasts, by how far ahead they were made.

What actually happened for a departure, best evidence first:
1. your own logged trip (depart within 10 min, same direction);
2. the live TomTom route time recorded by the collector within 8 min of that departure.
"""
from datetime import datetime
from statistics import mean

from . import db

MADE_BUCKET_S = 30 * 60  # one stored forecast per departure per half hour of forecasting
HORIZONS = [(0, 3600, "< 1 h ahead"), (3600, 6 * 3600, "1-6 h ahead"), (6 * 3600, 24 * 3600, "6-24 h ahead"),
            (24 * 3600, 10**9, "> 1 day ahead")]


def log(source: str, route: str, direction: str, points: list[dict]) -> None:
    """points: [{depart: iso, travel_s}] as returned by a forecast."""
    now = db.now()
    made = now // MADE_BUCKET_S * MADE_BUCKET_S
    rows = []
    for p in points:
        depart = int(datetime.fromisoformat(p["depart"]).timestamp())
        if p.get("travel_s") and depart - now >= 600:  # "leave now" is the live value itself: nothing to score
            rows.append((source, route, direction, depart, made, p["travel_s"]))
    if not rows:
        return
    con = db.connect()
    try:
        with db.tx(con):
            con.executemany("INSERT OR IGNORE INTO predictions VALUES (?,?,?,?,?,?)", rows)
    finally:
        con.close()


def _actual(con, route: str, direction: str, depart: int) -> tuple[float, str] | None:
    trip = con.execute(
        "SELECT arrive_ts - depart_ts FROM trips WHERE direction=? AND arrive_ts IS NOT NULL "
        "AND abs(depart_ts - ?) <= 600 AND (route IS NULL OR route=?) ORDER BY abs(depart_ts - ?) LIMIT 1",
        (direction, depart, route, depart)).fetchone()
    if trip:
        return float(trip[0]), "trip"
    obs = con.execute(
        "SELECT travel_s FROM obs_route WHERE route=? AND direction=? AND abs(ts - ?) <= 480 "
        "ORDER BY abs(ts - ?) LIMIT 1", (route, direction, depart, depart)).fetchone()
    return (float(obs[0]), "recorded") if obs and obs[0] else None


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]


def accuracy(days: int = 28, source: str | None = None) -> dict:
    """Errors (predicted - actual, seconds) grouped by how far ahead the forecast was made."""
    con = db.connect()
    try:
        since, now = db.now() - days * 86400, db.now()
        rows = con.execute(
            "SELECT source, route, direction, depart_ts, made_ts, predicted_s FROM predictions "
            "WHERE depart_ts BETWEEN ? AND ? AND (? IS NULL OR source = ?)", (since, now - 600, source, source)).fetchall()
        groups: dict = {}
        examples = []
        for src, route, direction, depart, made, pred in rows:
            act = _actual(con, route, direction, depart)
            if act is None:
                continue
            err = pred - act[0]
            horizon = max(0, depart - made)
            label = next(h[2] for h in HORIZONS if h[0] <= horizon < h[1])
            groups.setdefault((src, label), []).append(err)
            examples.append({"source": src, "route": route, "direction": direction, "depart_ts": depart,
                             "predicted_s": pred, "actual_s": act[0], "actual_from": act[1], "horizon_s": horizon})
        out = []
        for (src, label), errs in sorted(groups.items()):
            out.append({"source": src, "horizon": label, "n": len(errs), "mae_s": round(mean(abs(e) for e in errs)),
                        "bias_s": round(mean(errs)), "p10_s": round(_pct(errs, 0.1)), "p90_s": round(_pct(errs, 0.9))})
        examples.sort(key=lambda e: -e["depart_ts"])
        return {"days": days, "groups": out, "recent": examples[:8], "scored": sum(g["n"] for g in out)}
    finally:
        con.close()


def band(source: str, horizon_s: float, min_n: int = 30) -> tuple[float, float] | None:
    """Typical error range (10th-90th percentile) for forecasts made this far ahead, once enough are scored."""
    label = next(h[2] for h in HORIZONS if h[0] <= horizon_s < h[1])
    g = next((g for g in accuracy(source=source)["groups"] if g["horizon"] == label), None)
    return (g["p10_s"], g["p90_s"]) if g and g["n"] >= min_n else None
