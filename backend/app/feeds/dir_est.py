"""DIR Est speed/flow stations via Bison Futé open data (tipi).

The feed is national; we keep the Moselle stations (ids containing '57').
The official station reference has no coordinates for DIR Est, so ids are linked to
named count stations (placed by PR) through data/static/dir_stations.json.
"""
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from ..dir_matching import load_assignments, load_count_stations, station_key
from ..http import cached, get_bytes, get_if_changed

QTV_URL = "http://tipi.bison-fute.gouv.fr/bison-fute-ouvert/publicationsDIR/QTV-DIR/qtvDir.xml"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


def is_moselle(site_id: str) -> bool:
    return site_id.upper().startswith("MZ") and "57" in site_id


def parse_qtv(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for sm in root.iterfind(".//{*}siteMeasurements"):
        ref = sm.find("{*}measurementSiteReference")
        if ref is None or not is_moselle(ref.get("id", "")):
            continue
        st = {"id": ref.get("id"), "time": None, "flow": None, "speed": None}
        t = sm.find("{*}measurementTimeDefault")
        st["time"] = t.text if t is not None else None
        for bd in sm.iterfind(".//{*}basicData"):
            kind = bd.get(XSI_TYPE, "")
            if kind.endswith("TrafficFlow"):
                node, key = bd.find(".//{*}vehicleFlowRate"), "flow"
            elif kind.endswith("TrafficSpeed"):
                node, key = bd.find(".//{*}speed"), "speed"
            else:
                continue
            if node is not None and node.text:
                try:
                    v = float(node.text)
                    st[key] = v if v >= 0 else None
                except ValueError:
                    pass
        out.append(st)
    return out


def _resolve(data: list[dict]) -> None:
    stations = {station_key(s): s for s in load_count_stations()}
    assigned = load_assignments().get("stations", {})
    for st in data:
        base, sfx = st["id"][:-1], st["id"][-1]
        a = assigned.get(base)
        cs = stations.get(a["station_key"]) if a else None
        st.update({"lat": None, "lon": None, "road": None, "label": None, "pr": None,
                   "sens": sfx, "tmja": None, "match": a.get("source") if a else None})
        if cs:
            st.update({"lon": cs["coord"][0], "lat": cs["coord"][1], "road": cs["road"], "pr": cs["pr"],
                       "label": f"{cs['road']} {cs['name']}", "tmja": cs.get(f"tmja_sens{sfx}")})


async def stations() -> dict:
    async def produce():
        return parse_qtv(await get_bytes(QTV_URL))
    # Upstream refreshes every 6 minutes; placements are re-read on every call.
    data = [dict(s) for s in await cached("dir_qtv", 120, produce)]
    _resolve(data)
    data.sort(key=lambda s: (s["label"] is None, s["id"]))
    return {"fetched": datetime.now(timezone.utc).isoformat(), "stations": data}


async def qtv_if_changed() -> bytes | None:
    """The national file (~1.3 MB) only when it changed since our last download."""
    return await get_if_changed(QTV_URL)
