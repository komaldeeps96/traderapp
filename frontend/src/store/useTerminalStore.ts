/**
 * Application state.
 *
 * Deliberately small: bars live in the ChartEngine, not here. This store holds
 * only what React renders — the readout, the toggles, the scanner — so a bar
 * update once a second re-renders a handful of numbers rather than a chart.
 */

import { create } from 'zustand';

import { defaultVisibility, loadVisibility, saveVisibility, type Theme } from '@/lib/storage';
import type {
  ApiUsageMessage,
  DataSource,
  IndicatorSpec,
  InfoMessage,
  MarketRegime,
  QuoteMessage,
  ScannerConfig,
  ScannerRow,
  Timeframe,
  WireBar,
} from '@/types/protocol';

export type ChartStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface Readout {
  bar: WireBar;
  /** Close of the preceding bar, for the bar-over-bar change. */
  previousClose: number | null;
  values: Record<string, number>;
}

interface TerminalState {
  // connection & data source
  connected: boolean;
  source: DataSource;
  delayed: boolean;
  ibkrConnected: boolean;
  alpacaAvailable: boolean;
  sourceNote: string | null;

  // chart
  symbol: string;
  timeframe: Timeframe;
  status: ChartStatus;
  error: string | null;
  barCount: number;
  live: Readout | null;
  hovered: Readout | null;
  /** Bumped per snapshot. Rebuilding the series resets styling, so anything
   *  that decorates the chart watches this to know it must reapply. */
  snapshotEpoch: number;

  // per-symbol level 1 + reference data
  quote: QuoteMessage | null;
  info: InfoMessage | null;

  // upstream request budgets
  apiUsage: ApiUsageMessage | null;

  // indicators
  specs: IndicatorSpec[];
  visibility: Record<string, boolean>;

  // scanner
  scannerRows: ScannerRow[];
  scannerConfig: ScannerConfig | null;
  scannerRunning: boolean;
  scannerAvailable: boolean;
  scannerNote: string | null;
  scanCodes: Array<{ code: string; label: string }>;

  // market regime
  regimeRunning: boolean;
  regimeError: string | null;
  regime: MarketRegime | null;

  theme: Theme;

  // actions
  setConnected: (connected: boolean) => void;
  setSourceStatus: (status: {
    source: DataSource;
    delayed: boolean;
    ibkrConnected: boolean;
    alpacaAvailable: boolean;
    note: string | null;
  }) => void;
  setSpecs: (specs: IndicatorSpec[]) => void;
  requestChart: (symbol: string, timeframe: Timeframe) => void;
  chartReady: (payload: { symbol: string; timeframe: Timeframe; barCount: number; live: Readout | null }) => void;
  setLive: (live: Readout, barCount: number) => void;
  setHovered: (hovered: Readout | null) => void;
  setError: (message: string) => void;
  toggleIndicator: (id: string) => void;
  setAllIndicators: (ids: string[], visible: boolean) => void;
  setScanner: (payload: { rows: ScannerRow[]; config: ScannerConfig; running: boolean }) => void;
  setScannerMeta: (payload: {
    available: boolean;
    note: string | null;
    scanCodes: Array<{ code: string; label: string }>;
    config?: ScannerConfig;
  }) => void;
  setQuote: (quote: QuoteMessage) => void;
  setInfo: (info: InfoMessage) => void;
  setApiUsage: (usage: ApiUsageMessage) => void;
  setRegime: (payload: {
    regime: MarketRegime;
    running: boolean;
    error: string | null;
  }) => void;
  setTheme: (theme: Theme) => void;
}

export const useTerminalStore = create<TerminalState>((set, get) => ({
  connected: false,
  source: 'none',
  delayed: false,
  ibkrConnected: false,
  alpacaAvailable: false,
  sourceNote: null,

  symbol: '',
  timeframe: '10s',
  status: 'idle',
  error: null,
  barCount: 0,
  live: null,
  hovered: null,
  snapshotEpoch: 0,

  quote: null,
  info: null,
  apiUsage: null,

  specs: [],
  visibility: {},

  scannerRows: [],
  scannerConfig: null,
  scannerRunning: false,
  scannerAvailable: false,
  scannerNote: null,
  scanCodes: [],

  regimeRunning: false,
  regimeError: null,
  regime: null,

  theme: 'dark',

  setConnected: (connected) => set({ connected }),

  setSourceStatus: ({ source, delayed, ibkrConnected, alpacaAvailable, note }) =>
    set({ source, delayed, ibkrConnected, alpacaAvailable, sourceNote: note }),

  setSpecs: (specs) => {
    const { timeframe } = get();
    set({ specs, visibility: loadVisibility(specs, timeframe) });
  },

  requestChart: (symbol, timeframe) => {
    const state = get();
    const changedTimeframe = state.timeframe !== timeframe;
    const changedSymbol = state.symbol !== symbol;
    set({
      symbol,
      timeframe,
      status: 'loading',
      error: null,
      hovered: null,
      // A stale readout under a new symbol reads as live data for the wrong
      // instrument, so it is cleared immediately rather than on arrival.
      live: null,
      barCount: 0,
      quote: changedSymbol ? null : state.quote,
      info: changedSymbol ? null : state.info,
      visibility: changedTimeframe ? loadVisibility(state.specs, timeframe) : state.visibility,
    });
  },

  chartReady: ({ symbol, timeframe, barCount, live }) =>
    set((state) => ({
      symbol,
      timeframe,
      barCount,
      live,
      status: 'ready',
      error: null,
      snapshotEpoch: state.snapshotEpoch + 1,
    })),

  setLive: (live, barCount) => set({ live, barCount }),

  setHovered: (hovered) => set({ hovered }),

  setError: (message) => set({ status: 'error', error: message }),

  toggleIndicator: (id) => {
    const { visibility, timeframe } = get();
    const next = { ...visibility, [id]: !visibility[id] };
    saveVisibility(timeframe, next);
    set({ visibility: next });
  },

  setAllIndicators: (ids, visible) => {
    const { visibility, timeframe } = get();
    const next = { ...visibility };
    for (const id of ids) next[id] = visible;
    saveVisibility(timeframe, next);
    set({ visibility: next });
  },

  setScanner: ({ rows, config, running }) =>
    set({ scannerRows: rows, scannerConfig: config, scannerRunning: running }),

  setScannerMeta: ({ available, note, scanCodes, config }) =>
    set((state) => ({
      scannerAvailable: available,
      scannerNote: note,
      scanCodes,
      scannerConfig: config ?? state.scannerConfig,
    })),

  setQuote: (quote) => set({ quote }),

  setInfo: (info) => set({ info }),

  setApiUsage: (usage) => set({ apiUsage: usage }),

  setRegime: ({ regime, running, error }) =>
    set({ regime, regimeRunning: running, regimeError: error }),

  setTheme: (theme) => set({ theme }),
}));

/** Reset helper for tests. */
export function resetTerminalStore(specs: IndicatorSpec[] = []): void {
  useTerminalStore.setState({
    connected: false,
    source: 'none',
    delayed: false,
    ibkrConnected: false,
    alpacaAvailable: false,
    sourceNote: null,
    symbol: '',
    timeframe: '10s',
    status: 'idle',
    error: null,
    barCount: 0,
    live: null,
    hovered: null,
    snapshotEpoch: 0,
    quote: null,
    info: null,
    apiUsage: null,
    specs,
    visibility: defaultVisibility(specs, '10s'),
    scannerRows: [],
    scannerConfig: null,
    scannerRunning: false,
    scannerAvailable: false,
    scannerNote: null,
    scanCodes: [],
    regimeRunning: false,
    regimeError: null,
    regime: null,
    theme: 'dark',
  });
}
