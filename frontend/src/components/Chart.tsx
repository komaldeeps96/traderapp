import { useEffect, useRef } from 'react';

import { ChartEngine } from '@/chart/ChartEngine';
import { getEngine, setEngine } from '@/chart/engineRef';
import { useKeyLevels } from '@/hooks/useKeyLevels';
import { loadTheme } from '@/lib/storage';
import { buildBands, buildLevelStyles } from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';

/**
 * Hosts the chart canvas.
 *
 * The component owns the DOM node and the engine's lifetime and nothing else —
 * no bar ever passes through React state.
 */
export function Chart() {
  const containerRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<number | null>(null);
  const pendingRef = useRef<number | null>(null);
  const theme = useTerminalStore((state) => state.theme);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const engine = new ChartEngine({
      container,
      // Read straight from storage: the store may not have hydrated yet, and
      // creating the chart with the wrong palette causes a visible flash.
      theme: loadTheme(),
      zoomSlot: 'main',
      onCrosshairMove: (time) => {
        pendingRef.current = time;
        // The crosshair fires on every mouse move; collapsing to one update
        // per frame keeps the readout smooth instead of thrashing React.
        if (frameRef.current !== null) return;
        frameRef.current = requestAnimationFrame(() => {
          frameRef.current = null;
          publishHover(pendingRef.current);
        });
      },
    });

    setEngine(engine);

    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
      setEngine(null);
      engine.destroy();
    };
  }, []);

  useEffect(() => {
    getEngine()?.setTheme(theme);
  }, [theme]);

  useLevelStyling();

  return (
    <div
      ref={containerRef}
      data-testid="chart-canvas"
      className="h-full w-full min-h-0 min-w-0"
      role="img"
      aria-label="Price chart"
    />
  );
}

/**
 * Keep the drawn levels in step with the computed confluence bands.
 *
 * The bands are recomputed as the price moves, but the styling only reaches
 * the chart when it actually differs — otherwise every live bar would
 * re-apply options to two dozen series once a second for no visible change.
 * The snapshot counter forces a reapply after the series are rebuilt.
 */
function useLevelStyling(): void {
  const { clusters } = useKeyLevels();
  const theme = useTerminalStore((state) => state.theme);
  const snapshotEpoch = useTerminalStore((state) => state.snapshotEpoch);
  const appliedRef = useRef<string>('');

  useEffect(() => {
    const styles = buildLevelStyles(clusters, theme);
    const bands = buildBands(clusters, theme);
    const signature = `${snapshotEpoch}|${JSON.stringify(styles)}|${JSON.stringify(bands)}`;
    if (signature === appliedRef.current) return;
    appliedRef.current = signature;
    const engine = getEngine();
    engine?.setLevelStyles(styles);
    engine?.setBands(bands);
  }, [clusters, theme, snapshotEpoch]);
}

function publishHover(time: number | null): void {
  const engine = getEngine();
  const store = useTerminalStore.getState();

  if (time === null || !engine) {
    if (store.hovered) store.setHovered(null);
    return;
  }

  const bar = engine.barAt(time);
  if (!bar) {
    if (store.hovered) store.setHovered(null);
    return;
  }

  store.setHovered({
    bar,
    previousClose: engine.previousClose(time),
    values: engine.valuesAt(time),
    sessionVolume: engine.sessionVolumeAt(time),
  });
}
