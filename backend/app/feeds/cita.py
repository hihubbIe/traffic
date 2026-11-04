"""CITA (Luxembourg motorway traffic centre) open feeds, published on data.public.lu.

All feeds are free and keyless. DATEX II namespaces differ between feeds, so
lookups use the '{*}' namespace wildcard.
"""
import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from ..http import FeedError, cached, get_bytes

ROADS = ["a1", "a3", "a4", "a6", "a7", "a13", "b40"]
TRAFFIC_URL = "https://www.cita.lu/info_trafic/datex/trafficstatus_{road}"
EVENTS_URL = "https://cita.lu/info_trafic/datex/situationrecord36"
TRAVEL_TIMES_URL = "https://cita.lu/kml/temps_parcours.kml"
CAMERAS_URL = "https://www.cita.lu/kml/cameras.kml"
INTERCHANGES_URL = "https://www.cita.lu/kml/echangeurs.kml"

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


def _f(el: ET.Element | None, path: str) -> float | None:
    if el is None:
        return None
    node = el.find(path)
    if node is None or node.text is None:
        return None
    try:
        return float(node.text)
    except ValueError:
        return None


def _t(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    node = el.find(path)
    return node.text.strip() if node is not None and node.text else None


def parse_traffic_status(xml: bytes, road: str) -> list[dict]:
    root = ET.fromstring(xml)
    sites = []
    for sm in root.iterfind(".//{*}siteMeasurements"):
        ref = sm.find("{*}measurementSiteReference")
        if ref is None:
            continue
        site = {
            "id": ref.get("id"),
            "road": road.upper(),
            "time": _t(sm, "{*}measurementTimeDefault"),
            "lat": None, "lon": None, "direction": None, "chainage": None,
            "speed": None, "occupancy": None, "flow": None,
        }
        for bd in sm.iterfind(".//{*}basicData"):
            kind = bd.get(XSI_TYPE, "")
            if kind.endswith("TrafficSpeed"):
                site["speed"] = _f(bd, ".//{*}averageVehicleSpeed/{*}speed")
                site["lat"] = _f(bd, ".//{*}locationForDisplay/{*}latitude")
                site["lon"] = _f(bd, ".//{*}locationForDisplay/{*}longitude")
                site["direction"] = _t(bd, ".//{*}directionBoundOnLinearSection")
                site["chainage"] = _f(bd, ".//{*}fromPoint/{*}distanceAlong")
            elif kind.endswith("TrafficConcentration"):
                site["occupancy"] = _f(bd, ".//{*}occupancy/{*}percentage")
            elif kind.endswith("TrafficFlow"):
                site["flow"] = _f(bd, ".//{*}vehicleFlowRate")
        # Negative values are "no data" markers in some feeds.
        for k in ("speed", "flow", "occupancy"):
            if site[k] is not None and site[k] < 0:
                site[k] = None
        if site["lat"] is not None:
            sites.append(site)
    return sites


async def traffic_status() -> dict:
    async def fetch_road(road: str):
        try:
            return parse_traffic_status(await get_bytes(TRAFFIC_URL.format(road=road)), road), None
        except (FeedError, ET.ParseError) as e:
            return [], f"{road}: {e}"

    async def produce():
        results = await asyncio.gather(*(fetch_road(r) for r in ROADS))
        sites = [s for res, _ in results for s in res]
        errors = [err for _, err in results if err]
        return {"fetched": _now(), "sites": sites, "errors": errors}

    return await cached("cita_traffic", 55, produce)


def _comment(rec: ET.Element) -> list[str]:
    out = []
    for gpc in rec.findall("{*}generalPublicComment"):
        for v in gpc.iterfind(".//{*}value"):
            if v.text and v.text.strip():
                out.append(v.text.strip())
    return out


def parse_events(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    features = []
    for rec in root.iterfind(".//{*}situationRecord"):
        kind = rec.get(XSI_TYPE, "").split(":")[-1]
        props = {
            "id": rec.get("id"),
            "source": "CITA",
            "kind": kind,
            "start": _t(rec, ".//{*}overallStartTime"),
            "end": _t(rec, ".//{*}overallEndTime"),
            "lanesRestricted": _f(rec, ".//{*}numberOfLanesRestricted"),
            "lanesOperational": _f(rec, ".//{*}numberOfOperationalLanes"),
            "road": _t(rec, ".//{*}roadName"),
            "destination": _t(rec, ".//{*}roadDestination"),
            "lengthAffected": _f(rec, ".//{*}lengthAffected"),
            "comments": _comment(rec),
        }
        lines = []
        for pl in rec.iterfind(".//{*}posList"):
            nums = [float(x) for x in (pl.text or "").split()]
            # posList is "lat lon lat lon ..." in EPSG:4326.
            coords = [[nums[i + 1], nums[i]] for i in range(0, len(nums) - 1, 2)]
            if len(coords) >= 2:
                lines.append(coords)
        points = []
        for pc in rec.iterfind(".//{*}pointCoordinates"):
            lat, lon = _f(pc, "{*}latitude"), _f(pc, "{*}longitude")
            if lat is not None and lon is not None:
                points.append([lon, lat])
        if lines:
            geom = {"type": "MultiLineString", "coordinates": lines}
        elif points:
            geom = {"type": "MultiPoint", "coordinates": points}
        else:
            continue
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return features


async def events() -> dict:
    async def produce():
        return {"type": "FeatureCollection", "fetched": _now(),
                "features": parse_events(await get_bytes(EVENTS_URL))}
    return await cached("cita_events", 120, produce)


_PLACEMARK = re.compile(r"<Placemark[^>]*?(?:id\s*=\s*'([^']*)'|id=\"([^\"]*)\")?[^>]*>(.*?)</Placemark>", re.S)


def _placemarks(kml: str):
    for m in _PLACEMARK.finditer(kml):
        body = m.group(3)
        name = re.search(r"<name>([^<]*)</name>", body)
        coords = re.search(r"<coordinates>([^<]+)</coordinates>", body)
        desc = re.search(r"<description>(.*?)</description>", body, re.S)
        if not coords:
            continue
        lon, lat = (float(x) for x in coords.group(1).strip().split(",")[:2])
        yield (m.group(1) or m.group(2), name.group(1).strip() if name else "",
               desc.group(1) if desc else "", lon, lat)


async def travel_times() -> dict:
    """Variable message signs showing live travel times (e.g. 'LUX-SUD: 18min')."""
    async def produce():
        kml = (await get_bytes(TRAVEL_TIMES_URL)).decode("utf-8", "replace")
        feats = []
        for _id, name, desc, lon, lat in _placemarks(kml):
            entries = []
            for dest, minutes in re.findall(r"<span class='time'>\s*([^:<]+):\s*(\d+)\s*min", desc):
                entries.append({"destination": dest.strip(), "minutes": int(minutes)})
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                          "properties": {"name": name, "times": entries}})
        return {"type": "FeatureCollection", "fetched": _now(), "features": feats}
    return await cached("cita_tt", 60, produce)


async def cameras() -> dict:
    async def produce():
        kml = (await get_bytes(CAMERAS_URL)).decode("utf-8", "replace")
        feats = []
        for _id, name, desc, lon, lat in _placemarks(kml):
            src = re.search(r'src="([^"]+)"', desc)
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                          "properties": {"id": _id, "name": name, "url": src.group(1) if src else None}})
        return {"type": "FeatureCollection", "features": feats}
    return await cached("cita_cams", 24 * 3600, produce)


async def interchanges() -> dict:
    async def produce():
        kml = (await get_bytes(INTERCHANGES_URL)).decode("utf-8", "replace")
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                  "properties": {"name": name}}
                 for _id, name, _d, lon, lat in _placemarks(kml) if name.lower() != "echangeurs"]
        return {"type": "FeatureCollection", "features": feats}
    return await cached("cita_ech", 24 * 3600, produce)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
