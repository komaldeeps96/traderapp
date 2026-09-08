/**
 * Application state.
 *
 * Deliberately small: bars live in the ChartEngine, not here. This store holds
 * only what React renders — the readout, the toggles, the scanner — so a bar
 * update once a second re-renders a handful of numbers rather than a chart.
 */

import { create } from "zustand";

import { sendCommand } from "@/lib/commands";
import { clampDockWidth, type DockTabId } from "@/lib/dock";
import type { MainTabId } from "@/lib/mainTabs";
import type { ScannerTabId } from "@/lib/scannerTabs";
import {
  loadDockTab,
  loadMainTab,
  loadScannerTab,
  loadDockWidth,
  loadMiniTimeframes,
  loadNewsAi,
  loadTapeFilters,
  loadVisibility,
  saveDockTab,
  saveMainTab,
  saveScannerTab,
  saveDockWidth,
  saveMiniTimeframes,
  saveNewsAi,
  saveTapeFilters,
  visibilityOverrides,
  type Theme,
} from "@/lib/storage";
import { mergePrints, type TapeFilters } from "@/lib/tape";
import type {
  ApiUsageMessage,
  DataSource,
  FilingRow,
  Headline,
  IndicatorSpec,
  InfoMessage,
  MarketRegime,
  OrderRow,
  PositionRow,
  QuoteMessage,
  ScannerConfig,
  ScannerRow,
  ScannerTierId,
  TapeMessage,
  TapePrint,
  Timeframe,
  TradingState,
  WatchlistRow,
  WireBar,
} from "@/types/protocol";
import { SCANNER_TIER_IDS, SCANNER_TIER_LABELS } from "@/types/protocol";

export interface ScannerTierState {
  label: string;
  rows: ScannerRow[];
  config: ScannerConfig | null;
  running: boolean;
}

function emptyScanners(): Record<ScannerTierId, ScannerTierState> {
  const scanners = {} as Record<ScannerTierId, ScannerTierState>;
  for (const id of SCANNER_TIER_IDS) {
    scanners[id] = {
      label: SCANNER_TIER_LABELS[id],
      rows: [],
      config: null,
      running: false,
    };
  }
  return scanners;
}

export type ChartStatus = "idle" | "loading" | "ready" | "error";

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

  // time and sales — every print on the open symbol, newest first, and how
  // the window is filtered. The prints are the one high-rate list this store
  // holds; nothing else re-renders off them.
  tape: TapePrint[];
  tapeFilters: TapeFilters;

  // upstream request budgets
  apiUsage: ApiUsageMessage | null;

  // indicators
  specs: IndicatorSpec[];
  visibility: Record<string, boolean>;
  /** Per-timeframe deltas from the config defaults, as the server has them. */
  indicatorOverrides: Record<string, Record<string, boolean>>;

  // scanner — one entry per market-cap tier, each independently filtered
  // and persisted (see ScannerPanel/backend ScannerService).
  scanners: Record<ScannerTierId, ScannerTierState>;
  /** The timeframe each mini-chart slot shows. */
  miniTimeframes: Timeframe[];

  // watchlist — a flat list of symbols, in the order they were added, and one
  // quote row per name. Both come from the server, which owns the list; the
  // client never edits its own copy, so two windows cannot disagree.
  watchlist: string[];
  watchlistRows: WatchlistRow[];
  watchlistNote: string | null;

  // the right-hand dock — which tab is open and how wide the rail is
  dockTab: DockTabId;
  mainTab: MainTabId;
  scannerTab: ScannerTabId;
  dockWidth: number;

  // news: the backfill and every live headline merged into one list, held
  // here rather than in the panel so a headline arriving over the WebSocket
  // reaches it whether or not the tab is currently mounted.
  news: Headline[];
  newsSymbol: string;
  newsStatus: "idle" | "loading" | "ready" | "error";
  newsProviders: Array<{ code: string; name: string }>;
  /** Whether the panel's top half asks Claude to read the day. A user
   *  preference, not a server one — with it off nothing is requested and no
   *  process is spawned. */
  newsAi: boolean;

  /** Live pushes that arrived while a tab was not the open one, per tab.
   *  Cleared when that tab is selected. */
  dockAlerts: Partial<Record<DockTabId, number>>;
  /** Dilution and distress filings pushed mid-session, newest first. */
  liveFilings: FilingRow[];

  scannerNote: string | null;
  scanCodes: Array<{ code: string; label: string }>;

  // order entry — the strip under the chart. Positions and working orders are
  // IBKR's own numbers, broadcast whole on every change like the watchlist, so
  // no window can disagree about what is actually held.
  trading: TradingState | null;
  positions: PositionRow[];
  workingOrders: OrderRow[];
  /** The last order this terminal placed, for the strip's acknowledgement. */
  lastOrder: OrderRow | null;

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
  chartReady: (payload: {
    symbol: string;
    timeframe: Timeframe;
    barCount: number;
    live: Readout | null;
  }) => void;
  setLive: (live: Readout, barCount: number) => void;
  setHovered: (hovered: Readout | null) => void;
  setError: (message: string) => void;
  toggleIndicator: (id: string) => void;
  setAllIndicators: (ids: string[], visible: boolean) => void;
  applyVisibility: (visibility: Record<string, boolean>) => void;
  setIndicatorOverrides: (
    overrides: Record<string, Record<string, boolean>>,
  ) => void;
  setMiniTimeframe: (slot: number, timeframe: Timeframe) => void;
  setDockTab: (tab: DockTabId) => void;
  setMainTab: (tab: MainTabId) => void;
  setScannerTab: (tab: ScannerTabId) => void;
  setDockWidth: (width: number) => void;
  setNews: (
    symbol: string,
    headlines: Headline[],
    providers: Array<{ code: string; name: string }>,
  ) => void;
  setNewsStatus: (status: "idle" | "loading" | "ready" | "error") => void;
  setNewsAi: (enabled: boolean) => void;
  addHeadline: (symbol: string, headline: Headline) => void;
  addFiling: (symbol: string, filing: FilingRow) => void;
  setScanner: (
    scannerId: ScannerTierId,
    payload: {
      label: string;
      rows: ScannerRow[];
      config: ScannerConfig;
      running: boolean;
    },
  ) => void;
  setWatchlist: (payload: {
    symbols: string[];
    rows: WatchlistRow[];
    note: string | null;
  }) => void;
  addToWatchlist: (symbol: string) => void;
  removeFromWatchlist: (symbol: string) => void;
  setScannerTiers: (payload: {
    note: string | null;
    scanCodes: Array<{ code: string; label: string }>;
  }) => void;
  setQuote: (quote: QuoteMessage) => void;
  applyTape: (message: TapeMessage) => void;
  setTapeFilters: (patch: Partial<TapeFilters>) => void;
  setTrading: (payload: {
    state: TradingState;
    positions: PositionRow[];
    orders: OrderRow[];
  }) => void;
  setOrder: (order: OrderRow) => void;
  buy: (symbol: string, dollars: number) => void;
  sell: (symbol: string, fraction: number) => void;
  cancelAllOrders: () => void;
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
  source: "none",
  delayed: false,
  ibkrConnected: false,
  alpacaAvailable: false,
  sourceNote: null,

  symbol: "",
  timeframe: "10s",
  status: "idle",
  error: null,
  barCount: 0,
  live: null,
  hovered: null,
  snapshotEpoch: 0,

  quote: null,
  info: null,
  apiUsage: null,

  tape: [],
  tapeFilters: loadTapeFilters(),

  specs: [],
  visibility: {},
  indicatorOverrides: {},

  scanners: emptyScanners(),
  watchlist: [],
  watchlistRows: [],
  watchlistNote: null,
  miniTimeframes: loadMiniTimeframes(),
  dockTab: loadDockTab(),
  mainTab: loadMainTab(),
  scannerTab: loadScannerTab(),
  dockWidth: loadDockWidth(),

  news: [],
  newsSymbol: "",
  newsStatus: "idle",
  newsProviders: [],
  newsAi: loadNewsAi(),
  dockAlerts: {},
  liveFilings: [],
  scannerNote: null,
  scanCodes: [],

  trading: null,
  positions: [],
  workingOrders: [],
  lastOrder: null,

  regimeRunning: false,
  regimeError: null,
  regime: null,

  theme: "dark",

  setConnected: (connected) => set({ connected }),

  setTrading: ({ state, positions, orders }) =>
    set({ trading: state, positions, workingOrders: orders }),

  setOrder: (order) => set({ lastOrder: order }),

  // Sent, never applied locally. What a button press means is decided on the
  // server against the freshest quote and IBKR's own position — echoing an
  // optimistic fill here would draw a position that does not exist. The
  // `trading` broadcast that follows is what the strip renders.
  buy: (symbol, dollars) =>
    sendCommand({ action: "trade.buy", symbol, dollars }),
  sell: (symbol, fraction) =>
    sendCommand({ action: "trade.sell", symbol, fraction }),
  cancelAllOrders: () => sendCommand({ action: "trade.cancel_all" }),

  setSourceStatus: ({
    source,
    delayed,
    ibkrConnected,
    alpacaAvailable,
    note,
  }) =>
    set({ source, delayed, ibkrConnected, alpacaAvailable, sourceNote: note }),

  setIndicatorOverrides: (indicatorOverrides) => {
    const { specs, timeframe } = get();
    set({
      indicatorOverrides,
      visibility: loadVisibility(
        specs,
        timeframe,
        indicatorOverrides[timeframe],
      ),
    });
  },

  setSpecs: (specs) => {
    const { timeframe, indicatorOverrides } = get();
    set({
      specs,
      visibility: loadVisibility(
        specs,
        timeframe,
        indicatorOverrides[timeframe],
      ),
    });
  },

  requestChart: (symbol, timeframe) => {
    const state = get();
    const changedTimeframe = state.timeframe !== timeframe;
    const changedSymbol = state.symbol !== symbol;
    set({
      symbol,
      timeframe,
      status: "loading",
      error: null,
      hovered: null,
      // A stale readout under a new symbol reads as live data for the wrong
      // instrument, so it is cleared immediately rather than on arrival.
      live: null,
      barCount: 0,
      quote: changedSymbol ? null : state.quote,
      info: changedSymbol ? null : state.info,
      // The previous company's prints must never sit under a new ticker: a
      // tape row is a fact about one instrument and reads as live either way.
      // The server sends a `reset` frame on subscribe too; this is what
      // clears the window in the gap before it lands.
      tape: changedSymbol ? [] : state.tape,
      // The previous company's headlines and filing alerts must not sit under
      // the new ticker while its own load.
      news: changedSymbol ? [] : state.news,
      liveFilings: changedSymbol ? [] : state.liveFilings,
      dockAlerts: changedSymbol ? {} : state.dockAlerts,
      visibility: changedTimeframe
        ? loadVisibility(
            state.specs,
            timeframe,
            state.indicatorOverrides[timeframe],
          )
        : state.visibility,
    });
  },

  chartReady: ({ symbol, timeframe, barCount, live }) =>
    set((state) => ({
      symbol,
      timeframe,
      barCount,
      live,
      status: "ready",
      error: null,
      snapshotEpoch: state.snapshotEpoch + 1,
    })),

  setLive: (live, barCount) => set({ live, barCount }),

  setHovered: (hovered) => set({ hovered }),

  setError: (message) => set({ status: "error", error: message }),

  toggleIndicator: (id) => {
    const { visibility } = get();
    get().applyVisibility({ ...visibility, [id]: !visibility[id] });
  },

  setAllIndicators: (ids, visible) => {
    const next = { ...get().visibility };
    for (const id of ids) next[id] = visible;
    get().applyVisibility(next);
  },

  /**
   * Show this, and remember it on the server.
   *
   * The whole picture goes out; the server stores what differs from the
   * config. Keeping the same deltas here means a timeframe switch and back
   * reads the toggles from memory rather than waiting on a round trip.
   */
  applyVisibility: (next) => {
    const { specs, timeframe, indicatorOverrides } = get();
    const overrides = visibilityOverrides(specs, timeframe, next);
    sendCommand({ action: "indicators.visibility", timeframe, visible: next });
    set({
      visibility: next,
      indicatorOverrides: { ...indicatorOverrides, [timeframe]: overrides },
    });
  },

  setMiniTimeframe: (slot, timeframe) => {
    const next = [...get().miniTimeframes];
    if (slot < 0 || slot >= next.length) return;
    next[slot] = timeframe;
    saveMiniTimeframes(next);
    set({ miniTimeframes: next });
  },

  setNews: (newsSymbol, news, newsProviders) =>
    set({ newsSymbol, news, newsProviders }),

  setNewsStatus: (newsStatus) => set({ newsStatus }),

  setNewsAi: (newsAi) => {
    saveNewsAi(newsAi);
    set({ newsAi });
  },

  addHeadline: (symbol, headline) => {
    // A headline for a symbol the user has navigated away from is dropped,
    // exactly as a stale snapshot is.
    const state = get();
    if (symbol !== state.symbol) return;
    // The server only pushes genuinely new stories — a bulletin that
    // collapsed into one already held never reaches here — but the id check
    // keeps a reconnect replay from doubling a row.
    if (state.news.some((row) => row.article_id === headline.article_id))
      return;
    // A roundup goes in the list but never lights the badge. It names a dozen
    // companies and this one is merely among them, so a badge for it is an
    // interruption about somebody else's stock — and a badge that is usually
    // wrong is a badge nobody looks at.
    const badge =
      state.dockTab === "news" || headline.roundup
        ? state.dockAlerts
        : { ...state.dockAlerts, news: (state.dockAlerts.news ?? 0) + 1 };
    set({ news: [headline, ...state.news], dockAlerts: badge });
  },

  addFiling: (symbol, filing) => {
    const state = get();
    if (symbol !== state.symbol) return;
    if (state.liveFilings.some((row) => row.accession === filing.accession))
      return;
    set({
      liveFilings: [filing, ...state.liveFilings],
      dockAlerts:
        state.dockTab === "filings"
          ? state.dockAlerts
          : {
              ...state.dockAlerts,
              filings: (state.dockAlerts.filings ?? 0) + 1,
            },
    });
  },

  setScannerTab: (scannerTab) => {
    saveScannerTab(scannerTab);
    set({ scannerTab });
  },

  setMainTab: (mainTab) => {
    saveMainTab(mainTab);
    set({ mainTab });
  },

  setDockTab: (dockTab) => {
    saveDockTab(dockTab);
    // Opening a tab is what marks its alerts read.
    set((state) => ({
      dockTab,
      dockAlerts: { ...state.dockAlerts, [dockTab]: 0 },
    }));
  },

  setDockWidth: (width) => {
    // Clamped here rather than at the drag handler so a width arriving from
    // anywhere — a restored session, a test — lands inside the bounds.
    const dockWidth = clampDockWidth(width);
    saveDockWidth(dockWidth);
    set({ dockWidth });
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

  setWatchlist: ({ symbols, rows, note }) =>
    set({ watchlist: symbols, watchlistRows: rows, watchlistNote: note }),

  // Both edits are sent and not applied: the list lives on the server, and the
  // broadcast that comes back is what every window renders. Echoing locally
  // would show a name that a failed write never actually added.
  addToWatchlist: (symbol) => {
    const wanted = symbol.trim().toUpperCase();
    if (wanted) sendCommand({ action: "watchlist.add", symbol: wanted });
  },

  removeFromWatchlist: (symbol) => {
    sendCommand({
      action: "watchlist.remove",
      symbol: symbol.trim().toUpperCase(),
    });
  },

  setScannerTiers: ({ note, scanCodes }) =>
    set({ scannerNote: note, scanCodes }),

  setQuote: (quote) => set({ quote }),

  // Prints for a symbol the user has navigated away from are dropped, exactly
  // as a stale snapshot is. `mergePrints` owns the dedupe and the cap.
  applyTape: ({ symbol, prints, reset }) => {
    const state = get();
    if (symbol !== state.symbol) return;
    const merged = mergePrints(state.tape, prints, reset);
    if (merged !== state.tape) set({ tape: merged });
  },

  setTapeFilters: (patch) => {
    const tapeFilters = { ...get().tapeFilters, ...patch };
    saveTapeFilters(tapeFilters);
    set({ tapeFilters });
  },

  setInfo: (info) => set({ info }),

  setApiUsage: (usage) => set({ apiUsage: usage }),

  setRegime: ({ regime, running, error }) =>
    set({ regime, regimeRunning: running, regimeError: error }),

  setTheme: (theme) => set({ theme }),
}));
