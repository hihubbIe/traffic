import { useState } from "react";
import { api, apiBase, clock, CorridorConfig, DirStation, MatchStatus, setApiBase, Status } from "./api";
import type { Poll } from "./hooks";
import type { LayerKey } from "./MapView";

type Tab = "layers" | "data" | "stations" | "settings";

const LAYERS: { key: LayerKey; label: string; hint: string; needsKey?: boolean }[] = [
  { key: "flow", label: "Traffic on all roads", hint: "TomTom live flow", needsKey: true },
  { key: "incidents", label: "All incidents & roadworks", hint: "TomTom, FR + LU", needsKey: true },
  { key: "events", label: "Luxembourg motorway works", hint: "CITA" },
  { key: "sensors", label: "Luxembourg motorway sensors", hint: "CITA, 3D columns" },
  { key: "stations", label: "French count stations", hint: "DIR Est A31/A30" },
  { key: "chokes", label: "Choke points", hint: "Bottleneck inventory" },
  { key: "signs", label: "Travel-time signs", hint: "CITA" },
  { key: "cameras", label: "Cameras", hint: "CITA" },
  { key: "buildings", label: "3D buildings", hint: "" },
  { key: "terrain", label: "Terrain", hint: "" },
];

interface Props {
  open: boolean;
  onClose: () => void;
  visible: Record<LayerKey, boolean>;
  setVisible: (v: Record<LayerKey, boolean>) => void;
  status: Poll<Status>;
  feeds: { name: string; poll: Poll<unknown>; count?: number }[];
  dir: Poll<{ stations: DirStation[] }>;
  match: Poll<MatchStatus>;
  cfg: CorridorConfig | null;
}

export default function Drawer(p: Props) {
  const [tab, setTab] = useState<Tab>("layers");
  const [url, setUrl] = useState(apiBase());
  const hasKey = !!p.status.data?.tomtom_key;
  const rec = p.status.data?.recordings;

  return (
    <>
      <div className={`scrim ${p.open ? "open" : ""}`} onClick={p.onClose} />
      <aside className={`drawer glass ${p.open ? "open" : ""}`} aria-hidden={!p.open}>
        <header className="drawer-head">
          <h2>Details</h2>
          <button className="icon-btn" onClick={p.onClose} aria-label="Close">
            <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </header>
        <nav className="tabs">
          {(["layers", "data", "stations", "settings"] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>
          ))}
        </nav>

        <div className="drawer-body">
          {tab === "layers" && (
            <div className="toggles">
              {LAYERS.map((l) => (
                <label key={l.key} className={`switch ${l.needsKey && !hasKey ? "disabled" : ""}`}>
                  <span><b>{l.label}</b>{l.hint && <small>{l.hint}</small>}</span>
                  <input type="checkbox" checked={p.visible[l.key]} disabled={l.needsKey && !hasKey}
                         onChange={(e) => p.setVisible({ ...p.visible, [l.key]: e.target.checked })} />
                  <i />
                </label>
              ))}
            </div>
          )}

          {tab === "data" && (
            <>
              <div className="kv"><span>Backend</span><b>{apiBase()}</b></div>
              <div className="kv"><span>TomTom key</span><b className={hasKey ? "good" : "bad"}>{hasKey ? "Loaded" : "Missing"}</b></div>
              <div className="kv"><span>Recording</span><b>{p.status.data?.recording ? "On" : "Off"}{rec?.size_mb != null ? ` · ${rec.size_mb} MB` : ""}</b></div>
              {rec && (
                <div className="kv"><span>Rows</span>
                  <b>LU {rec.cita_obs?.rows ?? 0} · FR {rec.dir_obs?.rows ?? 0} · routes {rec.corridor_obs?.rows ?? 0} · events {rec.events_seen?.rows ?? 0}</b></div>
              )}
              <h3>Feeds</h3>
              {p.feeds.map((f) => (
                <div key={f.name} className="kv">
                  <span><i className={`dot ${f.poll.error ? "bad" : f.poll.at ? "good" : ""}`} />{f.name}</span>
                  <b>{f.poll.error ? "error" : f.poll.at ? `${f.count ?? ""} · ${clock(f.poll.at)}` : "—"}</b>
                </div>
              ))}
              {p.feeds.filter((f) => f.poll.error).map((f) => <p key={f.name} className="small bad">{f.name}: {f.poll.error}</p>)}
            </>
          )}

          {tab === "stations" && (
            <>
              <p className="small muted">
                French A31/A30 count stations are placed from their PR. Live ids are linked by comparing a recorded weekday
                with each station's 2024 traffic.
              </p>
              {p.match.data && !p.match.data.ready && <p className="small muted">{p.match.data.reason}</p>}
              {p.match.data?.ready && (
                <>
                  <table className="data">
                    <tbody>{p.match.data.proposals.map((m) => (
                      <tr key={m.id}><td>{m.id}x</td><td>{m.road} {m.station}</td><td className={m.confident ? "good" : "muted"}>{m.confident ? "good" : "weak"}</td></tr>
                    ))}</tbody>
                  </table>
                  <button className="btn" disabled={!p.match.data.proposals.some((m) => m.confident)}
                          onClick={async () => { await api("/api/dir/match/apply", { method: "POST" }); p.dir.reload(); p.match.reload(); }}>
                    Link good matches
                  </button>
                </>
              )}
              <h3>Live ids</h3>
              <table className="data">
                <tbody>{(p.dir.data?.stations ?? []).map((s) => (
                  <tr key={s.id}><td>{s.id}</td><td>{s.label ?? <span className="muted">unlinked</span>}</td>
                    <td className="num">{s.flow ?? "–"}</td><td className="num">{s.speed ?? "–"}</td></tr>
                ))}</tbody>
              </table>
            </>
          )}

          {tab === "settings" && (
            <>
              <h3>Backend URL</h3>
              <p className="small muted">Where the API runs: this PC now, the Raspberry Pi later. Leave empty for the default
                (same host, port 8000).</p>
              <div className="row">
                <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://raspberrypi.local:8000" />
                <button className="btn" onClick={() => { setApiBase(url); window.location.reload(); }}>Save</button>
              </div>
              <h3>Places</h3>
              {p.cfg && (["home", "work"] as const).map((k) => (
                <div key={k} className="kv"><span>{p.cfg!.endpoints[k].name}</span><b>{p.cfg!.endpoints[k].address}</b></div>
              ))}
              <p className="small muted">Home/Work are set in <code>backend/data/static/places.json</code>, routes in <code>corridors.json</code>.</p>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
