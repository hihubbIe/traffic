"""Calendar context for a commute day: public and school holidays in the four countries whose
commuters share the roads (FR Moselle/Grand Est, LU, DE Saarland + Rhineland-Palatinate, BE),
bridge days, clock changes, weekday effects.

Source: OpenHolidays API (free). Fetched about once a month into a small cache file
(8 requests), so day lookups are local.
"""
import asyncio
import json
import time
from datetime import date, timedelta

from .config import RECORDINGS_DIR
from .http import FeedError, polite_get

API = "https://openholidaysapi.org"
CACHE = RECORDINGS_DIR / "calendar.json"
REFRESH_S = 30 * 86400

# Which subdivisions matter for this corridor.
COUNTRIES = {
    "LU": {"name": "Luxembourg", "public": None, "school": None},
    "FR": {"name": "France", "public": {"FR-GE-MO"}, "school": {"FR-GE"}},
    "DE": {"name": "Germany", "public": {"DE-SL", "DE-RP"}, "school": {"DE-SL", "DE-RP"}},
    "BE": {"name": "Belgium", "public": None, "school": None},
}

_lock = asyncio.Lock()
_data: dict | None = None


def _relevant(h: dict, wanted: set | None) -> bool:
    if h.get("nationwide") or wanted is None:
        return True
    codes = {s.get("code", "") for s in h.get("subdivisions", [])}
    return any(c == w or c.startswith(w + "-") for c in codes for w in wanted)


async def _fetch() -> dict:
    start, end = date.today() - timedelta(days=40), date.today() + timedelta(days=420)
    entries = []
    for cc, cfg in COUNTRIES.items():
        for kind, path in (("public", "PublicHolidays"), ("school", "SchoolHolidays")):
            r = await polite_get(f"{API}/{path}", params={
                "countryIsoCode": cc, "validFrom": start.isoformat(), "validTo": end.isoformat(), "languageIsoCode": "EN"})
            if r.status_code != 200:
                raise FeedError(f"OpenHolidays {cc} {kind}: HTTP {r.status_code}")
            seen = set()
            for h in r.json():
                if not _relevant(h, cfg[kind]):
                    continue
                name = next((n["text"] for n in h.get("name", [])), "Holiday")
                key = (h["startDate"], h["endDate"], name)
                if key in seen:  # e.g. Belgian communities listed twice
                    continue
                seen.add(key)
                entries.append({"country": cc, "kind": kind, "start": h["startDate"], "end": h["endDate"], "name": name})
    return {"fetched": time.time(), "from": start.isoformat(), "to": end.isoformat(), "entries": entries}


async def ensure() -> dict:
    """Cached calendar; refreshed when older than 30 days. Falls back to a stale cache offline."""
    global _data
    async with _lock:
        if _data is None and CACHE.exists():
            _data = json.loads(CACHE.read_text(encoding="utf-8"))
        if _data is None or time.time() - _data["fetched"] > REFRESH_S:
            try:
                _data = await _fetch()
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(json.dumps(_data, ensure_ascii=False), encoding="utf-8")
            except FeedError:
                if _data is None:
                    raise
        return _data


def _on(entries: list, d: date, kind: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for e in entries:
        if e["kind"] == kind and e["start"] <= d.isoformat() <= e["end"]:
            out.setdefault(e["country"], []).append(e["name"])
    return out


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def factors_for(cal: dict, d: date) -> list[dict]:
    """Things that make this day's commute lighter or heavier than a normal working day.

    effect: 'lighter' | 'heavier' | 'mixed'; strength 1-3 (expected size, not yet measured).
    """
    entries = cal["entries"]
    public = _on(entries, d, "public")
    school = _on(entries, d, "school")
    f = []
    add = lambda effect, strength, title, detail, kind: f.append(
        {"effect": effect, "strength": strength, "title": title, "detail": detail, "kind": kind})

    if d.weekday() >= 5:
        add("lighter", 3, "Weekend", "No commute peak.", "calendar")
        return f
    if "LU" in public:
        add("lighter", 3, f"Luxembourg holiday: {public['LU'][0]}",
            "Most cross-border commuters are off; the morning and evening peaks mostly disappear.", "calendar")
    if "FR" in public and "LU" not in public:
        add("mixed", 2, f"French holiday: {public['FR'][0]}",
            "Luxembourg works: cross-border commuters still drive, but local French traffic and trucks are lighter.", "calendar")
    if "DE" in public and "LU" not in public:
        add("lighter", 1, f"German holiday: {public['DE'][0]}",
            "Fewer Saarland and Rhineland-Palatinate cars, mostly felt on the A13.", "calendar")
    if "BE" in public and "LU" not in public:
        add("lighter", 1, f"Belgian holiday: {public['BE'][0]}", "Fewer Belgian commuters on the A13 towards Belval.", "calendar")

    for cc in ("LU", "FR"):  # bridge days: Monday before a Tuesday holiday, Friday after a Thursday one
        nxt, prv = _on(entries, d + timedelta(days=1), "public"), _on(entries, d - timedelta(days=1), "public")
        if cc not in public and ((d.weekday() == 0 and cc in nxt) or (d.weekday() == 4 and cc in prv)):
            add("lighter", 2, f"Bridge day ({COUNTRIES[cc]['name']})",
                "Many people take the day off between a holiday and the weekend.", "calendar")

    if "LU" in school:
        add("lighter", 2, f"Luxembourg school holidays: {school['LU'][0]}", "Parents off, no school runs in Luxembourg.", "calendar")
    if "FR" in school:
        add("lighter", 2, f"French school holidays (Grand Est): {school['FR'][0]}",
            "Parents off, no school runs around Thionville and Audun-le-Tiche.", "calendar")
    if "DE" in school:
        add("lighter", 1, f"German school holidays: {school['DE'][0]}", "Slightly fewer Saarland/RLP commuters.", "calendar")
    if "BE" in school:
        add("lighter", 1, f"Belgian school holidays: {school['BE'][0]}", "Slightly fewer Belgian commuters.", "calendar")

    if d.weekday() in (0, 4):
        add("lighter", 1, "Monday" if d.weekday() == 0 else "Friday",
            "Telework is most common on Mondays and Fridays." + (" Friday evening peak starts earlier." if d.weekday() == 4 else ""),
            "calendar")

    for month in (3, 10):  # daylight-saving change: the first days are darker at peak time
        change = _last_sunday(d.year, month)
        if 0 < (d - change).days <= 5:
            add("mixed", 1, "Clocks changed on Sunday",
                "Darker " + ("mornings" if month == 3 else "evenings") + " this week; slightly slower driving.", "calendar")
    return f


async def day_context(d: date) -> dict:
    cal = await ensure()
    return {"date": d.isoformat(), "public": _on(cal["entries"], d, "public"),
            "school": _on(cal["entries"], d, "school"), "factors": factors_for(cal, d)}
