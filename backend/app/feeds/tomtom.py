"""TomTom APIs (free tier): flow tiles, incident details, routing with traffic.

The key stays server-side; the frontend only talks to this backend.
Request budget matters on the free tier, so everything is cached.
"""
import asyncio
import contextvars
import json
import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .. import budget
from ..config import BBOX, STATIC_DIR, tomtom_key
from ..http import FeedError, cached, client, polite_get

TZ = ZoneInfo("Europe/Luxembourg")
FLOW_TILE_URL = "https://api.tomtom.com/traffic/map/4/tile/flow/{style}/{z}/{x}/{y}.png"
INCIDENTS_URL = "https://api.tomtom.com/traffic/services/5/incidentDetails"
ROUTE_URL = "https://api.tomtom.com/routing/1/calculateRoute/{locs}/json"
SEGMENT_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

ICON_CATEGORY = {
    0: "Unknown", 1: "Accident", 2: "Fog", 3: "Dangerous conditions", 4: "Rain", 5: "Ice",
    6: "Jam", 7: "Lane closed", 8: "Road closed", 9: "Road works", 10: "Wind",
    11: "Flooding", 14: "Broken down vehicle",
}


class NoKey(FeedError):
    pass


def _key() -> str:
    k = tomtom_key()
    if not k:
        raise NoKey("TOMTOM_API_KEY is empty - put your key in .env and restart")
    return k


# Set by the collector so its requests stop earlier and leave budget for the app.
BACKGROUND: contextvars.ContextVar[bool] = contextvars.ContextVar("tomtom_background", default=False)


async def _get(url: str, params: dict, api: str) -> dict | bytes:
    """One TomTom call: counted against the daily budget, spaced per host, retried on 429."""
    params = {**params, "key": _key()}
    try:
        budget.consume(api, background=BACKGROUND.get())
    except budget.BudgetExceeded as e:
        raise FeedError(str(e)) from e
    for attempt in range(3):
        r = await (client().get(url, params=params) if api == "tiles" else polite_get(url, params=params))
        if r.status_code == 429 and attempt < 2:
            await asyncio.sleep(2.0 * (attempt + 1))
            continue
        break
    if r.status_code != 200:
        detail = r.text[:200] if "json" in r.headers.get("content-type", "") else ""
        raise FeedError(f"TomTom HTTP {r.status_code} {detail}")
    return r.json() if "json" in r.headers.get("content-type", "") else r.content


async def flow_tile(z: int, x: int, y: int, style: str = "relative0") -> bytes:
    async def produce():
        return await _get(FLOW_TILE_URL.format(style=style, z=z, x=x, y=y), {"tileSize": 256}, "tiles")
    return await cached(f"tt_tile:{style}:{z}:{x}:{y}", 120, produce)


async def incidents() -> dict:
    fields = ("{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,"
              "events{description,code},startTime,endTime,from,to,length,delay,roadNumbers}}}")

    async def produce():
        data = await _get(INCIDENTS_URL, {
            "bbox": ",".join(str(v) for v in BBOX), "fields": fields,
            "language": "en-GB", "timeValidityFilter": "present",
        }, "incidents")
        feats = []
        for inc in data.get("incidents", []):
            p = inc.get("properties", {})
            feats.append({"type": "Feature", "geometry": inc.get("geometry"), "properties": {
                "id": p.get("id"), "source": "TomTom",
                "category": ICON_CATEGORY.get(p.get("iconCategory"), str(p.get("iconCategory"))),
                "iconCategory": p.get("iconCategory"),
                "magnitude": p.get("magnitudeOfDelay"),
                "description": "; ".join(e.get("description", "") for e in p.get("events") or []),
                "from": p.get("from"), "to": p.get("to"),
                "start": p.get("startTime"), "end": p.get("endTime"),
                "length": p.get("length"), "delay": p.get("delay"),
                "roads": p.get("roadNumbers") or [],
            }})
        return {"type": "FeatureCollection", "fetched": datetime.now(TZ).isoformat(), "features": feats}
    return await cached("tt_incidents", 120, produce)


def load_corridors() -> dict:
    cfg = json.loads((STATIC_DIR / "corridors.json").read_text(encoding="utf-8"))
    # Home/Work are private (places.json is gitignored); fall back to the public example.
    places = STATIC_DIR / "places.json"
    if not places.exists():
        places = STATIC_DIR / "places.example.json"
    cfg["endpoints"] = json.loads(places.read_text(encoding="utf-8"))["endpoints"]
    return cfg


DIRECTIONS = ("to_work", "to_home")


def _locations(cfg: dict, corridor: dict, direction: str) -> list[list[float]]:
    home, work = cfg["endpoints"]["home"]["coord"], cfg["endpoints"]["work"]["coord"]
    via = corridor.get("via", [])
    if isinstance(via, dict):  # per-direction waypoints, already in travel order
        return [home, *via[direction], work] if direction == "to_work" else [work, *via[direction], home]
    pts = [home, *via, work]
    return pts if direction == "to_work" else list(reversed(pts))


def _dist_m(lat1, lon1, lat2, lon2) -> float:
    k = math.pi / 180
    x = (lon2 - lon1) * k * math.cos((lat1 + lat2) * k / 2)
    return math.hypot(x, (lat2 - lat1) * k) * 6371000


def _passes(points: list[list[float]], markers: dict) -> list[str]:
    """Which named markers the route geometry passes within their radius."""
    hits = []
    for name, m in markers.items():
        lon, lat, r = m["coord"][0], m["coord"][1], m.get("radius", 1500)
        if any(_dist_m(lat, lon, p[1], p[0]) < r for p in points[::3]):
            hits.append(name)
    return hits


async def _route(locs: list[list[float]], depart: str = "now") -> dict:
    loc_str = ":".join(f"{lat},{lon}" for lon, lat in locs)
    data = await _get(ROUTE_URL.format(locs=loc_str), {
        "traffic": "true", "travelMode": "car", "routeType": "fastest",
        "computeTravelTimeFor": "all", "departAt": depart, "routeRepresentation": "polyline",
        "sectionType": "traffic",
    }, "routing")
    route = data["routes"][0]
    s = route["summary"]
    points = [[p["longitude"], p["latitude"]] for leg in route["legs"] for p in leg["points"]]
    # Slowdowns along the route; indices refer to `points`.
    traffic = [{
        "start": sec.get("startPointIndex"), "end": sec.get("endPointIndex"),
        "category": sec.get("simpleCategory"), "magnitude": sec.get("magnitudeOfDelay"),
        "delay_s": sec.get("delayInSeconds"), "speed_kmh": sec.get("effectiveSpeedInKmh"),
    } for sec in route.get("sections", []) if sec.get("sectionType") == "TRAFFIC"]
    return {
        "length_m": s.get("lengthInMeters"),
        "travel_s": s.get("travelTimeInSeconds"),
        "delay_s": s.get("trafficDelayInSeconds"),
        "free_s": s.get("noTrafficTravelTimeInSeconds"),
        "historic_s": s.get("historicTrafficTravelTimeInSeconds"),
        "departure": s.get("departureTime"),
        "arrival": s.get("arrivalTime"),
        "points": points,
        "traffic": traffic,
    }


async def corridors_now(direction: str) -> dict:
    cfg = load_corridors()

    async def one(c):
        try:
            r = await _route(_locations(cfg, c, direction))
            r["passes"] = _passes(r["points"], cfg.get("markers", {}))
            return {"id": c["id"], **r}
        except FeedError as e:
            return {"id": c["id"], "error": str(e)}

    async def produce():
        results = await asyncio.gather(*(one(c) for c in cfg["corridors"]))
        out = {"direction": direction, "fetched": datetime.now(TZ).isoformat(), "results": results}
        if any("error" in r for r in results):
            raise _PartialResult(out)
        return out

    try:
        return await cached(f"tt_corr:{direction}", 180, produce)
    except _PartialResult as p:
        return p.value  # returned but not cached, so the next call retries


class _PartialResult(Exception):
    def __init__(self, value):
        self.value = value


async def departure_curve(corridor_id: str, direction: str, day: date,
                          start: str, end: str, step_min: int = 15) -> dict:
    """Predicted travel time for departures across a window (TomTom historic + live model)."""
    cfg = load_corridors()
    corridor = next((c for c in cfg["corridors"] if c["id"] == corridor_id), None)
    if corridor is None:
        raise FeedError(f"unknown corridor {corridor_id}")
    locs = _locations(cfg, corridor, direction)
    t0 = datetime.combine(day, time.fromisoformat(start), TZ)
    t1 = datetime.combine(day, time.fromisoformat(end), TZ)
    now = datetime.now(TZ)
    slots = []
    t = t0
    while t <= t1:
        slots.append(t)
        t += timedelta(minutes=step_min)

    async def one(slot: datetime):
        if slot < now - timedelta(minutes=1):
            return {"depart": slot.isoformat(), "travel_s": None, "past": True}
        depart = "now" if slot < now + timedelta(minutes=2) else slot.isoformat(timespec="seconds")
        key = f"tt_curve:{corridor_id}:{direction}:{slot.isoformat()}"
        try:
            r = await cached(key, 3600, lambda: _route(locs, depart))
            return {"depart": slot.isoformat(), "travel_s": r["travel_s"], "free_s": r["free_s"],
                    "historic_s": r["historic_s"], "delay_s": r["delay_s"]}
        except FeedError as e:
            return {"depart": slot.isoformat(), "travel_s": None, "error": str(e)}

    # Keep concurrency low to stay friendly with the free-tier QPS limit.
    sem = asyncio.Semaphore(3)

    async def guarded(slot):
        async with sem:
            return await one(slot)

    points = await asyncio.gather(*(guarded(s) for s in slots))
    return {"corridor": corridor_id, "direction": direction, "day": day.isoformat(), "points": points}


async def segment_flow(lon: float, lat: float) -> dict:
    """Current and free-flow speed on the road segment nearest to a point."""
    data = await _get(SEGMENT_URL, {"point": f"{lat},{lon}", "unit": "KMPH"}, "flow_segment")
    f = data["flowSegmentData"]
    return {"speed": f.get("currentSpeed"), "free_speed": f.get("freeFlowSpeed"),
            "travel_s": f.get("currentTravelTime"), "free_travel_s": f.get("freeFlowTravelTime"),
            "confidence": f.get("confidence"), "closed": int(bool(f.get("roadClosure"))), "frc": f.get("frc")}
