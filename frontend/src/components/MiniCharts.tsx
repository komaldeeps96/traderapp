import { useEffect, useRef } from 'react';

import { ChartEngine } from '@/chart/ChartEngine';
import { getMiniEngine, setMiniEngine } from '@/chart/engineRef';
import {
  MINI_COLUMN_QUERY,
  MINI_COLUMN_WIDTH,
  MINI_CONFIG,
  MINI_TIMEFRAMES,
  type MiniTimeframe,
} from '@/chart/mini';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { loadTheme } from '@/lib/storage';
import { useTerminalStore } from '@/store/useTerminalStore';

import { ChartButton } from './ChartButton';

/**
 * The column of context charts to the right of the main one.
 *
 * 1-minute above 5-minute, both on whatever symbol the main chart is showing.
 * The main chart usually sits on the 10-second tape, which is the wrong
 * distance to judge a trend from; these keep the other two clocks in view
 * without costing a timeframe switch.
 *
 * They are read-only in every sense: no crosshair callback, so hovering one
 * cannot disturb the main chart's OHLCV readout, and no toolbar of their own.
 */
export function MiniCharts() {
  const wideEnough = useMediaQuery(MINI_COLUMN_QUERY);
  if (!wideEnough) return null;

  return (
    <aside
      className="flex h-full shrink-0 flex-col border-l border-line bg-surface"
      style={{ width: MINI_COLUMN_WIDTH }}
      aria-label="Context charts"
      data-testid="mini-charts"
    >
      {MINI_TIMEFRAMES.map((timeframe) => (
        <MiniChart key={timeframe} timeframe={timeframe} />
      ))}
    </aside>
  );
}

/**
 * One mini chart.
 *
 * Mirrors `Chart.tsx`: the component owns the DOM node and the engine's
 * lifetime, and registers the engine under its timeframe so the WebSocket
 * wiring can reach it. No bar passes through React.
 */
function MiniChart({ timeframe }: { timeframe: MiniTimeframe }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const theme = useTerminalStore((state) => state.theme);
  const symbol = useTerminalStore((state) => state.symbol);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const engine = new ChartEngine({
      container,
      // Straight from storage, as the main chart does: the store may not have
      // hydrated yet and the wrong palette flashes.
      theme: loadTheme(),
      mini: MINI_CONFIG[timeframe],
    });
    setMiniEngine(timeframe, engine);

    return () => {
      setMiniEngine(timeframe, null);
      engine.destroy();
    };
  }, [timeframe]);

  useEffect(() => {
    getMiniEngine(timeframe)?.setTheme(theme);
  }, [theme, timeframe]);

  return (
    <section className="flex min-h-0 flex-1 flex-col border-b border-line last:border-b-0">
      {/* In the header rather than floating over the canvas: a mini chart has
          no room to give up, and buttons sitting on the candles are the first
          thing that gets in the way of reading one. Reset is the ↺ glyph, not
          the word — it buys back about 30px of every row. */}
      <header className="flex h-[22px] shrink-0 items-center gap-1.5 px-1.5">
        <h2 className="text-[10px] font-bold uppercase tracking-wider text-ink-2">{timeframe}</h2>
        <span className="min-w-0 flex-1 truncate text-[10px] font-semibold text-ink-3">
          {symbol}
        </span>
        <div className="flex shrink-0 items-center gap-0.5">
          <ChartButton
            size="sm"
            onClick={() => getMiniEngine(timeframe)?.zoomOut()}
            label={`Zoom out ${timeframe} chart`}
          >
            −
          </ChartButton>
          <ChartButton
            size="sm"
            onClick={() => getMiniEngine(timeframe)?.zoomIn()}
            label={`Zoom in ${timeframe} chart`}
          >
            +
          </ChartButton>
          <ChartButton
            size="sm"
            onClick={() => getMiniEngine(timeframe)?.resetView()}
            label={`Reset ${timeframe} chart`}
            testId={`mini-reset-${timeframe}`}
          >
            ↺
          </ChartButton>
        </div>
      </header>
      <div
        ref={containerRef}
        data-testid={`mini-chart-${timeframe}`}
        className="min-h-0 min-w-0 flex-1"
        role="img"
        aria-label={`${symbol} ${timeframe} chart`}
      />
    </section>
  );
}
