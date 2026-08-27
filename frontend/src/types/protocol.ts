/**
 * The wire protocol, mirroring `backend/app/domain/protocol.py`.
 *
 * Bars use short keys and series use `[time, value]` pairs because a snapshot
 * carries thousands of both; the compact shape roughly halves the payload.
 */

export const TIMEFRAMES = ['10s', '1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

export type DataSource = 'ibkr' | 'alpaca' | 'none';
export type Pane = 'price' | 'volume' | 'macd';
export type LineStyleName = 'solid' | 'dashed' | 'dotted';

export interface WireBar {
  /** Epoch seconds at which the period opened. */
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  /** Trade count. */
  n: number;
  /** Present and 1 only for extended-hours periods. */
  x?: number;
}

export type SeriesPoint = [time: number, value: number];
export type SeriesMap = Record<string, SeriesPoint[]>;

export interface SnapshotMessage {
  type: 'snapshot';
  symbol: string;
  timeframe: Timeframe;
  bars: WireBar[];
  series: SeriesMap;
  source: DataSource;
  delayed: boolean;
  generated_at: number;
}

export interface BarMessage {
  type: 'bar';
  symbol: string;
  timeframe: Timeframe;
  bar: WireBar;
  /** Each indicator's current value. */
  series: Record<string, number>;
}

export interface StatusMessage {
  type: 'status';
  source: DataSource;
  delayed: boolean;
  ibkr_connected: boolean;
  alpaca_available: boolean;
  message: string | null;
}

/** Top-of-book quote. Sizes are in shares. */
export interface QuoteMessage {
  type: 'quote';
  symbol: string;
  bid: number;
  ask: number;
  bs: number;
  as: number;
  t: number;
}

/** One upstream's request-budget window. */
export interface ApiWindow {
  used: number;
  limit: number;
  window_s: number;
}

/** Request-budget usage for the toolbar meters. */
export interface ApiUsageMessage {
  type: 'api';
  alpaca: ApiWindow;
  ibkr: ApiWindow;
}

/** Reference numbers and session-derived stats for the info strip. */
export interface InfoMessage {
  type: 'info';
  symbol: string;
  float_shares: number | null;
  market_cap: number | null;
  shares_outstanding: number | null;
  avg_vol_10d: number | null;
  /** Split-adjusted all-time high since listing, from TradingView. */
  all_time_high: number | null;
  description: string;
  exchange: string;
  sector: string;
  day_volume: number;
  pm_volume: number;
  prev_close: number | null;
  rel_vol: number | null;
  float_rotation: number | null;
  pm_float_rotation: number | null;
  halt_ref: number | null;
  halt_up: number | null;
  halt_down: number | null;
  halt_active: boolean;
  /** Days since the first daily bar; null once old enough not to matter. */
  listed_days: number | null;
  /** IBKR shortable magnitude: >2.5 easy, 1.5–2.5 locate, <1.5 none. */
  shortable: number | null;
  shortable_shares: number | null;
  /** Trading is halted right now. */
  halted: boolean;
  /** Halt transitions counted since the New York open. */
  halts_today: number;
  /** Old shares per new share of the latest reverse split, e.g. 10 = 1:10. */
  reverse_split_ratio: number | null;
  reverse_split_days: number | null;
  /** Yahoo's float, the second opinion against float_shares. */
  yahoo_float: number | null;
  /** Share of the current leg given back, 0–100. Null with no active leg. */
  pullback_depth_pct: number | null;
  /** Mean pullback-bar volume over mean rally-bar volume. */
  pullback_vol_ratio: number | null;
  /** Minutes since the leg high. */
  pullback_bars: number | null;
  /** The leg itself as a percentage of its trough. */
  pullback_leg_pct: number | null;
  generated_at: number;
}

// The four market-cap-tiered scanners, mirroring
// backend/app/domain/scanner.py's SCANNER_TIERS. Labels are duplicated here
// (not fetched) so a tier's header renders correctly before the first WS
// `scanner` frame lands — the same tolerance for small, stable literal
// duplication already exists between the backend's SCAN_CODES and its
// e2e-fixture copy.
export const SCANNER_TIER_IDS = ['small_cap', 'mid_cap', 'large_cap', 'mega_cap'] as const;
export type ScannerTierId = (typeof SCANNER_TIER_IDS)[number];
export const SCANNER_TIER_LABELS: Record<ScannerTierId, string> = {
  small_cap: 'Small Cap',
  mid_cap: 'Mid Cap',
  large_cap: 'Large Cap',
  mega_cap: 'Mega Cap',
};

export interface ScannerRow {
  rank: number;
  symbol: string;
  exchange: string;
  price: number | null;
  pct_change: number | null;
  volume: number | null;
  trades_1m: number;
  trades_5m: number;
  dollar_vol_1m: number;
  dollar_vol_5m: number;
  trades_day: number | null;
  dollar_vol_day: number | null;
  /** Places gained over the rank-velocity window; positive is upward. */
  rank_delta: number | null;
  /** Present now, absent a window ago. */
  entered: boolean;
  /** Free float, shares. From TradingView; null until its cache warms. */
  float_shares: number | null;
  /** Market capitalisation, dollars. */
  market_cap: number | null;
}

export interface ScannerConfig {
  scan_code: string;
  above_price: number | null;
  below_price: number | null;
  above_volume: number | null;
  market_cap_above: number | null;
  market_cap_below: number | null;
  change_perc_above: number | null;
  number_of_rows: number;
}

export interface ScannerMessage {
  type: 'scanner';
  scanner_id: ScannerTierId;
  label: string;
  rows: ScannerRow[];
  config: ScannerConfig;
  running: boolean;
}

export interface MarketRegime {
  up_50_count: number;
  up_100_count: number;
}

export interface RegimeMessage {
  type: 'regime';
  regime: MarketRegime;
  running: boolean;
  error: string | null;
}

export interface ErrorMessage {
  type: 'error';
  code: string;
  message: string;
}

export interface PongMessage {
  type: 'pong';
}

export type ServerMessage =
  | SnapshotMessage
  | BarMessage
  | StatusMessage
  | QuoteMessage
  | InfoMessage
  | ApiUsageMessage
  | ScannerMessage
  | RegimeMessage
  | ErrorMessage
  | PongMessage;

// ── client → server ────────────────────────────────────────────────────

/** A numeric filter: set it, omit it, or send "clear" to switch it off. */
export type Clearable = number | 'clear';

export type ClientCommand =
  | {
      action: 'subscribe';
      symbol: string;
      timeframe: Timeframe;
      /** Extra timeframes on the same symbol, for the mini charts. */
      extra_timeframes?: Timeframe[];
    }
  | { action: 'unsubscribe' }
  | {
      action: 'scanner.configure';
      scanner_id: ScannerTierId;
      scan_code?: string;
      above_price?: Clearable;
      below_price?: Clearable;
      above_volume?: number;
      market_cap_above?: Clearable;
      market_cap_below?: Clearable;
      change_perc_above?: Clearable;
    }
  | { action: 'scanner.stop'; scanner_id: ScannerTierId }
  | { action: 'ping' };

// ── REST payloads ──────────────────────────────────────────────────────

export interface IndicatorSpec {
  id: string;
  type:
    | 'ema'
    | 'sma'
    | 'vwap'
    | 'macd'
    | 'premarket'
    | 'session_bound'
    | 'session_level'
    | 'daily_level'
    | 'volume';
  label: string;
  color: string;
  color_dark: string;
  pane: Pane;
  /** Computed and streamed for the readout strip, but never painted. */
  readout_only: boolean;
  line_width: number;
  line_style: LineStyleName;
  price_line: boolean;
  last_value: boolean;
  group: string;
  /** Per-timeframe enablement, with an optional display-label override —
   *  the 10s chart shows "EMA 54" for the line whose id stays `ema9`. */
  timeframes: Record<string, { enabled: boolean; label?: string }>;
}

/** The label an indicator should carry on the given timeframe. */
export function indicatorLabel(spec: IndicatorSpec, timeframe: string): string {
  return spec.timeframes[timeframe]?.label ?? spec.label;
}

export interface TimeframeInfo {
  value: Timeframe;
  label: string;
  intraday: boolean;
}

export interface SessionInfo {
  symbol: string;
  timeframe: Timeframe;
  default_symbol: string;
  default_timeframe: Timeframe;
}

export interface ScannerTiersResponse {
  scan_codes: Array<{ code: string; label: string }>;
  tiers: Array<{ id: ScannerTierId; label: string }>;
  note: string | null;
}
