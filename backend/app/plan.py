"""The "before leaving" answer: when to leave, on which route, how sure, and why.

Forecast curves come from TomTom for now (honestly labelled); the structure is what our own
model will fill later. Everything else here is ours: recommendation, calendar and weather
factors, train disruptions, live trend from recorded segments, scored accuracy.
"""
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import calendar_ctx, db, scoring
from .feeds import tomtom, weather
from .http import FeedError

TZ = ZoneInfo("Europe/Luxembourg")
STEP_MIN = 15


def _next_workday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def window(mode: str, direction: str, now: datetime) -> dict:
    if mode == "workday":
        day = _next_workday(now.date())
        start, end = ("06:00", "09:30") if direction == "to_work" else ("16:00", "19:30")
        return {"mode": mode, "day": day, "start": start, "end": end, "label": day.strftime("%A")}
    s = now.replace(minute=now.minute // STEP_MIN * STEP_MIN, second=0, microsecond=0)
    e = s + timedelta(hours=3)
    if e.date() != s.date():
        e = s.replace(hour=23, minute=45)
    return {"mode": mode, "day": s.date(), "start": s.strftime("%H:%M"), "end": e.strftime("%H:%M"), "label": "Next 3 h"}


def _hm(ts_iso: str) -> str:
    return datetime.fromisoformat(ts_iso).astimezone(TZ).strftime("%H:%M")


def _arrive(depart_iso: str, travel_s: float) -> str:
    return (datetime.fromisoformat(depart_iso) + timedelta(seconds=travel_s)).astimezone(TZ).strftime("%H:%M")


def recommend(slots: list[dict], names: dict, mode: str) -> dict:
    """slots: [{depart, best_route, best_s, by_route}] in time order."""
    if not slots:
        return {"headline": "No departures left in this window.", "detail": None, "options": []}
    best = min(slots, key=lambda s: s["best_s"])
    thr = best["best_s"] + max(300, 0.10 * best["best_s"])
    bad = [s["best_s"] > thr for s in slots]

    def opt(s, label):
        return {"label": label, "depart": _hm(s["depart"]), "arrive": _arrive(s["depart"], s["best_s"]),
                "minutes": round(s["best_s"] / 60), "route": names.get(s["best_route"], s["best_route"])}

    options, headline, detail = [], "", None
    first = slots[0]
    if mode == "next":
        if not bad[0]:
            j = next((i for i, b in enumerate(bad) if b), None)
            if j is None:
                headline = "Leave whenever you like: no real peak in the next 3 h."
                options = [opt(first, "Now")]
            else:
                k = next((i for i in range(j, len(slots)) if not bad[i]), None)
                headline = f"Leave before {_hm(slots[j - 1]['depart'])}" + (f", or wait until {_hm(slots[k]['depart'])}" if k else "")
                peak = max(slots[j:k] if k else slots[j:], key=lambda s: s["best_s"])
                detail = (f"In between it takes up to {round(peak['best_s'] / 60)} min "
                          f"({round((peak['best_s'] - best['best_s']) / 60)} more than the best).")
                options = [opt(first, "Now"), opt(slots[j - 1], "Last good")] + ([opt(slots[k], "After the peak")] if k else [])
        else:
            k = next((i for i, b in enumerate(bad) if not b), None)
            if k is None:
                headline = "Busy for the next 3 h: waiting won't help much."
                options = [opt(first, "Now"), opt(best, "Least bad")]
            else:
                saved = round((first["best_s"] - slots[k]["best_s"]) / 60)
                headline = f"Wait until {_hm(slots[k]['depart'])}: {saved} min less driving"
                detail = (f"Leaving now you'd arrive at {_arrive(first['depart'], first['best_s'])}; "
                          f"at {_hm(slots[k]['depart'])} you'd arrive at {_arrive(slots[k]['depart'], slots[k]['best_s'])}.")
                options = [opt(first, "Now"), opt(slots[k], "Wait"), opt(best, "Best")]
    else:
        j = next((i for i, b in enumerate(bad) if b), None)
        if j is None:
            lo, hi = min(s["best_s"] for s in slots), max(s["best_s"] for s in slots)
            headline = f"No real peak: {round(lo / 60)}–{round(hi / 60)} min all along"
            options = [opt(best, "Best")]
        else:
            k = next((i for i in range(j, len(slots)) if not bad[i]), None)
            before = slots[j - 1] if j > 0 else None
            after = slots[k] if k is not None else None
            if before and after:
                headline = f"Leave before {_hm(before['depart'])} or after {_hm(after['depart'])}"
            elif before:
                headline = f"Leave before {_hm(before['depart'])}"
            elif after:
                headline = f"Leave after {_hm(after['depart'])}"
            else:
                headline = f"Busy the whole window: best at {_hm(best['depart'])}"
            block = slots[j:k] if k is not None else slots[j:]
            detail = (f"{_hm(block[0]['depart'])}–{_hm(block[-1]['depart'])} takes up to "
                      f"{round(max(s['best_s'] for s in block) / 60)} min ({round(best['best_s'] / 60)} at best).")
            options = ([opt(before, "Before the peak")] if before else []) + ([opt(after, "After the peak")] if after else []) + [opt(best, "Best")]
    seen, uniq = set(), []
    for o in options:  # same departure listed once
        if o["depart"] not in seen:
            seen.add(o["depart"])
            uniq.append(o)
    return {"headline": headline, "detail": detail, "options": uniq,
            "best": opt(best, "Best"), "threshold_s": thr}


def route_switches(slots: list[dict], names: dict, routes: list[str]) -> list[str]:
    """'Aumetz is quicker 17:15-18:00' style notes between the usual routes."""
    if len(routes) < 2:
        return []
    a, b = routes[0], routes[1]
    notes, run = [], []
    for s in slots + [None]:
        faster = s is not None and a in s["by_route"] and b in s["by_route"] and s["by_route"][b] < s["by_route"][a] - 120
        if faster:
            run.append(s)
        elif run:
            gain = round(max(r["by_route"][a] - r["by_route"][b] for r in run) / 60)
            span = _hm(run[0]["depart"]) + ("" if len(run) == 1 else f"–{_hm(run[-1]['depart'])}")
            notes.append(f"{names[b]} is quicker {span} (up to {gain} min)")
            run = []
    return notes


async def weather_factors(day: date, start: str, end: str) -> list[dict]:
    try:
        hours = await weather.forecast("aumetz")
    except FeedError:
        return []
    t0 = datetime.combine(day, datetime.strptime(start, "%H:%M").time(), TZ).timestamp() - 3600
    t1 = datetime.combine(day, datetime.strptime(end, "%H:%M").time(), TZ).timestamp()
    w = [h for h in hours if t0 <= h["ts"] <= t1]
    if not w:
        return []
    out = []
    snow = sum(h["snowfall"] or 0 for h in w)
    rain = max(h["precip"] or 0 for h in w)
    fog = any((h["code"] in (45, 48)) or (h["visibility"] is not None and h["visibility"] < 1000) for h in w)
    ice = any((h["temp"] or 9) <= 0 and (h["precip"] or 0) > 0 for h in w)
    if snow > 0:
        out.append({"effect": "heavier", "strength": 3, "title": "Snow forecast", "detail": f"{snow:.1f} cm expected around your trip.", "kind": "weather"})
    elif ice:
        out.append({"effect": "heavier", "strength": 3, "title": "Freezing rain risk", "detail": "Precipitation at or below 0 °C.", "kind": "weather"})
    elif rain >= 0.5:
        out.append({"effect": "heavier", "strength": 2 if rain >= 2 else 1, "title": "Rain forecast",
                    "detail": f"Up to {rain:.1f} mm/h; wet roads slow everyone down.", "kind": "weather"})
    if fog:
        out.append({"effect": "heavier", "strength": 2, "title": "Fog forecast", "detail": "Visibility under 1 km.", "kind": "weather"})
    return out


def rail_factors(con) -> list[dict]:
    last = con.execute("SELECT max(ts) FROM obs_rail").fetchone()[0]
    if not last or db.now() - last > 1800:
        return []
    rows = con.execute("SELECT relationship, delay_thionville FROM obs_rail WHERE ts = ?", (last,)).fetchall()
    cancelled = sum(1 for r, _ in rows if r == 3)
    late = sum(1 for r, d in rows if r != 3 and (d or 0) >= 600)
    if not cancelled and not late:
        return []
    parts = ([f"{cancelled} cancelled"] if cancelled else []) + ([f"{late} over 10 min late"] if late else [])
    return [{"effect": "heavier", "strength": 2 if cancelled >= 2 else 1, "title": "Train disruption via Thionville",
             "detail": ", ".join(parts) + " right now: some rail commuters switch to the car.", "kind": "rail"}]


def live_trend(con, direction: str, route: str) -> dict | None:
    """From what the collector recorded: is it building up or clearing, and where."""
    last = con.execute("SELECT max(ts) FROM obs_segment").fetchone()[0]
    if not last or db.now() - last > 1500:
        return None
    sites = con.execute("SELECT id, direction, meta FROM sites WHERE source='TTSEG'").fetchall()
    rows = []
    for sid, sdir, meta in sites:
        m = json.loads(meta or "{}")
        if route not in (m.get("routes") or []) or sdir not in ("both", direction):
            continue
        now = con.execute("SELECT ts, speed, free_speed, travel_s FROM obs_segment WHERE site=? AND ts=?", (sid, last)).fetchone()
        prev = con.execute("SELECT speed, travel_s FROM obs_segment WHERE site=? AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1",
                           (sid, last - 45 * 60, last - 20 * 60)).fetchone()
        if not now or not now[2]:
            continue
        rows.append({"name": m.get("name"), "speed": now[1], "free_speed": now[2], "ratio": round(now[1] / now[2], 2),
                     "speed_change": (now[1] - prev[0]) if prev else None})
    if not rows:
        return None
    r_now = con.execute("SELECT ts, travel_s FROM obs_route WHERE route=? AND direction=? ORDER BY ts DESC LIMIT 1",
                        (route, direction)).fetchone()
    r_prev = con.execute("SELECT travel_s FROM obs_route WHERE route=? AND direction=? AND ts BETWEEN ? AND ? "
                         "ORDER BY ts DESC LIMIT 1", (route, direction, (r_now or [0])[0] - 45 * 60, (r_now or [0])[0] - 20 * 60)).fetchone()
    change = round((r_now[1] - r_prev[0]) / 60) if r_now and r_prev else None
    trend = "unknown" if change is None else "building" if change >= 3 else "clearing" if change <= -3 else "steady"
    rows.sort(key=lambda r: r["ratio"])
    return {"as_of": last, "trend": trend, "route_change_min": change, "slowest": rows[:4]}


def tomtom_now_factor(now_result: dict | None) -> list[dict]:
    if not now_result or not now_result.get("travel_s") or not now_result.get("historic_s"):
        return []
    d = round((now_result["travel_s"] - now_result["historic_s"]) / 60)
    if abs(d) < 3:
        return []
    return [{"effect": "heavier" if d > 0 else "lighter", "strength": 2 if abs(d) >= 8 else 1,
             "title": f"{abs(d)} min {'worse' if d > 0 else 'better'} than usual right now",
             "detail": "Live traffic compared with TomTom's typical value for this time.", "kind": "live"}]


async def build(direction: str, mode: str) -> dict:
    now = datetime.now(TZ)
    win = window(mode, direction, now)
    cfg = tomtom.load_corridors()
    names = {c["id"]: c["name"] for c in cfg["corridors"]}
    usual = [c["id"] for c in cfg["corridors"] if c.get("group") == "usual"]

    curves = {}
    for rid in usual:
        c = await tomtom.departure_curve(rid, direction, win["day"], win["start"], win["end"], STEP_MIN)
        curves[rid] = [p for p in c["points"] if p.get("travel_s")]
        scoring.log("tomtom", rid, direction, curves[rid])

    by_depart: dict[str, dict] = {}
    for rid, pts in curves.items():
        for p in pts:
            by_depart.setdefault(p["depart"], {})[rid] = p["travel_s"]
    slots = []
    for dep in sorted(by_depart):
        br = min(by_depart[dep], key=by_depart[dep].get)
        slots.append({"depart": dep, "best_route": br, "best_s": by_depart[dep][br], "by_route": by_depart[dep]})

    # Error range from scored history, per point (depends on how far ahead it is).
    band_basis = None
    for s in slots:
        horizon = datetime.fromisoformat(s["depart"]).timestamp() - now.timestamp()
        b = scoring.band("tomtom", max(0, horizon))
        if b:
            s["low_s"], s["high_s"] = s["best_s"] - b[1], s["best_s"] - b[0]
            band_basis = "From how far off past forecasts were on your routes."

    rec = recommend(slots, names, mode)
    now_results = {}
    if mode == "next":
        try:
            now_results = {r["id"]: r for r in (await tomtom.corridors_now(direction))["results"] if "error" not in r}
        except FeedError:
            pass

    cal = await calendar_ctx.day_context(win["day"])
    factors = list(cal["factors"])
    factors += await weather_factors(win["day"], win["start"], win["end"])
    con = db.connect()
    try:
        if mode == "next":
            factors += rail_factors(con)
            factors += tomtom_now_factor(now_results.get(slots[0]["best_route"]) if slots else None)
        live = live_trend(con, direction, slots[0]["best_route"] if slots else usual[0]) if mode == "next" else None
    finally:
        con.close()
    if not any(f["kind"] == "calendar" for f in factors):
        factors.insert(0, {"effect": "mixed", "strength": 0, "title": "Normal working day",
                           "detail": "No holidays or bridge days in any of the four countries.", "kind": "calendar"})

    acc = scoring.accuracy(source="tomtom")
    return {
        "direction": direction, "window": {**win, "day": win["day"].isoformat()},
        "routes": {rid: {"name": names[rid], "points": [{"depart": p["depart"], "travel_s": p["travel_s"],
                                                         "free_s": p.get("free_s"), "arrive": _arrive(p["depart"], p["travel_s"])}
                                                        for p in pts]} for rid, pts in curves.items()},
        "slots": slots,
        "recommendation": rec,
        "route_notes": route_switches(slots, names, usual),
        "band_basis": band_basis,
        "factors": factors,
        "live": live,
        "forecast_source": "TomTom traffic forecast (our own model takes over once enough data is recorded)",
        "accuracy": {"scored": acc["scored"], "groups": acc["groups"]},
    }
