import { useMemo, useState } from "react";
import { clock, Factor, Plan, PlanMode } from "./api";
import type { Alert } from "./Hero";

// Validated pair for the dark surface (dataviz palette, dark steps).
const ROUTE_COLORS: Record<string, string> = { a30: "#3987e5", aumetz: "#d95926" };
const W = 360, H = 156, M = { l: 30, r: 56, t: 10, b: 24 };
const LASTING = new Set(["Roadworks", "Road closed", "Lane closed"]);

interface Props {
  plan: Plan | null;
  error: string | null;
  mode: PlanMode;
  setMode: (m: PlanMode) => void;
  workdayLabel: string;
  alerts: Alert[];
}

function Chart({ plan }: { plan: Plan }) {
  const [hover, setHover] = useState<number | null>(null);
  const slots = plan.slots;
  const geo = useMemo(() => {
    if (slots.length < 2) return null;
    const t0 = new Date(slots[0].depart).getTime();
    const t1 = new Date(slots[slots.length - 1].depart).getTime();
    const all = slots.flatMap((s) => [...Object.values(s.by_route), s.high_s ?? 0]);
    let yMax = Math.ceil((Math.max(...all) / 60 + 4) / 10) * 10;
    const yMin = Math.max(0, Math.floor((Math.min(...slots.map((s) => s.low_s ?? s.best_s)) / 60 - 6) / 10) * 10);
    if (yMax - yMin < 20) yMax = yMin + 20;
    const x = (iso: string) => M.l + ((new Date(iso).getTime() - t0) / (t1 - t0 || 1)) * (W - M.l - M.r);
    const y = (sec: number) => H - M.b - ((sec / 60 - yMin) / (yMax - yMin)) * (H - M.t - M.b);
    const lines = Object.entries(plan.routes).filter(([, r]) => r.points.length).map(([id, r]) => {
      const last = r.points[r.points.length - 1];
      return {
        id, name: r.name, color: ROUTE_COLORS[id] ?? "#9aa8bd", labelY: y(last.travel_s) + 3.5,
        d: r.points.map((p, i) => `${i ? "L" : "M"}${x(p.depart).toFixed(1)},${y(p.travel_s).toFixed(1)}`).join(""),
        lastX: x(last.depart),
      };
    });
    // Keep end-of-line labels apart (12 px) when the routes end close together.
    lines.sort((a, b) => a.labelY - b.labelY);
    for (let i = 1; i < lines.length; i++) {
      if (lines[i].labelY - lines[i - 1].labelY < 12) lines[i].labelY = lines[i - 1].labelY + 12;
    }
    const band = slots.every((s) => s.low_s != null)
      ? slots.map((s, i) => `${i ? "L" : "M"}${x(s.depart)},${y(s.high_s!)}`).join("") +
        [...slots].reverse().map((s) => `L${x(s.depart)},${y(s.low_s!)}`).join("") + "Z"
      : null;
    const thr = plan.recommendation.threshold_s;
    const peak: [number, number][] = [];
    if (thr) {
      let start: number | null = null;
      slots.forEach((s, i) => {
        const bad = s.best_s > thr;
        if (bad && start == null) start = i;
        if ((!bad || i === slots.length - 1) && start != null) {
          const end = bad ? i : i - 1;
          const half = (W - M.l - M.r) / (slots.length - 1) / 2;
          peak.push([x(slots[start].depart) - half, x(slots[end].depart) + half]);
          start = null;
        }
      });
    }
    const ticks = [yMin, (yMin + yMax) / 2, yMax];
    const xTicks = slots.filter((s) => new Date(s.depart).getMinutes() === 0);
    return { x, y, lines, band, peak, ticks, xTicks };
  }, [plan]);

  if (!geo) return null;
  const h = hover != null ? slots[hover] : null;

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Travel time by departure time"
           onMouseLeave={() => setHover(null)}
           onMouseMove={(e) => {
             const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
             const px = ((e.clientX - r.left) / r.width) * W;
             let bi = 0, bd = Infinity;
             slots.forEach((s, i) => { const d = Math.abs(geo.x(s.depart) - px); if (d < bd) { bd = d; bi = i; } });
             setHover(bi);
           }}
           onTouchStart={(e) => {
             const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
             const px = ((e.touches[0].clientX - r.left) / r.width) * W;
             let bi = 0, bd = Infinity;
             slots.forEach((s, i) => { const d = Math.abs(geo.x(s.depart) - px); if (d < bd) { bd = d; bi = i; } });
             setHover(bi);
           }}>
        {geo.peak.map(([a, b], i) => (
          <rect key={i} x={Math.max(M.l, a)} y={M.t} width={Math.min(W - M.r, b) - Math.max(M.l, a)} height={H - M.t - M.b}
                fill="#fab219" opacity="0.07" rx="4" />
        ))}
        {geo.ticks.map((v, i) => (
          <g key={v}>
            <line x1={M.l} x2={W - M.r} y1={geo.y(v * 60)} y2={geo.y(v * 60)} stroke="rgba(255,255,255,0.06)" />
            {i > 0 && <text x={M.l - 6} y={geo.y(v * 60) + 3.5} textAnchor="end" fontSize="9.5" fill="#6c778a">{Math.round(v)}{i === geo.ticks.length - 1 ? "′" : ""}</text>}
          </g>
        ))}
        {geo.xTicks.map((s) => (
          <text key={s.depart} x={geo.x(s.depart)} y={H - 5} textAnchor="middle" fontSize="9.5" fill="#6c778a">{clock(s.depart)}</text>
        ))}
        {geo.band && <path d={geo.band} fill="#3987e5" opacity="0.15" />}
        {geo.lines.map((l) => (
          <g key={l.id}>
            <path d={l.d} fill="none" stroke={l.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
            <text x={l.lastX + 6} y={l.labelY} fontSize="10" fill="#a6b0c0">{l.name}</text>
          </g>
        ))}
        {h && (
          <g>
            <line x1={geo.x(h.depart)} x2={geo.x(h.depart)} y1={M.t} y2={H - M.b} stroke="rgba(233,238,246,0.4)" />
            {Object.entries(h.by_route).map(([id, sec]) => (
              <circle key={id} cx={geo.x(h.depart)} cy={geo.y(sec)} r="4" fill={ROUTE_COLORS[id] ?? "#9aa8bd"} stroke="#0b0f17" strokeWidth="2" />
            ))}
          </g>
        )}
      </svg>
      {h && (
        <div className="tooltip" style={{ left: `${Math.min(72, Math.max(28, (geo.x(h.depart) / W) * 100))}%`, top: 2 }}>
          <b>Leave {clock(h.depart)}</b>
          {Object.entries(h.by_route).sort((a, b) => a[1] - b[1]).map(([id, sec]) => (
            <div key={id}><i style={{ background: ROUTE_COLORS[id] }} />{plan.routes[id]?.name}: {Math.round(sec / 60)} min · arrive {clock(new Date(new Date(h.depart).getTime() + sec * 1000))}</div>
          ))}
          {h.low_s != null && <div className="muted">likely {Math.round(h.low_s / 60)}–{Math.round(h.high_s! / 60)} min</div>}
        </div>
      )}
    </div>
  );
}

const ICON: Record<Factor["effect"], string> = { lighter: "↓", heavier: "↑", mixed: "~" };

export default function PlanPanel({ plan, error, mode, setMode, workdayLabel, alerts }: Props) {
  // For a later day only lasting things (works, closures) matter, not today's jams or accidents.
  const relevant = mode === "workday" ? alerts.filter((a) => LASTING.has(a.title)) : alerts;
  const why: (Factor | (Alert & { kind: "alert" }))[] = [
    ...relevant.slice(0, 4).map((a) => ({ ...a, kind: "alert" as const })),
    ...(plan?.factors ?? []),
  ];
  const acc = plan?.accuracy;
  const short = acc?.groups.find((g) => g.horizon === "< 1 h ahead") ?? acc?.groups[0];

  return (
    <div className="plan">
      <div className="tl-head">
        <span className="eyebrow">When to leave</span>
        <div className="chips">
          <button className={mode === "next" ? "on" : ""} onClick={() => setMode("next")}>Next 3 h</button>
          <button className={mode === "workday" ? "on" : ""} onClick={() => setMode("workday")}>{workdayLabel}</button>
        </div>
      </div>

      {error && !plan && <div className="muted small">{error}</div>}
      {!plan && !error && <div className="tl-skeleton" />}
      {plan && (
        <>
          <div className="rec">
            <div className="rec-head">{plan.recommendation.headline}</div>
            {plan.recommendation.detail && <div className="rec-detail">{plan.recommendation.detail}</div>}
          </div>

          <Chart plan={plan} />

          <div className="options">
            {plan.recommendation.options.map((o) => (
              <div key={o.depart} className="opt">
                <span className="opt-label">{o.label}</span>
                <span className="opt-time">{o.depart} <i>→</i> {o.arrive}</span>
                <span className="opt-min">{o.minutes}′ · {o.route}</span>
              </div>
            ))}
          </div>
          {plan.route_notes.map((n) => <div key={n} className="note-line">{n}</div>)}

          {plan.live && (
            <div className="live">
              <div className="live-head">
                <span className="eyebrow">On the road now</span>
                <span className={`trend ${plan.live.trend}`}>
                  {plan.live.trend === "building" ? "Building up" : plan.live.trend === "clearing" ? "Clearing" :
                   plan.live.trend === "steady" ? "Steady" : "Measuring"}
                  {plan.live.route_change_min != null && plan.live.route_change_min !== 0 &&
                    ` · ${plan.live.route_change_min > 0 ? "+" : ""}${plan.live.route_change_min} min in 30 min`}
                </span>
              </div>
              {plan.live.slowest.filter((s) => s.ratio < 0.85).slice(0, 3).map((s) => (
                <div key={s.name} className="seg">
                  <span>{s.name}</span>
                  <span className="seg-bar"><i style={{ width: `${Math.round(s.ratio * 100)}%` }} /></span>
                  <span className="seg-v">{Math.round(s.speed)}<small>/{Math.round(s.free_speed)} km/h</small></span>
                </div>
              ))}
              {plan.live.slowest.every((s) => s.ratio >= 0.85) && <div className="muted small">Flowing normally on your route.</div>}
            </div>
          )}

          <div className="why">
            <span className="eyebrow">Why</span>
            <ul>
              {why.map((f, i) => f.kind === "alert" ? (
                <li key={`a${i}`} className="heavier">
                  <span className="ic" style={{ color: (f as Alert).color }}>●</span>
                  <div><b>{(f as Alert).title}</b><small>{(f as Alert).where}</small></div>
                </li>
              ) : (
                <li key={`f${i}`} className={(f as Factor).effect}>
                  <span className="ic">{ICON[(f as Factor).effect]}</span>
                  <div><b>{(f as Factor).title}</b><small>{(f as Factor).detail}</small></div>
                </li>
              ))}
            </ul>
          </div>

          <div className="source">
            {plan.forecast_source}.{" "}
            {short && short.n >= 5
              ? `Past forecasts on your routes were off by ${Math.round(short.mae_s / 60)} min on average (${acc!.scored} checked).`
              : "Accuracy appears once forecasts can be checked against recorded trips."}
            {plan.band_basis && ` Shaded range: ${plan.band_basis.toLowerCase()}`}
          </div>
        </>
      )}
    </div>
  );
}
