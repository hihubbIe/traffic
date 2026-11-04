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

export interface RecordingTable { rows: number; first: string | null; last: string | null }

export interface Status {
  tomtom_key: boolean;
  recording: boolean;
  recordings: { size_mb?: number } & Partial<Record<"cita_obs" | "dir_obs" | "corridor_obs" | "events_seen", RecordingTable>>;
}

export const mins = (s: number | null | undefined) => (s == null ? "–" : String(Math.round(s / 60)));

export const clock = (d: Date | string) =>
  new Date(d).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

export const isoDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export const hhmm = (d: Date) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
