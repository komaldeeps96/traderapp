import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/http";

/**
 * One REST read that follows the charted symbol.
 *
 * The answer is held against the key of the request that produced it, so the
 * previous company's answer is never drawn under a new ticker while the next
 * one loads, and a failed request reads as a failure, not as "nothing on file".
 */
export interface SymbolResource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

interface Settled<T> {
  key: string;
  data: T | null;
  error: string | null;
}

/** An empty ``key`` means there is nothing to fetch. */
export function useSymbolResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
): SymbolResource<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  // The loader closes over the render that asked; only a new key refetches.
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    loadRef.current(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setSettled({ key, data, error: null });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setSettled({ key, data: null, error: describe(error) });
        }
      },
    );
    return () => controller.abort();
  }, [key]);

  const current = settled?.key === key ? settled : null;
  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    loading: key !== "" && current === null,
  };
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return `the server answered ${error.status}`;
  return "the backend could not be reached";
}
