/**
 * Application state.
 *
 * Deliberately small: bars live in the ChartEngine, not here. This store holds
 * only what React renders — the readout, the toggles, the scanner — so a bar
 * update once a second re-renders a handful of numbers rather than a chart.
 */

import { create } from 'zustand';

import {
  loadMiniTimeframes,
  loadVisibility,
  saveMiniTimeframes,
  saveVisibility,
  type Theme,
} from '@/lib/storage';
import type {
  ApiUsageMessage,
  DataSource,
  IndicatorSpec,
  InfoMessage,
  MarketRegime,
  QuoteMessage,
  ScannerConfig,
  ScannerRow,
  ScannerTierId,
  Timeframe,
  WireBar,
} from '@/types/protocol';
import { SCANNER_TIER_IDS, SCANNER_TIER_LABELS } from '@/types/protocol';

export interface ScannerTierState {
  label: string;
  rows: ScannerRow[];
  config: ScannerConfig | null;
  running: boolean;
}

function emptyScanners(): Record<ScannerTierId, ScannerTierState> {
  const scanners = {} as Record<ScannerTierId, ScannerTierState>;
  for (const id of SCANNER_TIER_IDS) {
    scanners[id] = { label: SCANNER_TIER_LABELS[id], rows: [], config: null, running: false };
  }
  return scanners;
}

export type ChartStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface Readout {
  bar: WireBar;
  /** Close of the preceding bar, for the bar-over-bar change. */
  previousClose: number | null;
  values: Record<string, number>;
  /** Cumulative session volume as of this bar, from the chart's bars. */
  sessionVolume: number | null;
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

  // scanner — one entry per market-cap tier, each independently filtered
  // and persisted (see ScannerPanel/backend ScannerService).
  scanners: Record<ScannerTierId, ScannerTierState>;
  /** The timeframe each mini-chart slot shows. */
  miniTimeframes: Timeframe[];
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
  setMiniTimeframe: (slot: number, timeframe: Timeframe) => void;
  setScanner: (
    scannerId: ScannerTierId,
    payload: { label: string; rows: ScannerRow[]; config: ScannerConfig; running: boolean },
  ) => void;
  setScannerTiers: (payload: {
    note: string | null;
    scanCodes: Array<{ code: string; label: string }>;
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

  scanners: emptyScanners(),
  miniTimeframes: loadMiniTimeframes(),
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

  setMiniTimeframe: (slot, timeframe) => {
    const next = [...get().miniTimeframes];
    if (slot < 0 || slot >= next.length) return;
    next[slot] = timeframe;
    saveMiniTimeframes(next);
    set({ miniTimeframes: next });
  },

  setScanner: (scannerId, { label, rows, config, running }) => {
    // One row per symbol, first (best-ranked) occurrence wins. The table keys
    // its rows by symbol, and React's reconciliation of duplicate keys leaves
    // orphaned DOM rows that outlive their data — the panel filled with stale
    // copies when a scan once returned a symbol under two contracts. The
    // backend dedupes too; this makes the render safe against any feed.
    const seen = new Set<string>();
    const unique = rows.filter((row) => {
      if (seen.has(row.symbol)) return false;
      seen.add(row.symbol);
      return true;
    });
    set((state) => ({
      scanners: {
        ...state.scanners,
        [scannerId]: { label, rows: unique, config, running },
      },
    }));
  },

  setScannerTiers: ({ note, scanCodes }) => set({ scannerNote: note, scanCodes }),

  setQuote: (quote) => set({ quote }),

  setInfo: (info) => set({ info }),

  setApiUsage: (usage) => set({ apiUsage: usage }),

  setRegime: ({ regime, running, error }) =>
    set({ regime, regimeRunning: running, regimeError: error }),

  setTheme: (theme) => set({ theme }),
}));
