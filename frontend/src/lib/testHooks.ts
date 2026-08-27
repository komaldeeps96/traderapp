/**
 * A read-only window onto the chart, for tests and debugging.
 *
 * The chart draws to a canvas, so there is nothing in the DOM to assert
 * against — a browser test cannot otherwise tell "the EMA series received 400
 * points" from "the series is empty". This exposes what the engine actually
 * drew. It is read-only: nothing here can change application state.
 */

import { getEngine, getMiniEngine } from '@/chart/engineRef';
import type { Timeframe } from '@/types/protocol';
import { useTerminalStore } from '@/store/useTerminalStore';

type ChartReport = ReturnType<NonNullable<ReturnType<typeof getEngine>>['inspect']>;

export interface TerminalTestHooks {
  chart: () => ChartReport | null;
  /** The same report for a mini chart, or null when the column is not shown. */
  miniChart: (timeframe: Timeframe) => ChartReport | null;
  state: () => {
    symbol: string;
    timeframe: string;
    status: string;
    connected: boolean;
    source: string;
    delayed: boolean;
    barCount: number;
    visibility: Record<string, boolean>;
  };
  ready: () => boolean;
}

declare global {
  interface Window {
    __traderapp?: TerminalTestHooks;
  }
}

export function installTestHooks(): void {
  if (typeof window === 'undefined') return;

  window.__traderapp = {
    chart: () => getEngine()?.inspect() ?? null,
    // Addressed by timeframe, as the tests read them; the first slot showing
    // that timeframe answers.
    miniChart: (timeframe) => {
      const slot = useTerminalStore.getState().miniTimeframes.indexOf(timeframe);
      return slot >= 0 ? (getMiniEngine(slot)?.inspect() ?? null) : null;
    },
    state: () => {
      const state = useTerminalStore.getState();
      return {
        symbol: state.symbol,
        timeframe: state.timeframe,
        status: state.status,
        connected: state.connected,
        source: state.source,
        delayed: state.delayed,
        barCount: state.barCount,
        visibility: state.visibility,
      };
    },
    ready: () => useTerminalStore.getState().status === 'ready',
  };
}
