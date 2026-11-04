"""French national-road events (roadworks, accidents, closures) from Bison Futé / tipi.

One DATEX II file per event; the directory keeps about 24 h of files. We list it, download
only files we haven't seen, and keep events inside the study area.
"""
import re
import xml.etree.ElementTree as ET

from ..config import BBOX
from ..http import HOST_GAP, get_bytes, polite_get

BASE = "http://tipi.bison-fute.gouv.fr/bison-fute-ouvert/publicationsDIR/Evenementiel-DIR/grt/RRN/"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

# Public server, one file per event nationwide: download each file once, 2 s apart.
HOST_GAP["tipi.bison-fute.gouv.fr"] = 2.0
_MAX_NEW_PER_RUN = 60
_seen: set[str] = set()
_loaded = False


def seen_loaded() -> bool:
    return _loaded


def load_seen(names) -> None:
    """Files already downloaded before a restart (persisted by the collector)."""
    global _loaded
    _seen.update(names)
    _loaded = True


def _in_area(lon: float, lat: float) -> bool:
    # A bit wider than the map: A31 down to Metz, A30 to Longwy.
    return BBOX[0] - 0.15 <= lon <= BBOX[2] + 0.1 and BBOX[1] - 0.25 <= lat <= BBOX[3] + 0.05


def _t(el, path):
    n = el.find(path)
    return n.text.strip() if n is not None and n.text else None


def parse(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for rec in root.iterfind(".//{*}situationRecord"):
        lat, lon = _t(rec, ".//{*}latitude"), _t(rec, ".//{*}longitude")
        if lat is None or lon is None or not _in_area(float(lon), float(lat)):
            continue
        comments = [v.text.strip() for v in rec.iterfind(".//{*}generalPublicComment//{*}value") if v.text]
        out.append({
            "id": rec.get("id"), "kind": rec.get(XSI_TYPE, "").split(":")[-1],
            "lat": float(lat), "lon": float(lon), "road": _t(rec, ".//{*}roadNumber"),
            "start": _t(rec, ".//{*}overallStartTime"), "end": _t(rec, ".//{*}overallEndTime"),
            "severity": _t(rec, ".//{*}overallSeverity") or _t(root, ".//{*}overallSeverity"),
            "lanes_restricted": _t(rec, ".//{*}numberOfLanesRestricted"),
            "comments": comments,
        })
    return out


async def new_events() -> tuple[list[dict], list[str]]:
    """(events in our area, file names downloaded) for files not seen before."""
    r = await polite_get(BASE)
    if r.status_code != 200:
        from ..http import FeedError
        raise FeedError(f"{BASE}: HTTP {r.status_code}")
    names = re.findall(r'href="(\d+\.xml)"', r.text)
    fresh = [n for n in names if n not in _seen]
    if not _loaded or len(fresh) > _MAX_NEW_PER_RUN * 3:
        # First run with no memory: only the newest files, mark the rest as seen.
        skipped = fresh[:-_MAX_NEW_PER_RUN]
        _seen.update(skipped)
        fresh = fresh[-_MAX_NEW_PER_RUN:]
    else:
        skipped = []
    out, done = [], []
    for name in fresh:
        try:
            out.extend(parse(await get_bytes(BASE + name)))
        except ET.ParseError:
            pass
        _seen.add(name)
        done.append(name)
    if len(_seen) > 20000:  # the listing only holds ~24 h
        _seen.intersection_update(names)
    return out, done + skipped
