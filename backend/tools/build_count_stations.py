"""Builds data/static/count_stations.json: DIR Est (Myrabel) permanent count stations in
Moselle, placed on the map from their road + PR (point de repère).

Inputs embedded below:
- STATIONS: DIR Est "Données trafic Myrabel 2024" table (road, PR, name, 2024 TMJA per
  direction, % HGV). Sens 1 (+) = increasing PR (north/west), sens 2 (-) = decreasing PR.
  https://www.dir.est.developpement-durable.gouv.fr/IMG/pdf/donnees_trafic_myrabel_2024.pdf
- ANCHORS: official PR milestones mapped in OpenStreetMap (nat_ref 57PRxxx, source data.gouv.fr).
- Road geometry: one TomTom route per road; PR is interpolated along it between anchors.

Run from backend/:  .venv/Scripts/python -m tools.build_count_stations
"""
import asyncio
import json
import math

from app.config import STATIC_DIR
from app.feeds import tomtom

# road, PR, name, TMJA sens 2 (-), TMJA sens 1 (+), %HGV (both)
STATIONS = [
    ("A30", 1.000, "Uckange", 21216, 17667, 11.75),
    ("A30", 11.380, "Hayange", 12496, 12287, 16.70),
    ("A30", 24.000, "Boulange", 14908, 15568, 14.40),
    ("A31", 290.770, "Fey", 29790, 29112, 16.85),
    ("A31", 294.440, "Augny", 29039, 28389, 15.05),
    ("A31", 297.020, "Jouy (hors échangeur)", 35613, 34955, 11.50),
    ("A31", 301.410, "Metz Sud", 36289, 36289, 11.70),
    ("A31", 302.910, "Metz Centre (bretelles)", 22317, 22808, 3.95),
    ("A31", 305.760, "Metz Nord", 44373, 44668, 9.90),
    ("A31", 307.750, "La Maxe", 39888, 38920, 9.85),
    ("A31", 311.400, "Saint-Rémy", 45078, 44471, 11.20),
    ("A31", 313.300, "Hauconcourt", 33545, 33353, 11.35),
    ("A31", 316.350, "Maizières-lès-Metz", 54040, 55291, 11.25),
    ("A31", 319.090, "Hagondange", None, None, None),
    ("A31", 321.400, "Richemont 1", 50564, 51126, 11.05),
    ("A31", 324.040, "Richemont 2", 35590, 35339, 11.00),
    ("A31", 325.770, "Guénange", 42789, 43001, 9.55),
    ("A31", 329.350, "Yutz", 40175, 41977, 9.05),
    ("A31", 330.700, "Beauregard", 41881, 44605, 8.60),
    ("A31", 332.020, "Linkling", 40851, 41833, 9.00),
    ("A31", 333.300, "Terville", 35141, 35852, 9.70),
    ("A31", 335.960, "Veymerange", 37933, 36507, 10.30),
    ("A31", 340.560, "Kanfen", 36643, 34943, 10.05),
    ("A31", 345.550, "Kanfen 1", 33034, 30296, 10.60),
    ("A31", 348.120, "Zoufftgen", 33872, 30841, 10.30),
]

# Live qtvDir ids confirmed by the official reference (refDir.csv gives road + PR).
KNOWN_IDS = {("A31", 290.770): "MZO57.5"}

# PR milestones from OSM: road -> {pr: (lon, lat)}
ANCHORS = {
    "A31": {
        283: (6.10920, 48.95778), 284: (6.10568, 48.96680), 285: (6.10421, 48.97567),
        286: (6.10482, 48.98465), 287: (6.10478, 48.99358), 288: (6.10700, 49.00233),
        289: (6.11271, 49.01048), 290: (6.11580, 49.01923), 291: (6.11473, 49.02814),
        292: (6.11280, 49.03708), 293: (6.11185, 49.04600), 302: (6.15972, 49.11210),
        331: (6.16362, 49.34819), 332: (6.14991, 49.34991), 345: (6.11697, 49.43680),
        346: (6.11915, 49.44569), 348: (6.12165, 49.46362),
    },
    "A30": {7: (6.09188, 49.31538), 23: (5.95170, 49.39519), 24: (5.94036, 49.40026)},
}

# Route endpoints (lon, lat) used to get each road's geometry in the sens 1 (+) direction.
ROUTES = {
    "A31": [(6.10920, 48.95778), (6.12165, 49.46362)],
    # From the A31 just south of the A30 junction, west along the A30 past Boulange.
    "A30": [(6.1600, 49.2900), (5.92900, 49.40600)],
}


def dist_m(a, b):
    k = math.pi / 180
    x = (b[0] - a[0]) * k * math.cos((a[1] + b[1]) * k / 2)
    return math.hypot(x, (b[1] - a[1]) * k) * 6371000


def cumulative(points):
    out, total = [0.0], 0.0
    for p, q in zip(points, points[1:]):
        total += dist_m(p, q)
        out.append(total)
    return out


def project(points, cum, pt):
    """Distance along the polyline of the closest vertex-segment point, and the offset in metres."""
    best = (math.inf, 0.0)
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = dist_m(a, b) or 1e-9
        # Local planar projection (fine at segment scale).
        ax, ay = 0.0, 0.0
        kx = math.cos(math.radians(a[1])) * 111320
        bx, by = (b[0] - a[0]) * kx, (b[1] - a[1]) * 111320
        px, py = (pt[0] - a[0]) * kx, (pt[1] - a[1]) * 111320
        t = max(0.0, min(1.0, (px * bx + py * by) / (seg * seg)))
        d = math.hypot(px - t * bx, py - t * by)
        if d < best[0]:
            best = (d, cum[i] + t * seg)
    return best[1], best[0]


def point_at(points, cum, s):
    s = max(0.0, min(cum[-1], s))
    for i in range(len(cum) - 1):
        if cum[i + 1] >= s:
            t = (s - cum[i]) / ((cum[i + 1] - cum[i]) or 1e-9)
            a, b = points[i], points[i + 1]
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return points[-1]


def pr_to_s(anchors_s, pr):
    """Piecewise-linear PR -> distance; linear extrapolation beyond the end anchors."""
    keys = sorted(anchors_s)
    if pr <= keys[0]:
        a, b = keys[0], keys[1]
    elif pr >= keys[-1]:
        a, b = keys[-2], keys[-1]
    else:
        a = max(k for k in keys if k <= pr)
        b = min(k for k in keys if k > pr)
    return anchors_s[a] + (pr - a) * (anchors_s[b] - anchors_s[a]) / (b - a)


async def main():
    features = []
    for road, (start, end) in ROUTES.items():
        r = await tomtom._route([list(start), list(end)])
        pts = [tuple(p) for p in r["points"]]
        cum = cumulative(pts)
        anchors_s = {}
        for pr, xy in ANCHORS[road].items():
            s, off = project(pts, cum, xy)
            print(f"{road} PR{pr}: {off:.0f} m off route")
            if off < 150:
                anchors_s[pr] = s
        for rd, pr, name, t2, t1, hgv in STATIONS:
            if rd != road:
                continue
            lon, lat = point_at(pts, cum, pr_to_s(anchors_s, pr))
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                             "properties": {"road": road, "pr": pr, "name": name, "dept": "57",
                                            "tmja_sens1": t1, "tmja_sens2": t2,
                                            "tmja": (t1 + t2) if t1 and t2 else None, "hgv_pct": hgv,
                                            "dir_id": KNOWN_IDS.get((road, pr))}})
    out = {"_doc": "Generated by backend/tools/build_count_stations.py - DIR Est Myrabel count stations (TMJA 2024). "
                   "sens1 = increasing PR (towards Luxembourg on A31, towards Longwy on A30).",
           "type": "FeatureCollection", "features": features}
    (STATIC_DIR / "count_stations.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(features)} stations")


if __name__ == "__main__":
    asyncio.run(main())
