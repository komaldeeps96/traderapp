import { useCallback, useSyncExternalStore } from 'react';

/** The wall clock in epoch seconds, stepping every `periodMs`. */
export function useNow(periodMs: number): number {
  const subscribe = useCallback(
    (onStep: () => void) => {
      const timer = setInterval(onStep, periodMs);
      return () => clearInterval(timer);
    },
    [periodMs],
  );
  return useSyncExternalStore(subscribe, () => stepped(periodMs));
}

// Constant within a step, which is what lets React skip the renders between.
function stepped(periodMs: number): number {
  return (Math.floor(Date.now() / periodMs) * periodMs) / 1000;
}
