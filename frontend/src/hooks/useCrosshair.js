import { useRef, useCallback } from 'react';

export function useCrosshair() {
  const hoverTimeRef = useRef(null);

  const handleCrosshair = useCallback((time) => {
    hoverTimeRef.current = time;
    return time;
  }, []);

  const getHoverBar = useCallback((bars) => {
    const t = hoverTimeRef.current;
    if (!t) return null;
    return bars.find((b) => b.time === t) || null;
  }, []);

  return { hoverTimeRef, handleCrosshair, getHoverBar };
}
