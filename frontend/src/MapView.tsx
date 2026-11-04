import { useEffect, useRef, useState } from "react";
import maplibregl, { GeoJSONSource, Map as MlMap, MapGeoJSONFeature, RasterTileSource } from "maplibre-gl";
import { apiBase, CitaSite, CorridorConfig, CorridorResult, Direction, DirStation, TrafficSection } from "./api";
import { bounds, cumulative, LngLat } from "./geo";

export type LayerKey =
  | "flow" | "incidents" | "events" | "sensors" | "stations" | "chokes" | "signs" | "cameras"
  | "buildings" | "terrain";

type FC = GeoJSON.FeatureCollection;

export interface ExtraData {
  sites: CitaSite[];
  events: FC | null;
  incidents: FC | null;
  cameras: FC | null;
  signs: FC | null;
  chokes: FC | null;
  countStations: FC | null;
  dir: DirStation[];
}

interface Props {
  cfg: CorridorConfig | null;
  routes: CorridorResult[];
  selected: string;
  onSelect: (id: string) => void;
  direction: Direction;
  alerts: FC;
  extra: ExtraData;
  visible: Record<LayerKey, boolean>;
  padding: { top: number; bottom: number; left: number; right: number };
  flowRefreshKey: number;
}

const BASE_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const BUILDINGS_TILEJSON = "https://tiles.openfreemap.org/planet";
const TERRAIN_TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
const FONT = ["Montserrat SemiBold", "Open Sans Bold"];
const EMPTY: FC = { type: "FeatureCollection", features: [] };

const C = {
  route: "#45d8ff", routeGlow: "#1aa6ff", alt: "#6f7d92",
  good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b", nodata: "#4b5260",
};

const SPEED_COLOR: maplibregl.ExpressionSpecification = [
  "case", ["<", ["get", "speed"], 0], C.nodata,
  ["step", ["get", "speed"], C.critical, 30, C.serious, 60, C.warning, 90, C.good],
];

const OPTIONAL: Record<LayerKey, string[]> = {
  flow: ["tt-flow"],
  incidents: ["inc-all-line", "inc-all-pt"],
  events: ["cita-events-line", "cita-events-pt"],
  sensors: ["cita-sensors"],
  stations: ["dir-pt", "dir-label"],
  chokes: ["chokes", "chokes-label"],
  signs: ["signs", "signs-label"],
  cameras: ["cams"],
  buildings: ["bldg-3d"],
  terrain: ["hillshade"],
};

export function sectionColor(s: TrafficSection): string {
  if (s.category === "ROAD_CLOSURE") return C.critical;
  if (s.category === "ROAD_WORK") return C.warning;
  if ((s.magnitude ?? 0) >= 3) return C.critical;
  if ((s.magnitude ?? 0) === 2) return C.serious;
  return C.warning;
}

/** line-progress step expression: cyan everywhere except slowdown sections. */
function trafficGradient(points: LngLat[], sections: TrafficSection[]): maplibregl.ExpressionSpecification {
  const cum = cumulative(points);
  const total = cum[cum.length - 1] || 1;
  const stops: (string | number)[] = [];
  let last = 0;
  const sorted = [...sections].filter((s) => s.end > s.start).sort((a, b) => a.start - b.start);
  for (const s of sorted) {
    let a = cum[Math.min(s.start, cum.length - 1)] / total;
    let b = cum[Math.min(s.end, cum.length - 1)] / total;
    a = Math.max(a, last + 1e-6);
    b = Math.max(b, a + 1e-4);
    if (a >= 1) break;
    stops.push(a, sectionColor(s), Math.min(b, 1 - 1e-6), C.route);
    last = b;
  }
  if (!stops.length) return ["interpolate", ["linear"], ["line-progress"], 0, C.route, 1, C.route];
  return ["step", ["line-progress"], C.route, ...stops] as maplibregl.ExpressionSpecification;
}

function hexagon(lon: number, lat: number, r: number): number[][] {
  const dLat = r / 111320, dLon = r / (111320 * Math.cos((lat * Math.PI) / 180));
  return Array.from({ length: 7 }, (_, i) => {
    const a = (Math.PI / 3) * (i % 6) + Math.PI / 6;
    return [lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)];
  });
}

const esc = (v: unknown) =>
  String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

const list = (v: unknown): any[] => {
  if (Array.isArray(v)) return v;
  try { return JSON.parse(String(v ?? "[]")); } catch { return []; }
};

function popupHtml(layer: string, f: MapGeoJSONFeature): string {
  const p = f.properties as Record<string, any>;
  const row = (k: string, v: unknown) => (v == null || v === "" ? "" : `<div><span class="k">${k}</span> ${esc(v)}</div>`);
  const t = (v: unknown) => (v ? new Date(String(v)).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" }) : null);
  const num = (n: unknown) => (n == null ? "–" : Number(n).toLocaleString("en-GB"));
  if (layer.startsWith("alert") || layer.startsWith("inc-all")) {
    return `<div class="pop"><b>${esc(p.title)}</b>${row("", p.description)}${row("From", p.from)}${row("To", p.to)}
      ${row("Delay", p.delay ? `${Math.round(Number(p.delay) / 60)} min` : null)}${row("Until", t(p.end))}
      <div class="k src">${esc(p.source)}</div></div>`;
  }
  if (layer.startsWith("cita-events")) {
    return `<div class="pop"><b>${esc(p.kind)} · ${esc(p.road)}</b>${row("Towards", p.destination)}
      ${list(p.comments).map((c) => `<div>${esc(c)}</div>`).join("")}${row("Lanes closed", p.lanesRestricted)}
      ${row("Since", t(p.start))}<div class="k src">CITA</div></div>`;
  }
  if (layer === "cita-sensors") {
    return `<div class="pop"><b>${esc(p.road)} · ${esc(p.id)}</b>${row("Speed", Number(p.speed) >= 0 ? `${p.speed} km/h` : "–")}
      ${row("Flow", p.flow != null ? `${p.flow} veh/h` : null)}${row("Occupancy", p.occupancy != null ? `${p.occupancy} %` : null)}
      <div class="k src">CITA loop detector</div></div>`;
  }
  if (layer.startsWith("dir")) {
    const d = p.road === "A31" ? ["→ Lux", "→ Metz"] : ["→ Longwy", "→ A31"];
    const live = (s: string, l: string) => (p[`flow${s}`] != null ? `<div>${l} <b>${num(p[`flow${s}`])}</b> veh/h · ${num(p[`speed${s}`])} km/h</div>` : "");
    return `<div class="pop"><b>${esc(p.road)} ${esc(p.name)}</b><div class="k">PR ${esc(p.pr)}</div>
      <div>2024 average: <b>${num(p.tmja)}</b> veh/day · ${esc(p.hgv_pct ?? "–")}% HGV</div>
      <div class="k">${d[0]} ${num(p.tmja_sens1)} · ${d[1]} ${num(p.tmja_sens2)}</div>
      ${p.live ? live("1", d[0]) + live("2", d[1]) : `<div class="k">No live feed linked yet</div>`}
      <div class="k src">DIR Est count station</div></div>`;
  }
  if (layer.startsWith("chokes")) {
    return `<div class="pop"><b>${esc(p.name)}</b><div class="k">${esc(p.kind)}${p.approx ? " · approx. position" : ""}</div><div>${esc(p.notes)}</div></div>`;
  }
  if (layer.startsWith("signs")) {
    return `<div class="pop"><b>${esc(p.name)}</b>${list(p.times).map((x) => `<div>${esc(x.destination)} <b>${esc(x.minutes)} min</b></div>`).join("")}
      <div class="k src">CITA sign</div></div>`;
  }
  if (layer === "cams") {
    return `<div class="pop"><b>${esc(p.name)}</b>${p.url ? `<iframe src="${esc(p.url)}" width="270" height="245" scrolling="no"></iframe>` : ""}</div>`;
  }
  return "";
}

function tuneBasemap(map: MlMap) {
  for (const l of map.getStyle().layers ?? []) {
    const id = l.id;
    if (/poi|housenumber|roadname_minor|roadname_sec|place_hamlet|place_suburbs|watername_ocean|watername_sea/.test(id)) {
      map.setLayoutProperty(id, "visibility", "none");
      continue;
    }
    if (id === "background") map.setPaintProperty(id, "background-color", "#05070b");
    if (id === "water") map.setPaintProperty(id, "fill-color", "#0a1322");
    if (l.type === "line" && /^(road|bridge|tunnel)_/.test(id) && id.includes("fill")) {
      const major = /mot|trunk|pri/.test(id);
      map.setPaintProperty(id, "line-color", major ? "#2a3446" : "#171d28");
    }
    if (l.type === "line" && /^(road|bridge|tunnel)_/.test(id) && id.includes("case")) {
      map.setPaintProperty(id, "line-color", "#0b0f16");
    }
    if (l.type === "line" && /^boundary_country/.test(id)) {
      map.setPaintProperty(id, "line-color", "#3a4a66");
    }
    if (l.type === "symbol") {
      map.setPaintProperty(id, "text-color", /city|town|country|state/.test(id) ? "#8a94a6" : "#5d6779");
      map.setPaintProperty(id, "text-halo-color", "#05070b");
      if (id === "place_villages") map.setLayerZoomRange(id, 11.5, 24);
    }
  }
}

function makeMarker(kind: "home" | "work", label: string, sub: string) {
  const el = document.createElement("div");
  el.className = `pin pin-${kind}`;
  const icon = kind === "home"
    ? `<svg viewBox="0 0 24 24"><path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z"/></svg>`
    : `<svg viewBox="0 0 24 24"><path d="M9 6V4h6v2h5v14H4V6zm2 0h2V5h-2z"/></svg>`;
  el.innerHTML = `<div class="pin-dot">${icon}</div><div class="pin-label">${esc(label)}<span>${esc(sub)}</span></div>`;
  return el;
}

export default function MapView(props: Props) {
  const { cfg, routes, selected, onSelect, direction, alerts, extra, visible, padding, flowRefreshKey } = props;
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const [ready, setReady] = useState(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const fittedFor = useRef("");

  useEffect(() => {
    const map = new maplibregl.Map({
      container: el.current!,
      style: BASE_STYLE,
      center: [6.05, 49.43], zoom: 10.3, pitch: 50, bearing: -12, maxPitch: 75,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    if (import.meta.env.DEV) (window as any).__map = map;

    map.once("style.load", () => {
      map.resize();
      tuneBasemap(map);
      try {
        (map as any).setSky?.({ "sky-color": "#05070b", "horizon-color": "#0b1a2e", "fog-color": "#05070b",
          "sky-horizon-blend": 0.6, "horizon-fog-blend": 0.6, "fog-ground-blend": 0.2 });
      } catch { /* older renderer */ }

      const api = apiBase();
      map.addSource("dem", { type: "raster-dem", tiles: [TERRAIN_TILES], encoding: "terrarium", tileSize: 256, maxzoom: 14 });
      map.addSource("dem-hs", { type: "raster-dem", tiles: [TERRAIN_TILES], encoding: "terrarium", tileSize: 256, maxzoom: 14 });
      map.addSource("bldg", { type: "vector", url: BUILDINGS_TILEJSON });
      map.addSource("tt-flow", { type: "raster", tiles: [`${api}/api/tomtom/flow/{z}/{x}/{y}.png`], tileSize: 256 });
      map.addSource("route-sel", { type: "geojson", data: EMPTY, lineMetrics: true });
      for (const id of ["route-alt", "alerts", "cita-sensors", "cita-events", "inc-all", "cams", "signs", "chokes", "dir"]) {
        map.addSource(id, { type: "geojson", data: EMPTY });
      }
      const firstLabel = map.getStyle().layers?.find((l) => l.type === "symbol")?.id;

      map.addLayer({ id: "hillshade", type: "hillshade", source: "dem-hs",
        paint: { "hillshade-exaggeration": 0.25, "hillshade-shadow-color": "#000", "hillshade-highlight-color": "#1a2333",
                 "hillshade-accent-color": "#05070b" } }, firstLabel);
      map.addLayer({ id: "tt-flow", type: "raster", source: "tt-flow", paint: { "raster-opacity": 0.75 } }, firstLabel);
      map.addLayer({ id: "bldg-3d", type: "fill-extrusion", source: "bldg", "source-layer": "building", minzoom: 13,
        paint: { "fill-extrusion-color": "#151c28", "fill-extrusion-opacity": 0.9,
                 "fill-extrusion-height": ["coalesce", ["get", "render_height"], 8],
                 "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0] } });

      // Alternative routes: quiet, clickable.
      map.addLayer({ id: "route-alt-hit", type: "line", source: "route-alt", paint: { "line-color": "#000", "line-opacity": 0, "line-width": 18 } });
      map.addLayer({ id: "route-alt", type: "line", source: "route-alt", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#9aa8bd", "line-width": 2.5, "line-opacity": 0.7, "line-dasharray": [2, 1.6] } });
      map.addLayer({ id: "route-alt-label", type: "symbol", source: "route-alt",
        layout: { "symbol-placement": "line", "text-field": ["get", "name"], "text-size": 11, "text-font": FONT, "symbol-spacing": 400 },
        paint: { "text-color": "#8b97aa", "text-halo-color": "#05070b", "text-halo-width": 1.5 } });

      // Selected route: glow, traffic-coloured core, flowing dashes.
      map.addLayer({ id: "route-glow", type: "line", source: "route-sel", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": C.routeGlow, "line-width": 18, "line-blur": 14, "line-opacity": 0.45 } });
      map.addLayer({ id: "route-core", type: "line", source: "route-sel", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-gradient": ["interpolate", ["linear"], ["line-progress"], 0, C.route, 1, C.route], "line-width": 5 } });
      map.addLayer({ id: "route-flow", type: "line", source: "route-sel", layout: { "line-cap": "butt", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": 1.6, "line-opacity": 0.55, "line-dasharray": [0, 4, 3] } });

      // Alerts on/near your routes.
      map.addLayer({ id: "alerts-halo", type: "circle", source: "alerts",
        paint: { "circle-color": ["get", "color"], "circle-radius": 16, "circle-blur": 1, "circle-opacity": 0.6 } });
      map.addLayer({ id: "alerts", type: "circle", source: "alerts",
        paint: { "circle-color": ["get", "color"], "circle-radius": 6, "circle-stroke-color": "#05070b", "circle-stroke-width": 2 } });

      // Optional layers (off by default, toggled in Details).
      const incColor: maplibregl.ExpressionSpecification = ["match", ["get", "iconCategory"],
        8, C.critical, 1, C.critical, 9, C.warning, 7, C.warning, 6, C.serious, C.alt];
      map.addLayer({ id: "inc-all-line", type: "line", source: "inc-all", filter: ["in", ["geometry-type"], ["literal", ["LineString", "MultiLineString"]]],
        paint: { "line-color": incColor, "line-width": 3, "line-opacity": 0.8 } });
      map.addLayer({ id: "inc-all-pt", type: "circle", source: "inc-all", filter: ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]],
        paint: { "circle-color": incColor, "circle-radius": 4 } });
      map.addLayer({ id: "cita-events-line", type: "line", source: "cita-events", filter: ["in", ["geometry-type"], ["literal", ["LineString", "MultiLineString"]]],
        paint: { "line-color": C.warning, "line-width": 3, "line-opacity": 0.8 } });
      map.addLayer({ id: "cita-events-pt", type: "circle", source: "cita-events", filter: ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]],
        paint: { "circle-color": C.warning, "circle-radius": 4 } });
      map.addLayer({ id: "cita-sensors", type: "fill-extrusion", source: "cita-sensors",
        paint: { "fill-extrusion-color": SPEED_COLOR, "fill-extrusion-height": ["get", "height"], "fill-extrusion-opacity": 0.85 } });
      map.addLayer({ id: "dir-pt", type: "circle", source: "dir",
        paint: { "circle-color": ["case", ["get", "live"], SPEED_COLOR, "rgba(0,0,0,0)"],
                 "circle-radius": ["interpolate", ["linear"], ["coalesce", ["get", "tmja"], 30000], 20000, 4, 110000, 9],
                 "circle-stroke-color": "#c9d3e3", "circle-stroke-width": 1.2, "circle-stroke-opacity": 0.8 } });
      map.addLayer({ id: "dir-label", type: "symbol", source: "dir", minzoom: 11,
        layout: { "text-field": ["get", "name"], "text-size": 10, "text-offset": [1, 0], "text-anchor": "left", "text-font": FONT },
        paint: { "text-color": "#8b97aa", "text-halo-color": "#05070b", "text-halo-width": 1.5 } });
      map.addLayer({ id: "chokes", type: "circle", source: "chokes",
        paint: { "circle-color": "rgba(0,0,0,0)", "circle-radius": 11, "circle-stroke-color": "#c9d3e3", "circle-stroke-width": 1.2 } });
      map.addLayer({ id: "chokes-label", type: "symbol", source: "chokes",
        layout: { "text-field": ["get", "name"], "text-size": 10, "text-offset": [0, -1.6], "text-anchor": "bottom", "text-font": FONT, "text-max-width": 12 },
        paint: { "text-color": "#c9d3e3", "text-halo-color": "#05070b", "text-halo-width": 1.5 } });
      map.addLayer({ id: "signs", type: "circle", source: "signs", paint: { "circle-color": "#c9d3e3", "circle-radius": 3.5 } });
      map.addLayer({ id: "signs-label", type: "symbol", source: "signs",
        layout: { "text-field": ["get", "label"], "text-size": 10, "text-offset": [0, 1], "text-anchor": "top", "text-font": FONT },
        paint: { "text-color": "#c9d3e3", "text-halo-color": "#05070b", "text-halo-width": 1.5 } });
      map.addLayer({ id: "cams", type: "circle", source: "cams", paint: { "circle-color": "#8b97aa", "circle-radius": 3 } });

      const clickable = ["alerts", "inc-all-line", "inc-all-pt", "cita-events-line", "cita-events-pt", "cita-sensors",
        "dir-pt", "dir-label", "chokes", "chokes-label", "signs", "signs-label", "cams"];
      map.on("click", (e) => {
        const hit = map.queryRenderedFeatures(e.point, { layers: clickable })[0];
        if (hit) {
          new maplibregl.Popup({ maxWidth: "300px", className: "glass-pop" }).setLngLat(e.lngLat).setHTML(popupHtml(hit.layer.id, hit)).addTo(map);
          return;
        }
        const alt = map.queryRenderedFeatures(e.point, { layers: ["route-alt-hit"] })[0];
        if (alt) onSelectRef.current(String(alt.properties.id));
      });
      for (const id of [...clickable, "route-alt-hit"]) {
        map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
      }

      // Flowing dashes along the selected route.
      const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      if (!reduce) {
        const seq = [[0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5], [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0],
          [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5], [0, 2, 3, 2], [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5]];
        let step = -1;
        const tick = (ts: number) => {
          const s = Math.floor(ts / 70) % seq.length;
          if (s !== step && map.getLayer("route-flow")) {
            map.setPaintProperty("route-flow", "line-dasharray", seq[s]);
            step = s;
          }
          raf = requestAnimationFrame(tick);
        };
        let raf = requestAnimationFrame(tick);
        map.once("remove", () => cancelAnimationFrame(raf));
      }
      setReady(true);
    });
    return () => map.remove();
  }, []);

  const map = ready ? mapRef.current : null;
  const set = (id: string, fc: FC | null): void => {
    if (!map?.style) return; // map removed (unmount / hot reload)
    (map.getSource(id) as GeoJSONSource | undefined)?.setData(fc ?? EMPTY);
  };

  // Home / Work markers.
  useEffect(() => {
    if (!map?.style || !cfg) return;
    const ms = (["home", "work"] as const).map((k) =>
      new maplibregl.Marker({ element: makeMarker(k, cfg.endpoints[k].name, cfg.endpoints[k].address.split(",").pop()!.trim()), anchor: "bottom" })
        .setLngLat(cfg.endpoints[k].coord).addTo(map));
    return () => ms.forEach((m) => m.remove());
  }, [map, cfg]);

  // Routes.
  useEffect(() => {
    if (!map?.style || !cfg) return;
    const names = Object.fromEntries(cfg.corridors.map((c) => [c.id, c.name]));
    const sel = routes.find((r) => r.id === selected && r.points?.length);
    set("route-sel", sel ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {},
      geometry: { type: "LineString", coordinates: sel.points! } }] } : null);
    if (sel) map.setPaintProperty("route-core", "line-gradient", trafficGradient(sel.points as LngLat[], sel.traffic ?? []));
    set("route-alt", { type: "FeatureCollection", features: routes.filter((r) => r.id !== selected && r.points?.length).map((r) => ({
      type: "Feature", properties: { id: r.id, name: names[r.id] ?? r.id }, geometry: { type: "LineString", coordinates: r.points! } })) });

    const key = `${direction}:${routes.length}`;
    if (routes.length && fittedFor.current !== key) {
      fittedFor.current = key;
      const pts = routes.flatMap((r) => (r.points ?? []) as LngLat[]);
      map.fitBounds(bounds(pts), { padding, pitch: 50, bearing: -12, duration: 1200, maxZoom: 13 });
    }
  }, [map, cfg, routes, selected, direction]);

  useEffect(() => set("alerts", alerts), [map, alerts]);
  useEffect(() => set("inc-all", extra.incidents), [map, extra.incidents]);
  useEffect(() => set("cita-events", extra.events), [map, extra.events]);
  useEffect(() => set("cams", extra.cameras), [map, extra.cameras]);
  useEffect(() => set("chokes", extra.chokes), [map, extra.chokes]);
  useEffect(() => {
    set("cita-sensors", { type: "FeatureCollection", features: extra.sites.map((s) => {
      const off = (s.direction === "inboundTowardsTown" ? 1 : -1) * 80;
      const lon = s.lon + off / (111320 * Math.cos((s.lat * Math.PI) / 180)) * 0.7;
      const lat = s.lat + (off / 111320) * 0.7;
      return { type: "Feature", geometry: { type: "Polygon", coordinates: [hexagon(lon, lat, 70)] },
        properties: { ...s, speed: s.speed ?? -1, height: Math.max(30, (s.flow ?? 0) * 0.3) } };
    }) });
  }, [map, extra.sites]);
  useEffect(() => {
    if (!extra.signs) return;
    set("signs", { ...extra.signs, features: extra.signs.features.map((f) => ({ ...f, properties: { ...f.properties,
      label: (f.properties?.times ?? []).map((t: any) => `${t.destination} ${t.minutes}′`).join("\n") } })) });
  }, [map, extra.signs]);
  useEffect(() => {
    if (!extra.countStations) return;
    set("dir", { ...extra.countStations, features: extra.countStations.features.map((f) => {
      const p = f.properties as Record<string, any>;
      const live = extra.dir.filter((s) => s.road === p.road && s.pr === p.pr);
      const s1 = live.find((s) => s.sens === "1"), s2 = live.find((s) => s.sens === "2");
      const sp = live.map((s) => s.speed).filter((v): v is number => v != null);
      return { ...f, properties: { ...p, live: live.length > 0, flow1: s1?.flow, speed1: s1?.speed, flow2: s2?.flow,
        speed2: s2?.speed, speed: sp.length ? Math.min(...sp) : -1 } };
    }) });
  }, [map, extra.countStations, extra.dir]);

  useEffect(() => {
    if (!map?.style) return;
    for (const [key, ids] of Object.entries(OPTIONAL) as [LayerKey, string[]][]) {
      for (const id of ids) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible[key] ? "visible" : "none");
    }
    for (const id of ["building", "building-top"]) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible.buildings ? "none" : "visible");
    map.setTerrain(visible.terrain ? { source: "dem", exaggeration: 1.3 } : null);
  }, [map, visible]);

  useEffect(() => {
    if (!map?.style || !flowRefreshKey) return;
    (map.getSource("tt-flow") as RasterTileSource | undefined)?.setTiles([`${apiBase()}/api/tomtom/flow/{z}/{x}/{y}.png?t=${flowRefreshKey}`]);
  }, [map, flowRefreshKey]);

  return <div ref={el} className="map" />;
}
