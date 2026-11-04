"""SNCF realtime (GTFS-RT, national feed via transport.data.gouv.fr): trains on the
Metz - Thionville - Luxembourg line with delays or cancellations, and service alerts.

The feed only lists trips that have realtime changes, which is exactly what matters:
a cancelled or late commuter train pushes people back into cars.
"""
from google.transit import gtfs_realtime_pb2 as rt

from ..http import FeedError, get_if_changed

TRIPS_URL = "https://proxy.transport.data.gouv.fr/resource/sncf-gtfs-rt-trip-updates"
ALERTS_URL = "https://proxy.transport.data.gouv.fr/resource/sncf-gtfs-rt-service-alerts"

# UIC codes of the stations that define "our" line.
STOPS = {"87191007": "Thionville", "82001000": "Luxembourg", "87192039": "Metz", "82001100": "Bettembourg"}
THIONVILLE = "87191007"


def _uic(stop_id: str) -> str | None:
    return next((code for code in STOPS if code in stop_id), None)


def _parse(content: bytes) -> rt.FeedMessage:
    feed = rt.FeedMessage()
    try:
        feed.ParseFromString(content)
    except Exception as e:  # protobuf DecodeError
        raise FeedError(f"GTFS-RT decode: {e}") from e
    return feed


async def trips() -> list[dict] | None:
    """Trips serving Thionville or Luxembourg with realtime info; None if the feed didn't change."""
    content = await get_if_changed(TRIPS_URL)
    if content is None:
        return None
    out = []
    for e in _parse(content).entity:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        stops = [(s, _uic(s.stop_id)) for s in tu.stop_time_update]
        if not any(code in (THIONVILLE, "82001000") for _, code in stops):
            continue
        delays = [max(s.arrival.delay, s.departure.delay) for s, _ in stops]
        thio = next((max(s.arrival.delay, s.departure.delay) for s, code in stops if code == THIONVILLE), None)
        out.append({
            "trip": tu.trip.trip_id, "relationship": tu.trip.schedule_relationship,
            "delay_thionville": thio, "max_delay": max(delays) if delays else None,
            "origin": stops[0][0].stop_id.rsplit("-", 1)[-1] if stops else None,
            "destination": stops[-1][0].stop_id.rsplit("-", 1)[-1] if stops else None,
        })
    return out


async def alerts() -> list[dict] | None:
    content = await get_if_changed(ALERTS_URL)
    if content is None:
        return None
    out = []
    for e in _parse(content).entity:
        a = e.alert
        hit = any(_uic(ie.stop_id or "") or any(c in (ie.trip.trip_id or "") for c in STOPS) for ie in a.informed_entity)
        if not hit:
            continue
        text = a.header_text.translation[0].text if a.header_text.translation else ""
        desc = a.description_text.translation[0].text if a.description_text.translation else ""
        periods = [(p.start, p.end) for p in a.active_period]
        out.append({"id": e.id, "effect": a.effect, "cause": a.cause, "header": text, "description": desc[:2000],
                    "periods": periods})
    return out
