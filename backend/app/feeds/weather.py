"""Hourly weather along the corridor from Open-Meteo (free, no key).

Open-Meteo returns past hours on request (past_days), so one call a day covering the
last two days is enough; overlapping hours simply overwrite.
"""
from ..http import FeedError, polite_get

URL = "https://api.open-meteo.com/v1/forecast"
PLACES = {  # rough points, not addresses
    "thionville": (6.16, 49.36),
    "aumetz": (5.94, 49.42),
    "belval": (5.95, 49.50),
}
HOURLY = ["temperature_2m", "precipitation", "rain", "snowfall", "weather_code",
          "wind_speed_10m", "visibility", "cloud_cover"]


async def hourly_past(days: int = 2) -> list[dict]:
    """[{place, ts, temp, precip, rain, snowfall, code, wind, visibility, cloud}] for the past `days` days."""
    names = list(PLACES)
    r = await polite_get(URL, params={
        "latitude": ",".join(str(PLACES[n][1]) for n in names),
        "longitude": ",".join(str(PLACES[n][0]) for n in names),
        "hourly": ",".join(HOURLY), "past_days": days, "forecast_days": 1, "timeformat": "unixtime",
        "timezone": "UTC",
    })
    if r.status_code != 200:
        raise FeedError(f"Open-Meteo HTTP {r.status_code}")
    data = r.json()
    data = data if isinstance(data, list) else [data]
    out = []
    for name, loc in zip(names, data):
        h = loc["hourly"]
        for i, ts in enumerate(h["time"]):
            out.append({"place": name, "ts": int(ts), "temp": h["temperature_2m"][i], "precip": h["precipitation"][i],
                        "rain": h["rain"][i], "snowfall": h["snowfall"][i], "code": h["weather_code"][i],
                        "wind": h["wind_speed_10m"][i], "visibility": h["visibility"][i], "cloud": h["cloud_cover"][i]})
    return out
