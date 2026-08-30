import { useEffect, useRef } from 'react';

import { ChartEngine } from '@/chart/ChartEngine';
import { getMiniEngine, setMiniEngine } from '@/chart/engineRef';
import { MINI_TIMEFRAME_CHOICES, miniConfig } from '@/chart/mini';
import type { Timeframe } from '@/types/protocol';
import { hydrateMini } from '@/hooks/useTerminal';
import { loadTheme } from '@/lib/storage';
import { useTerminalStore } from '@/store/useTerminalStore';

import { ChartButton } from './ChartButton';

/**
 * The column of context charts — the dock's first tab.
 *
 * 1-minute above 5-minute, both on whatever symbol the main chart is showing.
 * The main chart usually sits on the 10-second tape, which is the wrong
 * distance to judge a trend from; these keep the other two clocks in view
 * without costing a timeframe switch.
 *
 * They are read-only in every sense: no crosshair callback, so hovering one
 * cannot disturb the main chart's OHLCV readout, and no toolbar of their own.
 *
 * The rail, its width and the breakpoint below which none of this is built
 * belong to `Dock`; this renders only the charts inside it.
 */
export function MiniCharts({
  onTimeframeChange,
}: {
  onTimeframeChange: (slot: number, timeframe: Timeframe) => void;
}) {
  const timeframes = useTerminalStore((state) => state.miniTimeframes);

  return (
    <div
      className="flex min-h-0 flex-1 flex-col"
      aria-label="Context charts"
      data-testid="mini-charts"
    >
      {timeframes.map((timeframe, slot) => (
        <MiniChart
          key={slot}
          slot={slot}
          timeframe={timeframe}
          onTimeframeChange={onTimeframeChange}
        />
      ))}
    </div>
  );
}

/**
 * One mini chart.
 *
 * Mirrors `Chart.tsx`: the component owns the DOM node and the engine's
 * lifetime, and registers the engine under its timeframe so the WebSocket
 * wiring can reach it. No bar passes through React.
 */
function MiniChart({
  slot,
  timeframe,
  onTimeframeChange,
}: {
  slot: number;
  timeframe: Timeframe;
  onTimeframeChange: (slot: number, timeframe: Timeframe) => void;
}) {
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
      // Keyed by slot so a mini 1m zoom never collides with the main chart
      // sitting on 1m — they are read at very different widths.
      zoomSlot: 'mini',
      mini: miniConfig(timeframe),
    });
    setMiniEngine(slot, engine);
    // The wire sends one snapshot per subscription, and this engine may have
    // been built long after it arrived — returning to the dock's charts tab,
    // or the window crossing the breakpoint. Replay the last one for this
    // timeframe; a no-op on first load, where it is still in flight.
    hydrateMini(slot, timeframe);

    // Changing the slot's timeframe lands here via the dependency: the old
    // engine is torn down and a blank one waits for the new subscription's
    // snapshot, so 5-minute candles never masquerade as 15-minute ones.
    return () => {
      setMiniEngine(slot, null);
      engine.destroy();
    };
  }, [slot, timeframe]);

  useEffect(() => {
    getMiniEngine(slot)?.setTheme(theme);
  }, [theme, slot]);

  return (
    <section className="flex min-h-0 flex-1 flex-col border-b border-line last:border-b-0">
      {/* In the header rather than floating over the canvas: a mini chart has
          no room to give up, and buttons sitting on the candles are the first
          thing that gets in the way of reading one. Reset is the ↺ glyph, not
          the word — it buys back about 30px of every row. */}
      <header className="flex h-[22px] shrink-0 items-center gap-1.5 px-1.5">
        <select
          value={timeframe}
          onChange={(event) => onTimeframeChange(slot, event.target.value as Timeframe)}
          aria-label={`Mini chart ${slot + 1} timeframe`}
          data-testid={`mini-tf-${slot}`}
          className="rounded-sm border border-transparent bg-transparent text-[10px] font-bold uppercase tracking-wider text-ink-2 outline-none hover:border-line focus:border-accent"
        >
          {MINI_TIMEFRAME_CHOICES.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
        <span className="min-w-0 flex-1 truncate text-[10px] font-semibold text-ink-3">
          {symbol}
        </span>
        <div className="flex shrink-0 items-center gap-0.5">
          <ChartButton
            size="sm"
            onClick={() => getMiniEngine(slot)?.zoomOut()}
            label={`Zoom out ${timeframe} chart`}
          >
            −
          </ChartButton>
          <ChartButton
            size="sm"
            onClick={() => getMiniEngine(slot)?.zoomIn()}
            label={`Zoom in ${timeframe} chart`}
          >
            +
          </ChartButton>
          <ChartButton
            size="sm"
            onClick={() => getMiniEngine(slot)?.resetView()}
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
