import { useEffect, useMemo, useState } from "react";
import { api, CitaSite, CorridorConfig, CorridorResult, Direction, DirStation, MatchStatus, Status } from "./api";
import Drawer from "./Drawer";
import { allCoords, anchor, LngLat, nearLine } from "./geo";
import Hero, { Alert } from "./Hero";
import { usePoll, useStored } from "./hooks";
import MapView, { LayerKey } from "./MapView";

type FC = GeoJSON.FeatureCollection;

const DEFAULT_LAYERS: Record<LayerKey, boolean> = {
  flow: false, incidents: false, events: false, sensors: false, stations: false, chokes: false,
  signs: false, cameras: false, buildings: true, terrain: true,
};

const SEVERITY: Record<number, [string, string]> = {
  1: ["Accident", "#d03b3b"], 6: ["Slow traffic", "#ec835a"], 7: ["Lane closed", "#fab219"],
  8: ["Road closed", "#d03b3b"], 9: ["Roadworks", "#fab219"], 14: ["Broken-down vehicle", "#ec835a"],
};
const ALERT_RADIUS_M = 250;

function useIsMobile() {
  const [m, setM] = useState(() => window.innerWidth < 760);
  useEffect(() => {
    const f = () => setM(window.innerWidth < 760);
    window.addEventListener("resize", f);
    return () => window.removeEventListener("resize", f);
  }, []);
  return m;
}

export default function App() {
  const [direction, setDirection] = useState<Direction>(() => (new Date().getHours() < 12 ? "to_work" : "to_home"));
  const [manual, setManual] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [visible, setVisible] = useStored("layers.v2", DEFAULT_LAYERS);
  const [flowKey, setFlowKey] = useState(0);
  const mobile = useIsMobile();

  const status = usePoll(() => api<Status>("/api/status"), 60_000);
  const hasKey = status.data ? status.data.tomtom_key : null;
  const cfg = usePoll(() => api<CorridorConfig>("/api/corridors"), 0);
  const routes = usePoll(
    () => (hasKey ? api<{ results: CorridorResult[] }>(`/api/corridors/now?direction=${direction}`) : Promise.resolve(null)),
    180_000, [hasKey, direction]);
  const incidents = usePoll(() => (hasKey ? api<FC>("/api/tomtom/incidents") : Promise.resolve(null)), 120_000, [hasKey]);
  const events = usePoll(() => api<FC>("/api/cita/events"), 120_000);

  // Detail-only data: fetched when its layer or the drawer needs it.
  const sites = usePoll(() => (visible.sensors ? api<{ sites: CitaSite[] }>("/api/cita/traffic") : Promise.resolve(null)), 60_000, [visible.sensors]);
  const signs = usePoll(() => (visible.signs ? api<FC>("/api/cita/travel-times") : Promise.resolve(null)), 60_000, [visible.signs]);
  const cams = usePoll(() => (visible.cameras ? api<FC>("/api/cita/cameras") : Promise.resolve(null)), 0, [visible.cameras]);
  const chokes = usePoll(() => (visible.chokes ? api<FC>("/api/static/choke_points") : Promise.resolve(null)), 0, [visible.chokes]);
  const needDir = visible.stations || drawer;
  const counts = usePoll(() => (needDir ? api<FC>("/api/static/count_stations") : Promise.resolve(null)), 0, [needDir]);
  const dir = usePoll(() => (needDir ? api<{ stations: DirStation[] }>("/api/dir/stations") : Promise.resolve(null)), 180_000, [needDir]);
  const match = usePoll(() => (drawer ? api<MatchStatus>("/api/dir/match") : Promise.resolve(null)), 0, [drawer]);

  useEffect(() => {
    if (!visible.flow) return;
    const t = setInterval(() => setFlowKey(Date.now()), 120_000);
    return () => clearInterval(t);
  }, [visible.flow]);

  const results = routes.data?.results ?? [];
  const usual = new Set((cfg.data?.corridors ?? []).filter((c) => c.group === "usual").map((c) => c.id));
  const bestUsual = results.filter((r) => usual.has(r.id) && r.travel_s).sort((a, b) => a.travel_s! - b.travel_s!)[0];
  const selected = manual ?? bestUsual?.id ?? cfg.data?.corridors[0]?.id ?? "";

  // Incidents and works within reach of your routes (any of them), nearest route first.
  const { alertFC, alertList } = useMemo(() => {
    const lines = results.filter((r) => r.points?.length).map((r) => ({ id: r.id, pts: r.points as LngLat[] }));
    const feats: GeoJSON.Feature[] = [];
    const items: (Alert & { onSel: boolean })[] = [];
    const consider = (f: GeoJSON.Feature, title: string, color: string, where: string, source: string) => {
      const coords = allCoords(f.geometry);
      const step = Math.max(1, Math.floor(coords.length / 6));
      let onSel = false, near = false;
      for (const l of lines) {
        const hit = coords.some((c, i) => i % step === 0 && nearLine(c, l.pts) < ALERT_RADIUS_M);
        if (hit) { near = true; if (l.id === selected) onSel = true; }
      }
      if (!near) return;
      const a = anchor(f.geometry);
      if (!a) return;
      const id = `${source}:${f.properties?.id}`;
      feats.push({ type: "Feature", geometry: { type: "Point", coordinates: a },
        properties: { ...f.properties, title, color, source, description: f.properties?.description } });
      items.push({ id, title, where, color, onSel });
    };
    for (const f of incidents.data?.features ?? []) {
      const p = f.properties ?? {};
      const [title, color] = SEVERITY[p.iconCategory] ?? [p.category ?? "Incident", "#8b97aa"];
      const where = [p.roads?.[0], p.from && p.to ? `${p.from} → ${p.to}` : p.from].filter(Boolean).join(" · ");
      consider(f, title, color, where, "TomTom");
    }
    for (const f of events.data?.features ?? []) {
      const p = f.properties ?? {};
      consider(f, p.kind === "ConstructionWorks" || p.kind === "MaintenanceWorks" ? "Roadworks" : "Obstruction", "#fab219",
        [p.road, p.destination].filter(Boolean).join(" · "), "CITA");
    }
    items.sort((a, b) => Number(b.onSel) - Number(a.onSel));
    return { alertFC: { type: "FeatureCollection", features: feats } as FC, alertList: items.filter((i) => i.onSel) };
  }, [results, incidents.data, events.data, selected]);

  const padding = mobile
    ? { top: 70, bottom: Math.round(window.innerHeight * 0.42), left: 30, right: 30 }
    : { top: 80, bottom: 80, left: 460, right: 80 };

  return (
    <div className="app">
      <MapView cfg={cfg.data} routes={results} selected={selected} onSelect={setManual} direction={direction}
               alerts={alertFC} visible={visible} padding={padding} flowRefreshKey={flowKey}
               extra={{ sites: sites.data?.sites ?? [], events: events.data, incidents: incidents.data, cameras: cams.data,
                        signs: signs.data, chokes: chokes.data, countStations: counts.data, dir: dir.data?.stations ?? [] }} />

      <div className="brand"><span className="logo" />commute</div>

      <Hero cfg={cfg.data} direction={direction}
            onToggleDirection={() => { setDirection(direction === "to_work" ? "to_home" : "to_work"); setManual(null); }}
            routes={results} selected={selected} onSelect={setManual} alerts={alertList}
            updated={routes.at} error={routes.error ?? status.error} hasKey={hasKey} onOpenDetails={() => setDrawer(true)} />

      <Drawer open={drawer} onClose={() => setDrawer(false)} visible={visible} setVisible={setVisible}
              status={status} dir={dir} match={match} cfg={cfg.data}
              feeds={[
                { name: "Routes (TomTom)", poll: routes as any, count: results.length },
                { name: "Incidents (TomTom)", poll: incidents as any, count: incidents.data?.features.length },
                { name: "LU works (CITA)", poll: events as any, count: events.data?.features.length },
                { name: "LU sensors (CITA)", poll: sites as any, count: sites.data?.sites.length },
                { name: "FR stations (DIR Est)", poll: dir as any, count: dir.data?.stations.length },
              ]} />
    </div>
  );
}
