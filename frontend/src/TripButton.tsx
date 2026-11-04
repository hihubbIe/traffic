import { useEffect, useState } from "react";
import { api, clock, Direction, Trip } from "./api";

/** One tap when you leave, one when you arrive: your real trip times train the model. */
export default function TripButton({ direction, route }: { direction: Direction; route: string }) {
  const [open, setOpen] = useState<Trip | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Trip[]>("/api/trips?limit=1")
      .then((t) => setOpen(t[0] && !t[0].arrive_ts && Date.now() / 1000 - t[0].depart_ts < 4 * 3600 ? t[0] : null))
      .catch(() => {});
  }, []);

  const send = async (action: "depart" | "arrive" | "cancel") => {
    setBusy(true);
    try {
      const t = await api<Trip>("/api/trips", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, direction, route }),
      });
      setOpen(action === "depart" ? t : null);
    } finally {
      setBusy(false);
    }
  };

  if (open) {
    return (
      <span className="trip">
        <span className="muted">Left {clock(new Date(open.depart_ts * 1000))}</span>
        <button className="trip-btn on" disabled={busy} onClick={() => send("arrive")}>Arrived</button>
        <button className="trip-x" disabled={busy} onClick={() => send("cancel")} aria-label="Cancel trip">×</button>
      </span>
    );
  }
  return <button className="trip-btn" disabled={busy} onClick={() => send("depart")}>I'm leaving</button>;
}
