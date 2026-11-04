import { useState } from "react";
import { clock, CorridorConfig, CorridorResult, Direction, mins } from "./api";
import LeaveTimeline from "./LeaveTimeline";

export interface Alert {
  id: string;
  title: string;
  where: string;
  color: string;
}

interface Props {
  cfg: CorridorConfig | null;
  direction: Direction;
  onToggleDirection: () => void;
  routes: CorridorResult[];
  selected: string;
  onSelect: (id: string) => void;
  alerts: Alert[];
  updated: Date | null;
  error: string | null;
  hasKey: boolean | null;
  onOpenDetails: () => void;
}

function deltaInfo(r?: CorridorResult) {
  if (!r?.travel_s || !r.historic_s) return null;
  const d = Math.round((r.travel_s - r.historic_s) / 60);
  if (d >= 3) return { text: `+${d} min vs usual`, cls: "bad" };
  if (d <= -3) return { text: `${-d} min faster than usual`, cls: "good" };
  return { text: "Usual traffic", cls: "ok" };
}

export default function Hero(p: Props) {
  const [expanded, setExpanded] = useState(false);
  const names = Object.fromEntries((p.cfg?.corridors ?? []).map((c) => [c.id, c]));
  const r = p.routes.find((x) => x.id === p.selected);
  const delta = deltaInfo(r);
  const from = p.direction === "to_work" ? "Home" : "Work";
  const to = p.direction === "to_work" ? "Work" : "Home";
  const valid = p.routes.filter((x) => x.travel_s);
  const maxT = Math.max(1, ...valid.map((x) => x.travel_s!));
  const ref = valid.find((x) => names[x.id]?.group === "reference");
  const gain = r?.travel_s && ref?.travel_s ? Math.round((r.travel_s - ref.travel_s) / 60) : 0;
  const shortcut = gain >= 5 ? gain : 0;
  const fastestUsual = valid.filter((x) => names[x.id]?.group === "usual").sort((a, b) => a.travel_s! - b.travel_s!)[0];

  return (
    <section className={`hero glass ${expanded ? "expanded" : ""}`}>
      <button className="handle" aria-label={expanded ? "Collapse" : "Expand"} onClick={() => setExpanded(!expanded)} />

      <header className="hero-top">
        <button className="dir-pill" onClick={p.onToggleDirection} title="Switch direction">
          {from} <span className="arrow">→</span> {to}
          <svg viewBox="0 0 24 24" className="swap"><path d="M7 7h11l-3-3M17 17H6l3 3" /></svg>
        </button>
        <button className="icon-btn" onClick={p.onOpenDetails} aria-label="Details">
          <svg viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></svg>
        </button>
      </header>

      {p.hasKey === false ? (
        <div className="empty">Add your TomTom key on the backend to get live times.</div>
      ) : p.error && !r ? (
        <div className="empty">{p.error}</div>
      ) : (
        <div className="hero-main" onClick={() => setExpanded(!expanded)}>
          <div className={`big ${r?.travel_s ? "" : "loading"}`}>
            {r?.travel_s ? mins(r.travel_s) : "––"}<span>min</span>
          </div>
          <div className="hero-meta">
            <div className="via">via <b>{names[p.selected]?.name ?? "…"}</b></div>
            {r?.travel_s && <div className="muted">Leave now · arrive {clock(new Date(Date.now() + r.travel_s * 1000))}</div>}
            {delta && <div className={`delta ${delta.cls}`}><i />{delta.text}</div>}
            {shortcut > 0 && <div className="hint">Motorway {shortcut} min faster right now</div>}
          </div>
        </div>
      )}

      <button className="peek" onClick={() => setExpanded(true)}>
        {p.alerts.length > 0
          ? <><i style={{ background: p.alerts[0].color }} />{p.alerts.length} alert{p.alerts.length > 1 ? "s" : ""} on this route</>
          : <>Routes & when to leave</>}
        <span>›</span>
      </button>

      <div className="hero-more">
        {p.alerts.length > 0 && (
          <ul className="alerts">
            {p.alerts.slice(0, 3).map((a) => (
              <li key={a.id}><i style={{ background: a.color }} /><b>{a.title}</b><span>{a.where}</span></li>
            ))}
          </ul>
        )}

        <div className="routes">
          {p.cfg?.corridors.map((c) => {
            const x = p.routes.find((y) => y.id === c.id);
            const pct = x?.travel_s ? (x.travel_s / maxT) * 100 : 0;
            const delayPct = x?.travel_s && x.delay_s ? (Math.min(x.delay_s, x.travel_s) / maxT) * 100 : 0;
            return (
              <button key={c.id} className={`route ${p.selected === c.id ? "sel" : ""} ${c.group}`} onClick={() => p.onSelect(c.id)}>
                <span className="r-name">{c.name}{c.group === "reference" && <em>ref</em>}
                  {x === fastestUsual && valid.length > 1 && <em className="fast">fastest</em>}</span>
                <span className="r-bar"><i style={{ width: `${pct}%` }} /><b style={{ left: `${pct - delayPct}%`, width: `${delayPct}%` }} /></span>
                <span className="r-min">{x?.travel_s ? mins(x.travel_s) : x?.error ? "!" : "…"}<small>min</small></span>
              </button>
            );
          })}
        </div>

        <LeaveTimeline corridor={p.selected} direction={p.direction} enabled={p.hasKey === true && !!p.selected} />

        <footer className="hero-foot">
          <span className="live-dot" /> {p.updated ? `Updated ${clock(p.updated)}` : "Connecting…"}
        </footer>
      </div>
    </section>
  );
}
