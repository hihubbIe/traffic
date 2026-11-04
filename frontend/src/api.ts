export type Direction = "to_work" | "to_home";

// Backend base URL: runtime override (Details > Settings) > build-time VITE_API_URL > same host, port 8000.
const API_KEY = "apiUrl";

export function apiBase(): string {
  try {
    const saved = localStorage.getItem(API_KEY);
    if (saved) return saved.replace(/\/$/, "");
  } catch {
    /* storage unavailable */
  }
  const env = import.meta.env.VITE_API_URL as string | undefined;
  if (env) return env.replace(/\/$/, "");
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

export function setApiBase(url: string) {
  try {
    if (url.trim()) localStorage.setItem(API_KEY, url.trim());
    else localStorage.removeItem(API_KEY);
  } catch {
    /* storage unavailable */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(apiBase() + path, init);
  } catch {
    throw new ApiError(0, `Can't reach the backend at ${apiBase()}`);
  }
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* not json */
    }
    throw new ApiError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

export interface CitaSite {
  id: string; road: string; time: string | null; lat: number; lon: number;
  direction: string | null; chainage: number | null;
  speed: number | null; occupancy: number | null; flow: number | null;
}

export interface DirStation {
  id: string; time: string | null; flow: number | null; speed: number | null;
  lat: number | null; lon: number | null; road: string | null; label: string | null;
  pr: number | null; sens: "1" | "2"; tmja: number | null; match: string | null;
}

export interface MatchStatus {
  weekdays_recorded: string[];
  ids_with_volume: number;
  ready: boolean;
  reason?: string;
  proposals: { id: string; station: string; road: string; pr: number; cost: number; margin: number; confident: boolean }[];
}

export interface Corridor {
  id: string; name: string; group: "usual" | "reference"; description: string;
}

export interface CorridorConfig {
  endpoints: Record<"home" | "work", { name: string; address: string; coord: [number, number] }>;
  corridors: Corridor[];
}

export interface TrafficSection {
  start: number; end: number; category: string | null; magnitude: number | null;
  delay_s: number | null; speed_kmh: number | null;
}

export interface CorridorResult {
  id: string; error?: string;
  length_m?: number; travel_s?: number; delay_s?: number; free_s?: number; historic_s?: number;
  points?: [number, number][]; passes?: string[]; traffic?: TrafficSection[];
}

export interface CurvePoint {
  depart: string; travel_s: number | null; free_s?: number; historic_s?: number;
  delay_s?: number; past?: boolean; error?: string;
}

export interface JobHealth {
  last_run: number | null; last_ok: number | null; last_error: string | null;
  runs_24h: number; failures_24h: number; rows_24h: number;
}

export interface Status {
  tomtom_key: boolean;
  collector_in_api: boolean;
  collector: { active_hours: string; collecting_now: boolean; jobs: Record<string, JobHealth> };
  tomtom_budget: { day: string; used: number; budget: number; reserve_for_app: number };
  db_mb: number;
  disk_free_gb: number;
}

export interface Trip { id: number; direction: Direction | null; route: string | null; depart_ts: number; arrive_ts: number | null }

export const mins = (s: number | null | undefined) => (s == null ? "–" : String(Math.round(s / 60)));

export const clock = (d: Date | string) =>
  new Date(d).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

export const isoDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export const hhmm = (d: Date) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

export type PlanMode = "next" | "workday";

export interface Factor {
  effect: "lighter" | "heavier" | "mixed"; strength: number; title: string; detail: string; kind: string;
}

export interface PlanOption { label: string; depart: string; arrive: string; minutes: number; route: string }

export interface Plan {
  direction: Direction;
  window: { mode: PlanMode; day: string; start: string; end: string; label: string };
  routes: Record<string, { name: string; points: { depart: string; travel_s: number; free_s?: number; arrive: string }[] }>;
  slots: { depart: string; best_route: string; best_s: number; by_route: Record<string, number>; low_s?: number; high_s?: number }[];
  recommendation: { headline: string; detail: string | null; options: PlanOption[]; best?: PlanOption; threshold_s?: number };
  route_notes: string[];
  band_basis: string | null;
  factors: Factor[];
  live: null | {
    as_of: number; trend: "building" | "clearing" | "steady" | "unknown"; route_change_min: number | null;
    slowest: { name: string; speed: number; free_speed: number; ratio: number; speed_change: number | null }[];
  };
  forecast_source: string;
  accuracy: { scored: number; groups: { source: string; horizon: string; n: number; mae_s: number; bias_s: number }[] };
}
