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
  /**
   * LULD band width for the session, fixed by the previous close: 10 above
   * $3, 20 from $0.75–$3. Null when the fixed-cent band applies instead.
   */
  halt_band_pct: number | null;
  /** The fixed band below $0.75, in cents. Null when a percentage applies. */
  halt_band_cents: number | null;
  /** Days since the first daily bar; null once old enough not to matter. */
  listed_days: number | null;
  /** Epoch seconds of the next scheduled earnings report. */
  earnings_next: number | null;
  /** IBKR shortable magnitude: >2.5 easy, 1.5–2.5 locate, <1.5 none. */
  shortable: number | null;
  shortable_shares: number | null;
  /** Trading is halted right now. */
  halted: boolean;
  /** Halt transitions counted since the New York open. */
  halts_today: number;
  /** When the current or most recent halt began, on the server clock. */
  halt_halted_at: number | null;
  /** When the most recent halt ended. Null until one does, and at each open. */
  halt_resumed_at: number | null;
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
  /** Just enough of the dilution read to colour the always-visible chip.
   *  The full read is a REST call away — see `api.fundamentals`. */
  dilution: DilutionSummary | null;
  generated_at: number;
}

/** How much supply can hit the tape, and whether they need to sell it. */
export type DilutionTone = 'clean' | 'watch' | 'heavy' | 'serial';

export interface DilutionSummary {
  tone: DilutionTone;
  /** Warrants outstanding over shares outstanding, as a fraction. */
  warrant_overhang: number | null;
  /** Exercise price. Whether the warrants are in the money is decided here,
   *  against the live price, rather than on a server that would have to
   *  recompute the whole read every tick to answer it. */
  warrant_strike: number | null;
  runway_months: number | null;
  /** The sentences behind the tone — a grade you can check. */
  reasons: string[];
}

/** A figure from an SEC filing, with the period end it was reported for. */
export interface DatedValue {
  value: number;
  /** ISO date of the period end, not of the filing. */
  as_of: string;
  form: string;
  stale_days: number;
}

export interface DilutionRead extends Omit<DilutionSummary, 'warrant_strike'> {
  /** Overrides the summary's plain number: the full read ships every figure
   *  with the period it was reported for, the strike included. */
  warrant_strike: DatedValue | null;
  shares_outstanding: DatedValue | null;
  shares_issued: DatedValue | null;
  shares_authorized: DatedValue | null;
  warrants: DatedValue | null;
  preferred: DatedValue | null;
  convertible_notes: DatedValue | null;
  cash: DatedValue | null;
  annual_operating_cash_flow: DatedValue | null;
  public_float: DatedValue | null;
  /** Common plus warrants. Preferred is excluded on purpose — conversion
   *  ratios live in the charter, not the XBRL facts. */
  fully_diluted: number | null;
  fully_diluted_ratio: number | null;
  authorized_headroom: number | null;
  /** Public float under $75M: Form S-3 General Instruction I.B.6 caps sales
   *  at a third of float per rolling twelve months. Measured on the last
   *  10-K cover, so it describes the company before the run. */
  baby_shelf: boolean | null;
  baby_shelf_capacity: number | null;
  /** The same cap re-measured the way a sale would be — see `ShelfCapacity`. */
  live_shelf: ShelfCapacity | null;
  share_growth_12m: number | null;
  offerings_12m: number;
  delinquent: boolean;
  /** 8-K item 3.01 — the company was told it fails a listing rule. */
  listing_deficiency: boolean;
  /** A Form 25 was filed. Alone this is weak: a large issuer files one to
   *  remove a matured note. */
  delisting_filed: boolean;
}

/**
 * The baby-shelf ceiling, re-measured the way an actual sale would be.
 *
 * Public float is re-measured on the date of every takedown against a price
 * from a 60-day look-back, so a run raises the ceiling it is running into —
 * and past $75M of float the cap stops applying at all.
 */
export interface ShelfCapacity {
  /** The 60-day high the measurement runs against. */
  price: number;
  /** Float shares at that price. */
  public_float: number;
  /** The one-third limit still binds. */
  capped: boolean;
  /** Dollars sellable in a rolling twelve months; null once uncapped. */
  capacity: number | null;
  /** Live float over the float on the last cover page. */
  multiple: number | null;
}

/** What a headline does to the tape. */
export type Catalyst = 'supply' | 'distress' | 'upside' | 'none';

export interface Headline {
  article_id: string;
  provider: string;
  /** Epoch seconds. */
  time: number;
  headline: string;
  catalyst: Catalyst;
  /** Duplicate bulletins and continuations folded into this row. */
  related: string[];
  /** Set only by sources that publish one — Benzinga does, the wire does not. */
  url: string;
  /** How many companies the story is about. A press release names one. */
  symbol_count: number;
  /** True when the story is about a basket rather than about this company. */
  roundup: boolean;
}

export interface NewsResponse {
  symbol: string;
  /** The feeds behind the panel. Benzinga is here with no TWS running. */
  providers: Array<{ code: string; name: string }>;
  headlines: Headline[];
}

export interface ArticleResponse {
  provider: string;
  article_id: string;
  /** Plain text. The wire sends HTML; it is converted server-side so no
   *  provider markup ever reaches the DOM. */
  paragraphs: string[];
}

/** A live headline, pushed as it arrives on IBKR's generic tick 292. */
export interface NewsMessage {
  type: 'news';
  symbol: string;
  headline: Headline;
}

/** Why a filing is on screen. */
export type FilingKind = 'dilution' | 'distress' | 'periodic' | 'ownership' | 'routine';

export interface FilingRow {
  form: string;
  kind: FilingKind;
  /** What the form means at the tape, not what the SEC calls it. */
  note: string;
  /** ISO date. */
  filed: string;
  /** Epoch seconds EDGAR accepted it, or null on older rows with no zone. */
  accepted: number | null;
  accession: string;
  /** 8-K item numbers, e.g. ["3.01"]. */
  items: string[];
  url: string;
}

export interface FilingsResponse {
  symbol: string;
  available: boolean;
  /** Set only when EDGAR itself is the problem — a rejected User-Agent, say —
   *  so an empty panel never claims the company files nothing. */
  note: string | null;
  filings: FilingRow[];
}

/** A dilution or distress filing that landed while the symbol was open. */
export interface FilingMessage {
  type: 'filing';
  symbol: string;
  filing: FilingRow;
}

export interface CompanyProfile {
  cik: number;
  name: string;
  sic: string;
  sic_description: string;
  exchanges: string[];
  website: string;
  state_of_incorporation: string;
  fiscal_year_end: string;
}

/**
 * TradingView's ratios and statements.
 *
 * The slow half of the panel. These ride the same row the info strip already
 * fetches, so they cost nothing — which is the only reason they are here.
 * None of them decides whether a trade is possible.
 */
export interface BusinessStats {
  industry: string;
  country: string;
  employees: number | null;
  price_earnings: number | null;
  eps_ttm: number | null;
  revenue_ttm: number | null;
  gross_margin: number | null;
  operating_margin: number | null;
  net_income: number | null;
  total_debt: number | null;
  total_cash: number | null;
  free_cash_flow: number | null;
  ebitda: number | null;
  debt_to_equity: number | null;
  current_ratio: number | null;
  enterprise_value: number | null;
  return_on_equity: number | null;
  price_to_book: number | null;
  price_to_sales: number | null;
  beta: number | null;
  perf_ytd: number | null;
  /** Epoch seconds of the next scheduled report. */
  earnings_next: number | null;
}

export interface FundamentalsResponse {
  symbol: string;
  /** False when EDGAR is switched off in settings. */
  available: boolean;
  /** Set only when EDGAR itself is the problem, never when the company
   *  simply has nothing on file. */
  note: string | null;
  dilution: DilutionRead | null;
  profile: CompanyProfile | null;
  business: BusinessStats | null;
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
  /** Trades per minute, IBKR's `tradeRateAbove`. */
  above_trade_rate: number | null;
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

export interface WatchlistRow {
  symbol: string;
  /** The company name. Empty when the screener does not know the symbol. */
  name: string;
  close: number | null;
  change: number | null;
  volume: number | null;
  rvol: number | null;
  market_cap: number | null;
  premarket_change: number | null;
  /** Epoch seconds of the next scheduled report. */
  next_earnings: number | null;
}

/** The whole list, every time — the server never sends a diff. */
export interface WatchlistMessage {
  type: 'watchlist';
  symbols: string[];
  rows: WatchlistRow[];
  note: string | null;
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
  | WatchlistMessage
  | NewsMessage
  | FilingMessage
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
      above_trade_rate?: Clearable;
      market_cap_above?: Clearable;
      market_cap_below?: Clearable;
      change_perc_above?: Clearable;
    }
  | { action: 'scanner.stop'; scanner_id: ScannerTierId }
  | {
      /** Which indicators are on, for one timeframe. The server keeps the deltas. */
      action: 'indicators.visibility';
      timeframe: Timeframe;
      visible: Record<string, boolean>;
    }
  | { action: 'watchlist.add'; symbol: string }
  | { action: 'watchlist.remove'; symbol: string }
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
  /** Indicator toggles that differ from the config, keyed by timeframe. */
  indicators: Record<string, Record<string, boolean>>;
}

export type FinancialPeriodKind = 'annual' | 'quarterly';

export interface FinancialPeriod {
  /** "FY2025" or "FY2026 Q1" — a convention. */
  key: string;
  /** The exact close. This is the fact; the label is the convention. */
  end: string;
  fiscal_year: number;
}

export interface FinancialLine {
  key: string;
  label: string;
  unit: string;
  /** Which XBRL tags answered, in the order they were consulted. */
  concepts: string[];
  /** One entry per period, aligned with `periods`; null where nothing was filed. */
  values: Array<number | null>;
}

export interface FinancialStatement {
  key: string;
  label: string;
  lines: FinancialLine[];
}

export interface FinancialsResponse {
  symbol: string;
  available: boolean;
  note: string | null;
  /** Always USD once converted; the filer's own currency is `native_currency`. */
  currency: string;
  native_currency: string;
  converted: boolean;
  /** Periods whose FX rate could not be fetched, so were left unconverted. */
  unconverted_periods?: string[];
  symbol_prefix: string;
  period: FinancialPeriodKind;
  periods: FinancialPeriod[];
  statements: FinancialStatement[];
}

export interface MetricRow {
  key: string;
  label: string;
  /** "percent" | "ratio" | "multiple" | "money" — how the cell is read. */
  unit: string;
  values: Array<number | null>;
}

export interface MetricGroup {
  label: string;
  metrics: MetricRow[];
}

export interface ValuationMultiple {
  key: string;
  label: string;
  /** Null where the ratio was refused, not zero. */
  value: number | null;
}

export interface Valuation {
  market_cap: number | null;
  enterprise_value: number | null;
  basis: string;
  /** "filings" when we computed it, else who we borrowed it from. */
  source: string;
  /** Why there are no multiples, when there are none. */
  note: string | null;
  multiples: ValuationMultiple[];
}

export interface MetricsResponse {
  symbol: string;
  available: boolean;
  currency: string;
  symbol_prefix: string;
  period: FinancialPeriodKind;
  periods: FinancialPeriod[];
  groups: MetricGroup[];
  valuation: Valuation | null;
}

export interface SwingScreen {
  id: string;
  label: string;
  note: string;
}

export interface SwingConfig {
  min_market_cap: number;
  min_avg_volume: number;
  rows: number;
}

export interface SwingRow {
  symbol: string;
  name: string;
  sector: string;
  close: number | null;
  change: number | null;
  rvol: number | null;
  market_cap: number | null;
  avg_volume: number | null;
  perf_week: number | null;
  perf_month: number | null;
  perf_quarter: number | null;
  adr: number | null;
  /** Negative below the 52-week high; zero at it. */
  off_high: number | null;
  distance_to_sma50: number | null;
  /** Epoch seconds of the next scheduled report. */
  next_earnings: number | null;
}

export interface SwingScreensResponse {
  screens: SwingScreen[];
  config: SwingConfig;
  note: string | null;
}

export interface SwingRowsResponse {
  screen_id: string;
  rows: SwingRow[];
  config: SwingConfig;
  note: string | null;
}

export interface WatchlistResponse {
  symbols: string[];
  rows: WatchlistRow[];
  note: string | null;
}

export type InsiderIntent = 'buy' | 'sell' | 'compensation' | 'other';

export interface InsiderTrade {
  filed: string;
  traded: string;
  owner: string;
  role: string;
  /** The Form 4 Table 1 code: P, S, A, M, F… */
  code: string;
  intent: InsiderIntent;
  note: string;
  shares: number | null;
  price: number | null;
  shares_after: number | null;
  acquired: boolean;
  /** Sold under a 10b5-1 plan adopted months earlier. */
  planned: boolean;
  value: number | null;
  url: string;
}

export interface InsiderTotal {
  count: number;
  shares: number;
  value: number;
  people: number;
}

export interface OwnershipSummary {
  window_days: number;
  buys: InsiderTotal;
  discretionary_sells: InsiderTotal;
  planned_sells: InsiderTotal;
  compensation: InsiderTotal;
  net_value: number;
  verdict: string;
}

export interface OwnershipResponse {
  symbol: string;
  available: boolean;
  note: string | null;
  summary: OwnershipSummary | null;
  trades: InsiderTrade[];
}

export interface PeerRow {
  symbol: string;
  name: string;
  industry: string;
  market_cap: number | null;
  price_earnings: number | null;
  price_sales: number | null;
  price_book: number | null;
  gross_margin: number | null;
  operating_margin: number | null;
  return_on_equity: number | null;
  debt_to_equity: number | null;
  revenue: number | null;
  perf_ytd: number | null;
  /** Epoch seconds of the next scheduled report. */
  next_earnings: number | null;
}

export interface PeerRank {
  key: string;
  label: string;
  unit: string;
  value: number | null;
  median: number | null;
  /** 1 is best on this measure. Null when the company does not report it. */
  position: number | null;
  total: number;
}

export interface PeersResponse {
  symbol: string;
  available: boolean;
  industry: string;
  rows: PeerRow[];
  ranks: PeerRank[];
  note: string | null;
}

export interface ConceptRow {
  key: string;
  label: string;
  concept: string;
  taxonomy: string;
  /** The unit as filed — not normalised, because the meaning is unknown. */
  unit: string;
  values: Array<number | null>;
}

export interface ConceptsResponse {
  symbol: string;
  available: boolean;
  currency: string;
  query: string;
  total: number;
  periods: FinancialPeriod[];
  rows: ConceptRow[];
}

export interface ScannerTiersResponse {
  scan_codes: Array<{ code: string; label: string }>;
  tiers: Array<{ id: ScannerTierId; label: string }>;
  note: string | null;
}
