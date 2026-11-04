import { useCallback, useEffect, useState } from "react";

export interface Poll<T> {
  data: T | null;
  error: string | null;
  at: Date | null;
  reload: () => void;
}

/** Fetches now and every `ms` (0 = once). Re-runs when `deps` change. */
export function usePoll<T>(fn: () => Promise<T | null>, ms: number, deps: unknown[] = []): Poll<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [at, setAt] = useState<Date | null>(null);
  const run = useCallback(async () => {
    try {
      const v = await fn();
      if (v !== null) {
        setData(v);
        setAt(new Date());
      }
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    run();
    if (!ms) return;
    const t = setInterval(run, ms);
    return () => clearInterval(t);
  }, [run, ms]);
  return { data, error, at, reload: run };
}

export function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

export function useStored<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const s = localStorage.getItem(key);
      return s ? { ...initial, ...JSON.parse(s) } : initial;
    } catch {
      return initial;
    }
  });
  const set = (nv: T) => {
    setV(nv);
    try {
      localStorage.setItem(key, JSON.stringify(nv));
    } catch {
      /* storage unavailable */
    }
  };
  return [v, set];
}
