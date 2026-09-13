import { useCallback, useEffect, useState } from 'react';

import { getEngine } from '@/chart/engineRef';
import { useKeyedState } from '@/hooks/useKeyedState';
import { useTerminalStore } from '@/store/useTerminalStore';

import { ChartButton } from './ChartButton';

const GAP_ABOVE_PANES = 10;
const FALLBACK_OFFSET = 140;

/**
 * Floating zoom and pan controls, centred above the sub-panes.
 *
 * The vertical offset is measured from the chart rather than hardcoded: the
 * sub-panes are resizable by dragging their separator, and a fixed offset would
 * strand the controls over the volume bars or the time axis.
 */
export function ChartControls() {
  const offset = useSubPaneOffset();

  return (
    <div
      className="pointer-events-none absolute inset-x-0 z-10 flex justify-center"
      style={{ bottom: offset + GAP_ABOVE_PANES }}
      data-testid="chart-controls"
    >
      <div className="pointer-events-auto flex items-center gap-1">
        <ChartButton onClick={() => getEngine()?.scrollLeft()} label="Scroll left">
          ‹
        </ChartButton>
        <ChartButton onClick={() => getEngine()?.zoomOut()} label="Zoom out">
          −
        </ChartButton>
        <ChartButton onClick={() => getEngine()?.zoomIn()} label="Zoom in">
          +
        </ChartButton>
        <ChartButton onClick={() => getEngine()?.scrollRight()} label="Scroll right">
          ›
        </ChartButton>
        <ChartButton onClick={() => getEngine()?.resetView()} label="Reset view" testId="reset-view" wide>
          Reset
        </ChartButton>
        <MeasureToggle />
      </div>
    </div>
  );
}

/**
 * The measure tool's switch. While on, dragging selects a region and reads out
 * its move, span and volume, and panning is suspended. Escape is the fast exit.
 */
function MeasureToggle() {
  const symbol = useTerminalStore((state) => state.symbol);
  const timeframe = useTerminalStore((state) => state.timeframe);
  // A symbol or timeframe switch clears the selection under us; the mode goes
  // with it, so the chart never silently keeps eating drag gestures.
  const [measuring, setMeasuring] = useKeyedState(`${symbol}:${timeframe}`, false);

  useEffect(() => {
    getEngine()?.setMeasureMode(measuring);
  }, [measuring]);

  useEffect(() => {
    if (!measuring) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMeasuring(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [measuring, setMeasuring]);

  return (
    <ChartButton
      onClick={() => setMeasuring(!measuring)}
      label="Measure"
      testId="measure-toggle"
      pressed={measuring}
    >
      ⤢
    </ChartButton>
  );
}

/**
 * Track the height of the panes below the price pane.
 *
 * lightweight-charts does not announce a pane resize, so this samples after
 * everything that causes one: a new snapshot (when the sub-panes are built —
 * at mount there is no volume pane yet), a window resize, and the mouse being
 * released after a separator drag.
 */
function useSubPaneOffset(): number {
  const [offset, setOffset] = useState(FALLBACK_OFFSET);
  const snapshotEpoch = useTerminalStore((state) => state.snapshotEpoch);

  const sample = useCallback(() => {
    const next = getEngine()?.subPaneOffset();
    if (typeof next === 'number' && next > 0) {
      setOffset((current) => (Math.abs(current - next) > 1 ? next : current));
    }
  }, []);

  useEffect(() => {
    let frame = 0;

    /**
     * Sample until the panes stop moving.
     *
     * The chart relayouts on its own ResizeObserver, which runs *after* the
     * window resize event, and its panes settle a frame or two later — so
     * sampling once on the event keeps the pre-resize geometry. Re-reading each
     * frame until two agree is as quick as the browser and needs no timeout.
     */
    const settle = (deadline = performance.now() + 2_000) => {
      cancelAnimationFrame(frame);
      let previous: number | null = null;
      const step = () => {
        const next = getEngine()?.subPaneOffset();
        if (typeof next === 'number' && next > 0) {
          setOffset((current) => (Math.abs(current - next) > 1 ? next : current));
          if (previous !== null && Math.abs(previous - next) <= 1) return;
          previous = next;
        }
        if (performance.now() < deadline) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    };

    settle();
    const onResize = () => settle();
    window.addEventListener('resize', onResize);
    document.addEventListener('mouseup', sample);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', onResize);
      document.removeEventListener('mouseup', sample);
    };
  }, [sample, snapshotEpoch]);

  return offset;
}
