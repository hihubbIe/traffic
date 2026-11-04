import { useEffect, useState } from "react";
import { api, clock, CurvePoint, Direction, hhmm, isoDay } from "./api";

type Mode = "next" | "workday";

function nextWorkday(from: Date): Date {
  const d = new Date(from.getFullYear(), from.getMonth(), from.getDate() + 1);
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1);
  return d;
}

function window_(mode: Mode, direction: Direction, now: Date) {
  if (mode === "workday") {
    const d = nextWorkday(now);
    const [start, end] = direction === "to_work" ? ["06:00", "09:30"] : ["16:00", "19:30"];
    return { day: isoDay(d), start, end, label: d.toLocaleDateString("en-GB", { weekday: "long" }) };
  }
  const s = new Date(now);
  s.setMinutes(Math.floor(s.getMinutes() / 15) * 15, 0, 0);
  let e = new Date(s.getTime() + 105 * 60_000);
  if (e.getDate() !== s.getDate()) e = new Date(s.getFullYear(), s.getMonth(), s.getDate(), 23, 45);
  return { day: isoDay(s), start: hhmm(s), end: hhmm(e), label: "Next 2 h" };
}

export default function LeaveTimeline({ corridor, direction, enabled }: { corridor: string; direction: Direction; enabled: boolean }) {
  const [mode, setMode] = useState<Mode>("next");
  const [points, setPoints] = useState<CurvePoint[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const w = window_(mode, direction, new Date());
  const key = `${corridor}|${direction}|${w.day}|${w.start}|${w.end}`;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setPoints(null);
    setErr(null);
    api<{ points: CurvePoint[] }>(`/api/corridors/${corridor}/curve?direction=${direction}&day=${w.day}&start=${w.start}&end=${w.end}`)
      .then((r) => !cancelled && setPoints(r.points.filter((p) => p.travel_s != null)))
      .catch((e) => !cancelled && setErr(e.message));
    return () => { cancelled = true; };
  }, [key, enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  const best = points?.length ? points.reduce((b, p) => (p.travel_s! < b.travel_s! ? p : b)) : null;
  const max = points?.length ? Math.max(...points.map((p) => p.travel_s!)) : 1;
  const shown = hover != null && points ? points[hover] : best;

  return (
    <div className="timeline">
      <div className="tl-head">
        <span className="eyebrow">When to leave</span>
        <div className="chips">
          <button className={mode === "next" ? "on" : ""} onClick={() => setMode("next")}>Next 2 h</button>
          <button className={mode === "workday" ? "on" : ""} onClick={() => setMode("workday")}>
            {window_("workday", direction, new Date()).label}
          </button>
        </div>
      </div>

      {err && <div className="muted small">{err}</div>}
      {!points && !err && <div className="tl-skeleton" />}
      {points && points.length > 0 && (
        <>
          <div className="tl-readout">
            {shown && (
              <>
                <span className="tl-time">{clock(shown.depart)}</span>
                <span className="tl-val">{Math.round(shown.travel_s! / 60)} min</span>
                {shown === best && <span className="tag">best</span>}
              </>
            )}
          </div>
          <div className="bars" onMouseLeave={() => setHover(null)}>
            {points.map((p, i) => (
              <button key={p.depart} className={`bar ${p === best ? "best" : ""} ${hover === i ? "hover" : ""}`}
                      aria-label={`Leave ${clock(p.depart)}: ${Math.round(p.travel_s! / 60)} minutes`}
                      onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onClick={() => setHover(i)}>
                <i style={{ height: `${Math.max(8, (p.travel_s! / max) * 100)}%` }} />
              </button>
            ))}
          </div>
          <div className="tl-axis">
            <span>{clock(points[0].depart)}</span>
            <span>{clock(points[points.length - 1].depart)}</span>
          </div>
        </>
      )}
      {points && points.length === 0 && <div className="muted small">No departures left in this window.</div>}
    </div>
  );
}
