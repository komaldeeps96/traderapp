/**
 * Deterministic market data for the mocked browser suite.
 *
 * Shaped exactly like the backend's wire protocol so the frontend cannot tell
 * the difference. Everything derives from a fixed seed and a fixed session
 * date, so a screenshot taken today matches one taken next month.
 */

export interface WireBar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  n: number;
  x?: number;
}

export type SeriesPoint = [number, number];

export interface IndicatorSpec {
  id: string;
  type: string;
  label: string;
  color: string;
  color_dark: string;
  pane: 'price' | 'volume' | 'macd';
  readout_only?: boolean;
  line_width: number;
  line_style: 'solid' | 'dashed' | 'dotted';
  price_line: boolean;
  last_value: boolean;
  group: string;
  timeframes: Record<string, { enabled: boolean; label?: string }>;
}

const INTRADAY = {
  '10s': { enabled: true },
  '1m': { enabled: true },
  '5m': { enabled: true },
  '15m': { enabled: true },
  '30m': { enabled: true },
  '1h': { enabled: true },
  '4h': { enabled: true },
};

const ALL = { ...INTRADAY, '1d': { enabled: true }, '1w': { enabled: true } };

function line(
  id: string,
  label: string,
  group: string,
  color: string,
  colorDark: string,
  extra: Partial<IndicatorSpec> = {},
): IndicatorSpec {
  return {
    id,
    type: 'daily_level',
    label,
    color,
    color_dark: colorDark,
    pane: 'price',
    line_width: 1,
    line_style: 'solid',
    price_line: false,
    last_value: true,
    group,
    timeframes: INTRADAY,
    ...extra,
  };
}

/**
 * The levels that stack above a faded runner.
 *
 * The real config carries 28 key levels; the slice below carries eight, which
 * is enough for most assertions but never puts more than a band or two over
 * the last price. These exist so the "price buried under overhead supply"
 * case — the one that makes the panel unreadable — can be reproduced.
 */
export const OVERHEAD_LEVELS = [
  'prev_week_high',
  'prev_month_high',
  'prev_quarter_high',
  'prev_year_high',
  'high_13w',
  'high_26w',
] as const;

/** A representative slice of the real indicator config. */
export const INDICATORS: IndicatorSpec[] = [
  // The moving averages and VWAP carry no axis tag: they track price, so
  // their labels crowd the axis exactly where the levels that matter are
  // read. Their colours are in the sidebar. Matches `indicators.yaml`.
  line('ema9', 'EMA 9', 'moving_averages', '#2a78d6', '#3987e5', {
    type: 'ema',
    last_value: false,
    timeframes: { ...ALL, '10s': { enabled: true, label: 'EMA 54' } },
  }),
  line('ema20', 'EMA 20', 'moving_averages', '#eb6834', '#d95926', {
    type: 'ema',
    last_value: false,
    timeframes: { ...ALL, '10s': { enabled: true, label: 'EMA 120' } },
  }),
  line('ema45', 'EMA 45', 'moving_averages', '#1baf7a', '#199e70', {
    type: 'ema',
    last_value: false,
    timeframes: { ...INTRADAY, '10s': { enabled: true, label: 'EMA 270' } },
  }),
  line('ema100', 'EMA 100', 'moving_averages', '#788e0b', '#beda2f', {
    type: 'ema',
    last_value: false,
    timeframes: { ...INTRADAY, '10s': { enabled: true, label: 'EMA 600' } },
  }),
  line('vwap', 'VWAP', 'session', '#93126b', '#bc0b97', {
    type: 'vwap',
    last_value: false,
  }),
  // Readout-only: streamed for the strip, never painted. Matches the real
  // config's windowed RVOL.
  line('wrvol', 'Windowed RVOL', 'session', '#898781', '#898781', {
    type: 'daily_level',
    readout_only: true,
    last_value: false,
  }),
  line('pm_high', 'PM High', 'key_levels', '#52514e', '#c3c2b7', {
    type: 'premarket',
    line_width: 2,
    line_style: 'dotted',
  }),
  line('pm_low', 'PM Low', 'key_levels', '#52514e', '#c3c2b7', {
    type: 'premarket',
    line_width: 2,
    line_style: 'dotted',
  }),
  line('prev_day_close', 'Prev Day Close', 'key_levels', '#52514e', '#c3c2b7', {
    line_width: 2,
    line_style: 'dashed',
  }),
  line('prev_day_high', 'Prev Day High', 'key_levels', '#6d6b66', '#a8a69d', {
    line_style: 'dashed',
  }),
  line('prev_day_low', 'Prev Day Low', 'key_levels', '#6d6b66', '#a8a69d', {
    line_style: 'dashed',
  }),
  line('high_52w', '52W High', 'key_levels', '#898781', '#898781'),
  line('low_52w', '52W Low', 'key_levels', '#898781', '#898781'),
  line('d_sma20', '1D SMA 20', 'daily_ma', '#6d6b66', '#a8a69d'),
  {
    id: 'volume',
    type: 'volume',
    label: 'Volume',
    color: '#898781',
    color_dark: '#898781',
    pane: 'volume',
    line_width: 1,
    line_style: 'solid',
    price_line: false,
    last_value: false,
    group: 'panes',
    timeframes: ALL,
  },
  {
    id: 'macd',
    type: 'macd',
    label: 'MACD 12·26·9',
    color: '#2a78d6',
    color_dark: '#3987e5',
    pane: 'macd',
    line_width: 1,
    line_style: 'solid',
    price_line: false,
    last_value: false,
    group: 'panes',
    timeframes: { '1m': { enabled: true } },
  },
];

export const SCAN_CODES = [
  { code: 'TOP_TRADE_RATE', label: 'Top Trade Rate' },
  { code: 'TOP_PERC_GAIN', label: 'Top % Gainers' },
  { code: 'TOP_PERC_LOSE', label: 'Top % Losers' },
  { code: 'MOST_ACTIVE', label: 'Most Active' },
  { code: 'HOT_BY_VOLUME', label: 'Hot by Volume' },
];

// Mirrors backend/app/domain/scanner.py's SCANNER_TIERS.
export const SCANNER_TIERS = [
  { id: 'small_cap', label: 'Small Cap' },
  { id: 'mid_cap', label: 'Mid Cap' },
  { id: 'large_cap', label: 'Large Cap' },
  { id: 'mega_cap', label: 'Mega Cap' },
] as const;
export type ScannerTierId = (typeof SCANNER_TIERS)[number]['id'];

export const TIMEFRAMES = [
  { value: '10s', label: '10S', intraday: true },
  { value: '1m', label: '1M', intraday: true },
  { value: '5m', label: '5M', intraday: true },
  { value: '15m', label: '15M', intraday: true },
  { value: '30m', label: '30M', intraday: true },
  { value: '1h', label: '1H', intraday: true },
  { value: '4h', label: '4H', intraday: true },
  { value: '1d', label: '1D', intraday: false },
  { value: '1w', label: '1W', intraday: false },
];

/** Bar length in seconds for the fixture generator. */
export function stepFor(timeframe: string): number {
  switch (timeframe) {
    case '10s':
      return 10;
    case '5m':
      return 300;
    case '15m':
      return 900;
    case '30m':
      return 1800;
    case '1h':
      return 3600;
    case '4h':
      return 14_400;
    case '1d':
      return 86_400;
    case '1w':
      return 604_800;
    default:
      return 60;
  }
}

/**
 * 2024-03-05, 07:00 New York. A 240-bar session therefore starts in
 * pre-market and crosses the 09:30 open, so roughly the first 150 bars are
 * extended hours and the rest are regular — which is what gives the
 * extended-hours tint and the pre-market high/low something real to describe.
 */
export const SESSION_START = Math.floor(Date.UTC(2024, 2, 5, 12, 0) / 1000);
export const REGULAR_OPEN = Math.floor(Date.UTC(2024, 2, 5, 14, 30) / 1000);

/** Deterministic pseudo-random source, so runs are byte-identical. */
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

function seedFor(symbol: string): number {
  let hash = 7;
  for (const char of symbol) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash;
}

/** INDICATORS plus the overhead stack, for the buried-price case. */
export const MANY_INDICATORS: IndicatorSpec[] = [
  ...INDICATORS,
  line('prev_week_high', 'Prev Week High', 'key_levels', '#6d6b66', '#a8a69d'),
  line('prev_month_high', 'Prev Month High', 'key_levels', '#6d6b66', '#a8a69d'),
  line('prev_quarter_high', 'Prev Qtr High', 'key_levels', '#6d6b66', '#a8a69d'),
  line('prev_year_high', 'Prev Year High', 'key_levels', '#6d6b66', '#a8a69d'),
  line('high_13w', '13W High', 'key_levels', '#6d6b66', '#a8a69d'),
  line('high_26w', '26W High', 'key_levels', '#6d6b66', '#a8a69d'),
];

export interface SnapshotOptions {
  symbol?: string;
  timeframe?: string;
  barCount?: number;
  basePrice?: number;
  source?: 'ibkr' | 'alpaca' | 'none';
  delayed?: boolean;
  /** Serve the overhead level stack as well — see `OVERHEAD_LEVELS`. */
  manyLevels?: boolean;
}

export function makeBars(options: SnapshotOptions = {}): WireBar[] {
  const { symbol = 'AAPL', timeframe = '10s', barCount = 240, basePrice = 10 } = options;
  const step = stepFor(timeframe);
  const random = seeded(seedFor(symbol));
  const bars: WireBar[] = [];
  let price = basePrice;

  // Sub-minute sessions start shortly before the open so a 240-bar window
  // still crosses 09:30 — sixty pre-market bars, the rest regular hours.
  const start = step < 60 ? REGULAR_OPEN - 60 * step : SESSION_START;

  for (let i = 0; i < barCount; i += 1) {
    const time = start + i * step;
    const drift = (random() - 0.48) * 0.08;
    const open = price;
    const close = Math.max(0.5, open + drift);
    const high = Math.max(open, close) + random() * 0.04;
    const low = Math.min(open, close) - random() * 0.04;
    const bar: WireBar = {
      t: time,
      o: round(open),
      h: round(high),
      l: round(low),
      c: round(close),
      v: Math.round(2000 + random() * 20000),
      n: Math.round(20 + random() * 200),
    };
    // Anything before the 09:30 open is extended hours, which the chart tints.
    if (time < REGULAR_OPEN) bar.x = 1;
    bars.push(bar);
    price = close;
  }
  return bars;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function round4(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

function ema(values: number[], span: number): Array<number | null> {
  const out: Array<number | null> = values.map(() => null);
  if (values.length < span) return out;
  const alpha = 2 / (span + 1);
  let current = values.slice(0, span).reduce((a, b) => a + b, 0) / span;
  out[span - 1] = current;
  for (let i = span; i < values.length; i += 1) {
    current = alpha * values[i] + (1 - alpha) * current;
    out[i] = current;
  }
  return out;
}

export function makeSeries(bars: WireBar[], manyLevels = false): Record<string, SeriesPoint[]> {
  const closes = bars.map((bar) => bar.c);
  const first = bars[0];
  const last = bars.at(-1)!;

  const series: Record<string, SeriesPoint[]> = {};
  // Spans are the 1-minute ones at every timeframe: the fixture does not
  // model the 10s chart's x6 mapping, and a 600-span line would have no
  // points at all in a 240-bar window.
  for (const [id, span] of [
    ['ema9', 9],
    ['ema20', 20],
    ['ema45', 45],
    ['ema100', 100],
  ] as const) {
    series[id] = ema(closes, span)
      .map((value, i) => (value == null ? null : ([bars[i].t, round(value)] as SeriesPoint)))
      .filter((point): point is SeriesPoint => point !== null);
  }

  // Volume-weighted running average across the session.
  let cumulativePv = 0;
  let cumulativeVolume = 0;
  series.vwap = bars.map((bar) => {
    cumulativePv += ((bar.h + bar.l + bar.c) / 3) * bar.v;
    cumulativeVolume += bar.v;
    return [bar.t, round(cumulativePv / cumulativeVolume)] as SeriesPoint;
  });

  // Windowed RVOL: a recognisable ramp, deterministic for assertions.
  series.wrvol = bars.map((bar, i) => [bar.t, round(1 + i * 0.01)] as SeriesPoint);

  // MACD triple, only consumed when the timeframe carries the pane.
  const fast = ema(closes, 12);
  const slow = ema(closes, 26);
  const macdValues = closes.map((_, i) => {
    const f = fast[i];
    const s = slow[i];
    return f == null || s == null ? null : f - s;
  });
  const defined = macdValues.filter((value): value is number => value != null);
  const signalDefined = ema(defined, 9);
  let cursor = 0;
  const toPoints = (values: Array<number | null>) =>
    values
      .map((value, i) => (value == null ? null : ([bars[i].t, round4(value)] as SeriesPoint)))
      .filter((point): point is SeriesPoint => point !== null);
  const signalValues = macdValues.map((value) => {
    if (value == null) return null;
    const signal = signalDefined[cursor];
    cursor += 1;
    return signal ?? null;
  });
  series.macd = toPoints(macdValues);
  series.macd_signal = toPoints(signalValues);
  series.macd_hist = toPoints(
    macdValues.map((value, i) => {
      const signal = signalValues[i];
      return value == null || signal == null ? null : value - signal;
    }),
  );

  // Key levels hold one value for the session, so they compress to endpoints —
  // exactly what the backend sends.
  const premarket = bars.filter((bar) => bar.x === 1);
  const pmHigh = Math.max(...premarket.map((bar) => bar.h));
  const pmLow = Math.min(...premarket.map((bar) => bar.l));
  const previousClose = round(first.o * 0.94);
  const levels: Record<string, number> = {
    pm_high: round(pmHigh),
    pm_low: round(pmLow),
    prev_day_close: previousClose,
    // Deliberately within a fraction of a percent of the previous close, so
    // the fixture always contains a real confluence band to assert against.
    // Levels converging like this is the common case, not a contrived one.
    prev_day_high: round(previousClose * 1.0012),
    d_sma20: round(previousClose * 0.9988),
    prev_day_low: round(first.o * 0.88),
    high_52w: round(Math.max(...bars.map((b) => b.h)) * 1.4),
    low_52w: round(Math.min(...bars.map((b) => b.l)) * 0.55),
  };
  // A runner that has given back most of its move has every longer-period
  // high stacked overhead — which is what buries the last price in the key
  // levels panel. Spread them from just above the session high upward.
  if (manyLevels) {
    const sessionHigh = Math.max(...bars.map((bar) => bar.h));
    OVERHEAD_LEVELS.forEach((id, index) => {
      levels[id] = round(sessionHigh * (1.02 + index * 0.035));
    });
  }

  for (const [id, value] of Object.entries(levels)) {
    series[id] = [
      [first.t, value],
      [last.t, value],
    ];
  }

  return series;
}

export function makeSnapshot(options: SnapshotOptions = {}) {
  const {
    symbol = 'AAPL',
    timeframe = '10s',
    source = 'alpaca',
    delayed = false,
  } = options;
  const bars = makeBars({ ...options, timeframe });
  return {
    type: 'snapshot' as const,
    symbol,
    timeframe,
    bars,
    series: makeSeries(bars, options.manyLevels ?? false),
    source,
    delayed,
    generated_at: SESSION_START + bars.length * stepFor(timeframe),
  };
}

/** The next bar after a snapshot, for live-update tests. */
export function makeNextBar(
  snapshot: ReturnType<typeof makeSnapshot>,
  overrides: Partial<WireBar> = {},
) {
  const last = snapshot.bars.at(-1)!;
  const bar: WireBar = {
    t: last.t + stepFor(snapshot.timeframe),
    o: last.c,
    h: round(last.c + 0.15),
    l: round(last.c - 0.05),
    c: round(last.c + 0.1),
    v: 15_000,
    n: 180,
    ...overrides,
  };

  const values: Record<string, number> = {};
  for (const [id, points] of Object.entries(snapshot.series)) {
    const lastPoint = points.at(-1);
    if (lastPoint) values[id] = lastPoint[1];
  }
  values.ema9 = round(bar.c - 0.02);

  return { type: 'bar' as const, symbol: snapshot.symbol, timeframe: snapshot.timeframe, bar, series: values };
}

export function makeStatus(overrides: Partial<Record<string, unknown>> = {}) {
  // ibkr_connected follows the source unless a test says otherwise — a
  // status frame claiming "source: ibkr" with the connection down would be
  // a contradiction the real backend never sends.
  return {
    type: 'status' as const,
    source: 'alpaca',
    delayed: false,
    ibkr_connected: overrides.source === 'ibkr',
    alpaca_available: true,
    message: overrides.source === 'ibkr' ? null : 'IBKR unavailable — using Alpaca.',
    ...overrides,
  };
}

export function makeScannerRows(count = 6) {
  const random = seeded(99);
  return Array.from({ length: count }, (_, index) => {
    const price = round(1 + random() * 18);
    return {
      rank: index,
      symbol: `SC${String(index + 1).padStart(2, '0')}`,
      exchange: 'NASDAQ',
      price,
      pct_change: round((random() - 0.3) * 90),
      volume: Math.round(200_000 + random() * 8_000_000),
      trades_1m: Math.round(random() * 400),
      trades_5m: Math.round(random() * 1800),
      dollar_vol_1m: Math.round(random() * 900_000),
      dollar_vol_5m: Math.round(random() * 4_000_000),
      trades_day: Math.round(random() * 60_000),
      dollar_vol_day: Math.round(random() * 90_000_000),
    };
  });
}

export function makeScannerMessage(
  scannerId: ScannerTierId,
  rows = makeScannerRows(),
  running = true,
) {
  const label = SCANNER_TIERS.find((tier) => tier.id === scannerId)?.label ?? scannerId;
  return {
    type: 'scanner' as const,
    scanner_id: scannerId,
    label,
    rows,
    config: {
      scan_code: 'TOP_TRADE_RATE',
      above_price: 1,
      below_price: 20,
      above_volume: 100_000,
      market_cap_above: null,
      market_cap_below: null,
      change_perc_above: null,
      number_of_rows: 5,
    },
    running,
  };
}

// ── level 1 / reference data ───────────────────────────────────────────

export function makeQuote(symbol = 'AAPL', overrides: Partial<Record<string, number>> = {}) {
  return {
    type: 'quote' as const,
    symbol,
    bid: 10.02,
    ask: 10.06,
    bs: 700,
    as: 1200,
    t: SESSION_START + 240 * 10,
    ...overrides,
  };
}

export function makeInfo(symbol = 'AAPL', overrides: Partial<Record<string, unknown>> = {}) {
  return {
    type: 'info' as const,
    symbol,
    float_shares: 8_500_000,
    market_cap: 62_000_000,
    shares_outstanding: 12_000_000,
    avg_vol_10d: 1_900_000,
    all_time_high: 22.0,
    description: 'Fixture Industries',
    exchange: 'NASDAQ',
    sector: 'Electronic Technology',
    day_volume: 14_200_000,
    pm_volume: 1_100_000,
    prev_close: 8.4,
    rel_vol: 7.47,
    float_rotation: 1.67,
    pm_float_rotation: 0.129,
    halt_ref: 10.0,
    halt_up: 11.0,
    halt_down: 9.0,
    halt_active: false,
    halt_band_pct: 10,
    halt_band_cents: null,
    listed_days: null,
    shortable: 2.9,
    shortable_shares: 1_500_000,
    halted: false,
    halts_today: 0,
    halt_halted_at: null,
    halt_resumed_at: null,
    reverse_split_ratio: null,
    reverse_split_days: null,
    yahoo_float: null,
    pullback_depth_pct: null,
    pullback_vol_ratio: null,
    pullback_bars: null,
    pullback_leg_pct: null,
    dilution: null,
    generated_at: SESSION_START + 240 * 10,
    ...overrides,
  };
}

/**
 * A dilution read shaped like Celularity's, which is what the panel was
 * designed against: 25.8M warrants over 28.9M shares, five months of cash, a
 * baby shelf and a filing trail full of offerings.
 */
export function makeDilutionSummary(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    tone: 'serial' as const,
    warrant_overhang: 0.89,
    warrant_strike: 3.0,
    runway_months: 5.6,
    reasons: [
      'warrants 89% of shares outstanding',
      '5.6 months of cash at current burn',
      'public float under $75M — baby shelf limits apply',
    ],
    ...overrides,
  };
}

function dated(value: number, asOf: string, staleDays: number, form = '10-K') {
  return { value, as_of: asOf, form, stale_days: staleDays };
}

export function makeFundamentals(symbol = 'AAPL', overrides: Partial<Record<string, unknown>> = {}) {
  return {
    symbol,
    available: true,
    profile: {
      cik: 1752828,
      name: 'Fixture Industries Inc',
      sic: '2834',
      sic_description: 'Pharmaceutical Preparations',
      exchanges: ['Nasdaq'],
      website: '',
      state_of_incorporation: 'Delaware',
      fiscal_year_end: '1231',
    },
    business: {
      industry: 'Miscellaneous Commercial Services',
      country: 'United States',
      employees: 115,
      price_earnings: null,
      eps_ttm: -3.584,
      revenue_ttm: 26_550_000,
      gross_margin: -3.08,
      operating_margin: -220.5,
      net_income: -91_716_000,
      total_debt: 74_713_000,
      total_cash: 6_175_000,
      free_cash_flow: -13_254_000,
      ebitda: -70_000_000,
      debt_to_equity: null,
      current_ratio: 0.1525,
      enterprise_value: 160_000_000,
      return_on_equity: null,
      price_to_book: 2.1,
      price_to_sales: 3.4,
      beta: 1.158,
      perf_ytd: 42.34,
      earnings_next: 1787918400,
    },
    dilution: {
      ...makeDilutionSummary(),
      shares_outstanding: dated(28_945_961, '2026-04-28', 122),
      shares_issued: dated(28_837_787, '2025-12-31', 240),
      shares_authorized: dated(730_000_000, '2025-12-31', 240),
      warrants: dated(25_774_577, '2025-12-31', 240),
      warrant_strike: dated(3.0, '2024-11-25', 641),
      preferred: dated(1_732_084, '2025-12-31', 240),
      convertible_notes: dated(922_000, '2025-12-31', 240),
      cash: dated(6_175_000, '2025-12-31', 240),
      annual_operating_cash_flow: dated(-13_254_000, '2025-12-31', 240),
      public_float: dated(28_400_000, '2025-06-30', 424),
      fully_diluted: 54_720_538,
      fully_diluted_ratio: 1.89,
      authorized_headroom: 701_162_213,
      baby_shelf: true,
      baby_shelf_capacity: 9_466_667,
      // The same cap re-measured at the 60-day high: 28.9M float shares at
      // $2.10 is $60.7M of float, so still capped — but at more than twice
      // the ceiling the cover page implies.
      live_shelf: {
        price: 2.1,
        public_float: 60_690_000,
        capped: true,
        capacity: 20_230_000,
        multiple: 2.14,
      },
      share_growth_12m: 0.209,
      offerings_12m: 3,
      delinquent: true,
      listing_deficiency: true,
      delisting_filed: true,
    },
    ...overrides,
  };
}

/**
 * Headlines shaped like the ones IBKR actually sends — the real CELU feed,
 * complete with a supply story, a distress pair and an ordinary row.
 */
export function makeHeadline(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    article_id: 'DJ-N$1f364634',
    provider: 'DJ-N',
    time: SESSION_START + 240 * 10,
    headline: 'Celularity Announces Pricing of $8M Public Offering',
    catalyst: 'supply' as const,
    related: [],
    ...overrides,
  };
}

export function makeNews(symbol = 'AAPL', overrides: Partial<Record<string, unknown>> = {}) {
  return {
    symbol,
    providers: [
      { code: 'DJ-N', name: 'Dow Jones Global Equity Trader' },
      { code: 'BRFG', name: 'Briefing.com General Market Columns' },
    ],
    headlines: [
      makeHeadline(),
      makeHeadline({
        article_id: 'DJ-N$2',
        headline: 'Celularity: Not in Compliance With Nasdaq Listing Rule 5250(C)(1)',
        catalyst: 'distress',
        time: SESSION_START + 200 * 10,
      }),
      makeHeadline({
        article_id: 'DJ-N$3',
        headline: 'Celularity and MuseCell Announce U.S. Manufacturing Collaboration',
        catalyst: 'upside',
        time: SESSION_START + 150 * 10,
        related: ['DJ-N$3b', 'DJ-N$3c'],
      }),
      makeHeadline({
        article_id: 'DJ-N$4',
        headline: 'Celularity Names Steven N. Gordon Chief Operating Officer',
        catalyst: 'none',
        time: SESSION_START + 100 * 10,
      }),
    ],
    ...overrides,
  };
}

export function makeArticle(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    provider: 'DJ-N',
    article_id: 'DJ-N$1f364634',
    paragraphs: [
      'Celularity Inc. (CELU) announced the pricing of an underwritten public offering.',
      'The full text of this SEC filing can be retrieved at: https://www.sec.gov/Archives/edgar/data/1752828/',
    ],
    ...overrides,
  };
}

export function makeNewsMessage(symbol = 'AAPL', overrides: Partial<Record<string, unknown>> = {}) {
  return {
    type: 'news' as const,
    symbol,
    headline: makeHeadline(overrides),
  };
}

/** A filing trail shaped like Celularity's: offerings, a late report, a
 *  delisting notice and the routine rows they sit among. */
export function makeFiling(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    form: '424B5',
    kind: 'dilution' as const,
    note: 'shelf takedown — shares being sold now',
    filed: '2026-08-27',
    accepted: 1787702400,
    accession: '0001493152-26-000878',
    items: [] as string[],
    url: 'https://www.sec.gov/Archives/edgar/data/1752828/000149315226000878/p.htm',
    ...overrides,
  };
}

/** A long dilution trail, for exercising the recent/older split. */
export function makeLongFilingTrail(count: number) {
  return Array.from({ length: count }, (_, index) =>
    makeFiling({
      accession: `long-${index}`,
      filed: `20${String(26 - Math.floor(index / 12)).padStart(2, '0')}-01-01`,
      note: `offering number ${index}`,
    }),
  );
}

export function makeFilings(symbol = 'AAPL', overrides: Partial<Record<string, unknown>> = {}) {
  return {
    symbol,
    available: true,
    filings: [
      makeFiling(),
      makeFiling({
        form: 'NT 10-Q',
        kind: 'distress',
        note: 'quarterly report filed late',
        filed: '2026-08-14',
        accession: '0001493152-26-038318',
      }),
      makeFiling({
        form: '10-K',
        kind: 'periodic',
        note: 'annual report',
        filed: '2026-04-30',
        accession: '0001493152-26-020000',
      }),
      makeFiling({
        form: '4',
        kind: 'ownership',
        note: 'insider bought or sold',
        filed: '2026-06-23',
        accession: '0001493152-26-029000',
      }),
    ],
    ...overrides,
  };
}

export function makeFilingMessage(
  symbol = 'AAPL',
  overrides: Partial<Record<string, unknown>> = {},
) {
  return { type: 'filing' as const, symbol, filing: makeFiling(overrides) };
}

export function makeRegimeMessage(running = true) {
  return {
    type: 'regime' as const,
    regime: { up_50_count: 4, up_100_count: 1 },
    running,
    error: null,
  };
}

export function makeApiUsage(overrides: { alpaca?: number; ibkr?: number } = {}) {
  return {
    type: 'api' as const,
    alpaca: { used: overrides.alpaca ?? 12, limit: 200, window_s: 60 },
    ibkr: { used: overrides.ibkr ?? 4, limit: 60, window_s: 600 },
  };
}
