import { useCallback, useEffect, useState } from 'react';

import { getEngine } from '@/chart/engineRef';
import { useTerminalStore } from '@/store/useTerminalStore';

import { ChartButton } from './ChartButton';

const GAP_ABOVE_PANES = 10;
const FALLBACK_OFFSET = 140;

/**
 * Floating zoom and pan controls, centred above the sub-panes.
 *
 * The vertical offset is measured from the chart rather than hardcoded: the
 * sub-panes sit below the price pane and can be resized by dragging their
 * separator, and a fixed offset would leave the controls stranded over the
 * volume bars or the time axis. An earlier version pinned them flush in the
 * corner, where they landed on the axis in translucent white — present,
 * clickable, and invisible.
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
      </div>
    </div>
  );
}

/**
 * Track the height of the panes below the price pane.
 *
 * lightweight-charts does not announce a pane resize, so this samples after
 * everything that can cause one: a new snapshot (which is when the sub-panes
 * are actually built — sampling only at mount reads a chart that has no
 * volume pane yet), the window resizing, and the mouse being released after a
 * separator drag.
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
     * window resize event we hear, and its panes settle a frame or two after
     * that. Sampling once on the event reads the pre-resize geometry and
     * keeps it, leaving the controls stranded over the volume bars until
     * something else happens to resample.
     *
     * Converging beats guessing at a delay: it re-reads each frame until
     * two agree, so it is as quick as the browser is and does not depend on
     * a timeout being long enough on a loaded machine.
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

    sample();
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
