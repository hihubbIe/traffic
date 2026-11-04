export type LngLat = [number, number];

export function distM(a: LngLat, b: LngLat): number {
  const k = Math.PI / 180;
  const x = (b[0] - a[0]) * k * Math.cos(((a[1] + b[1]) * k) / 2);
  return Math.hypot(x, (b[1] - a[1]) * k) * 6371000;
}

export function cumulative(points: LngLat[]): number[] {
  const out = [0];
  for (let i = 1; i < points.length; i++) out.push(out[i - 1] + distM(points[i - 1], points[i]));
  return out;
}

/** Smallest distance (m) from p to any sampled vertex of the line. */
export function nearLine(p: LngLat, line: LngLat[], step = 2): number {
  let best = Infinity;
  for (let i = 0; i < line.length; i += step) best = Math.min(best, distM(p, line[i]));
  return best;
}

/** Representative coordinate of any GeoJSON geometry (first vertex). */
export function anchor(g: GeoJSON.Geometry): LngLat | null {
  switch (g.type) {
    case "Point": return g.coordinates as LngLat;
    case "MultiPoint":
    case "LineString": return (g.coordinates[0] as LngLat) ?? null;
    case "MultiLineString": return (g.coordinates[0]?.[0] as LngLat) ?? null;
    default: return null;
  }
}

export function allCoords(g: GeoJSON.Geometry): LngLat[] {
  switch (g.type) {
    case "Point": return [g.coordinates as LngLat];
    case "MultiPoint":
    case "LineString": return g.coordinates as LngLat[];
    case "MultiLineString": return g.coordinates.flat() as LngLat[];
    default: return [];
  }
}

export function bounds(points: LngLat[]): [LngLat, LngLat] {
  let [w, s, e, n] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [x, y] of points) {
    w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y);
  }
  return [[w, s], [e, n]];
}
