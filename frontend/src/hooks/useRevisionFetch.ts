"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

export interface RevisionFetch<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => Promise<void>;
}

/**
 * Fetch `load()` whenever `revision` changes (coalescing bursts of telemetry events) and keep
 * the latest successful result. 404s mean "nothing to show yet" — nothing is invented.
 */
export function useRevisionFetch<T>(load: (() => Promise<T>) | null, revision: number, delayMs = 200): RevisionFetch<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    if (!load) return;
    const mine = ++seq.current;
    setLoading(true);
    try {
      const value = await load();
      if (mine === seq.current) {
        setData(value);
        setError(null);
      }
    } catch (err) {
      if (mine !== seq.current) return;
      if (err instanceof ApiError && err.status === 404) setData(null);
      else setError(err instanceof ApiError ? err.message : "Could not load the latest details.");
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [load]);

  useEffect(() => {
    if (!load) {
      setData(null);
      return undefined;
    }
    const timer = setTimeout(() => void reload(), delayMs);
    return () => clearTimeout(timer);
  }, [load, revision, reload, delayMs]);

  return { data, error, loading, reload };
}
