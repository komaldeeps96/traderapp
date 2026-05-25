import { useRef, useCallback } from 'react';

export function useChartData() {
  const barsRef = useRef([]);
  const latestBarRef = useRef(null);

  const processHistory = useCallback((bars) => {
    barsRef.current = bars;
    latestBarRef.current = bars[bars.length - 1];
    return { bars, latest: latestBarRef.current };
  }, []);

  const processUpdate = useCallback((bar) => {
    const bars = barsRef.current;
    const last = bars[bars.length - 1];
    if (last && last.time === bar.time) {
      bars[bars.length - 1] = bar;
    } else {
      bars.push(bar);
    }
    latestBarRef.current = bar;
    return { bars, latest: bar };
  }, []);

  const clearData = useCallback(() => {
    barsRef.current = [];
    latestBarRef.current = null;
  }, []);

  return { barsRef, latestBarRef, processHistory, processUpdate, clearData };
}
