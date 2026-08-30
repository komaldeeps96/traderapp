import { describe, expect, it } from 'vitest';

import type {
  DilutionSummary,
  IndicatorSpec,
  InfoMessage,
  WireBar,
} from '@/types/protocol';

import {
  athLevel,
  borrowStatus,
  budgetTone,
  buildBands,
  buildDilutionView,
  buildInfoView,
  buildKeyLevels,
  buildLevelStyles,
  buildOhlcv,
  buildQuoteView,
  clusterLevels,
  dilutionWorseThan,
  floatDisagreement,
  headroom,
  isFarLevel,
  levelIndicators,
  nearestLevels,
  overlayIndicators,
  plottableAth,
  pullbackTone,
  spreadTone,
} from './selectors';

function spec(overrides: Partial<IndicatorSpec> & Pick<IndicatorSpec, 'id'>): IndicatorSpec {
  return {
    type: 'daily_level',
    label: overrides.id,
    color: '#898781',
    color_dark: '#898781',
    pane: 'price',
    readout_only: false,
    line_width: 1,
    line_style: 'solid',
    price_line: false,
    last_value: true,
    group: 'key_levels',
    timeframes: { '1m': { enabled: true } },
    ...overrides,
  };
}

const SPECS: IndicatorSpec[] = [
  spec({ id: 'pm_high', label: 'PM High' }),
  spec({ id: 'prev_day_close', label: 'Prev Day Close' }),
  spec({ id: 'high_52w', label: '52W High' }),
  spec({ id: 'd_sma20', label: '1D SMA 20', group: 'daily_ma' }),
  spec({ id: 'ema9', label: 'EMA 9', type: 'ema', group: 'moving_averages' }),
  spec({ id: 'volume', label: 'Volume', type: 'volume', pane: 'volume', group: 'panes' }),
];

const VALUES = {
  pm_high: 12.5,
  prev_day_close: 9.8,
  high_52w: 18.0,
  d_sma20: 10.4,
  ema9: 10.05,
};

const VISIBILITY = { pm_high: true, prev_day_close: true, high_52w: false, d_sma20: true };

describe('buildKeyLevels', () => {
  it('includes key levels and daily moving averages', () => {
    const levels = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', 10);
    expect(levels.map((level) => level.id)).toEqual([
      'high_52w',
      'pm_high',
      'd_sma20',
      'prev_day_close',
    ]);
  });

  it('excludes overlays and panes', () => {
    const ids = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', 10).map((l) => l.id);
    expect(ids).not.toContain('ema9');
    expect(ids).not.toContain('volume');
  });

  it('sorts from highest price to lowest', () => {
    const values = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', 10).map((l) => l.value);
    expect(values).toEqual([...values].sort((a, b) => b - a));
  });

  it('marks levels above and below the price', () => {
    const levels = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', 10);
    const byId = Object.fromEntries(levels.map((level) => [level.id, level]));
    expect(byId['pm_high']?.side).toBe('above');
    expect(byId['prev_day_close']?.side).toBe('below');
  });

  it('measures percentage distance from the price', () => {
    const levels = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', 10);
    const pmHigh = levels.find((level) => level.id === 'pm_high');
    expect(pmHigh?.distancePercent).toBeCloseTo(25);
  });

  it('skips levels with no value yet', () => {
    const levels = buildKeyLevels(SPECS, { pm_high: 12 }, VISIBILITY, 'light', 10);
    expect(levels).toHaveLength(1);
  });

  it('carries visibility through', () => {
    const levels = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', 10);
    expect(levels.find((level) => level.id === 'high_52w')?.visible).toBe(false);
  });

  it('uses the dark colour in dark mode', () => {
    const specs = [spec({ id: 'pm_high', color: '#111111', color_dark: '#eeeeee' })];
    const [level] = buildKeyLevels(specs, { pm_high: 5 }, {}, 'dark', 4);
    expect(level?.color).toBe('#eeeeee');
  });

  it('leaves distance undefined without a price', () => {
    const levels = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', null);
    expect(levels[0]?.distancePercent).toBeNull();
  });
});

describe('nearestLevels', () => {
  it('finds the closest level above the price', () => {
    // At 10, the nearest overhead level is the 1D SMA 20 at 10.4 — not the
    // more distant PM High at 12.5.
    const levels = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', 10);
    expect(nearestLevels(levels).above?.id).toBe('d_sma20');
  });

  it('picks the closest overhead level, not merely the first listed', () => {
    const levels = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', 10.5);
    expect(nearestLevels(levels).above?.id).toBe('pm_high');
  });

  it('finds the closest level below the price', () => {
    const levels = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', 10);
    expect(nearestLevels(levels).below?.id).toBe('prev_day_close');
  });

  it('returns nothing when the price is above everything', () => {
    const levels = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', 100);
    expect(nearestLevels(levels).above).toBeNull();
  });

  it('returns nothing when the price is below everything', () => {
    const levels = buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', 1);
    expect(nearestLevels(levels).below).toBeNull();
  });
});

describe('clusterLevels', () => {
  // The situation that motivated this: on a sub-dollar ticker several levels
  // land within a fraction of a cent and become an unreadable smear.
  const STACKED_SPECS = [
    spec({ id: 'prev_day_low', label: 'Prev Day Low' }),
    spec({ id: 'low_52w', label: '52W Low' }),
    spec({ id: 'low_26w', label: '26W Low' }),
    spec({ id: 'pm_high', label: 'PM High' }),
  ];
  const STACKED_VALUES = {
    prev_day_low: 0.4001,
    low_52w: 0.4,
    low_26w: 0.3999,
    pm_high: 0.41,
  };

  function cluster(price: number | null, tolerance?: number) {
    const levels = buildKeyLevels(STACKED_SPECS, STACKED_VALUES, {}, 'light', price);
    return clusterLevels(levels, price, tolerance);
  }

  it('merges levels sitting at the same price', () => {
    const bands = cluster(0.39);
    const stacked = bands.find((band) => band.strength > 1);
    expect(stacked?.members.map((m) => m.id).sort()).toEqual([
      'low_26w',
      'low_52w',
      'prev_day_low',
    ]);
  });

  it('leaves a distinct level on its own', () => {
    const bands = cluster(0.39);
    expect(bands.find((band) => band.members[0]?.id === 'pm_high')?.strength).toBe(1);
  });

  it('records how many levels agree', () => {
    expect(cluster(0.39).map((band) => band.strength).sort()).toEqual([1, 3]);
  });

  it('reports the band price and its extent', () => {
    const band = cluster(0.39).find((b) => b.strength > 1)!;
    expect(band.low).toBeCloseTo(0.3999);
    expect(band.high).toBeCloseTo(0.4001);
    expect(band.value).toBeCloseTo(0.4);
  });

  it('sorts bands from high to low', () => {
    const values = cluster(0.39).map((band) => band.value);
    expect(values).toEqual([...values].sort((a, b) => b - a));
  });

  it('marks the nearest band above as resistance', () => {
    const bands = cluster(0.395);
    expect(bands.find((band) => band.emphasis === 'resistance')?.value).toBeCloseTo(0.4);
  });

  it('marks the nearest band below as support', () => {
    // Above every level: the 0.41 band becomes the nearest support.
    const bands = cluster(0.5);
    expect(bands.find((band) => band.emphasis === 'support')?.value).toBeCloseTo(0.41);
  });

  it('emphasises at most one band on each side', () => {
    const bands = cluster(0.405);
    expect(bands.filter((band) => band.emphasis === 'resistance')).toHaveLength(1);
    expect(bands.filter((band) => band.emphasis === 'support')).toHaveLength(1);
  });

  it('splits everything apart at a tight tolerance', () => {
    expect(cluster(0.39, 0.0001).every((band) => band.strength === 1)).toBe(true);
  });

  it('does not chain unboundedly at a loose tolerance', () => {
    // A ladder of levels each just inside the tolerance must not collapse into
    // one meaningless band spanning the whole range.
    const ladderSpecs = Array.from({ length: 6 }, (_, i) =>
      spec({ id: `low_${i}`, label: `L${i}` }),
    );
    const ladderValues = Object.fromEntries(
      ladderSpecs.map((s, i) => [s.id, 100 + i * 0.3]),
    );
    const levels = buildKeyLevels(ladderSpecs, ladderValues, {}, 'light', 99);
    const bands = clusterLevels(levels, 99, 0.35);
    expect(bands.length).toBeGreaterThan(1);
  });

  it('is empty without levels', () => {
    expect(clusterLevels([], 10)).toEqual([]);
  });

  it('has a stable key derived from its members', () => {
    expect(cluster(0.39)[1]?.key).toBe('prev_day_low+low_52w+low_26w');
  });
});

describe('buildLevelStyles', () => {
  const SPECS_FOR_STYLE = [
    spec({ id: 'a', label: 'A' }),
    spec({ id: 'b', label: 'B' }),
    spec({ id: 'c', label: 'C' }),
  ];

  function styles(values: Record<string, number>, price: number, theme: 'light' | 'dark' = 'light') {
    const levels = buildKeyLevels(SPECS_FOR_STYLE, values, {}, theme, price);
    return buildLevelStyles(clusterLevels(levels, price), theme);
  }

  /** The one line in a band that carries its label and its weight. */
  function leadOf(result: Record<string, { labelVisible: boolean; lineWidth: number }>) {
    return Object.values(result).find((style) => style.labelVisible)!;
  }

  it('no longer counts members with line weight', () => {
    // Depth is shown by the shaded zone (see buildBands); a thicker line said
    // something was there without saying where it began or ended. Both sides
    // here are the nearest band overhead, so only the member count differs.
    const stacked = leadOf(styles({ a: 50, b: 50.01, c: 50.02 }, 40));
    const lone = styles({ a: 50, b: 80, c: 20 }, 40).a!;
    expect(stacked.lineWidth).toBe(lone.lineWidth);
  });

  it('still lifts the two actionable bands above the recessive ones', () => {
    const result = styles({ a: 50, b: 80, c: 20 }, 40);
    expect(result.a!.lineWidth).toBeGreaterThan(result.b!.lineWidth);
  });

  it('draws the rest of a band thin so it reads as one line', () => {
    const result = styles({ a: 50, b: 50.01, c: 50.02 }, 40);
    const followers = Object.values(result).filter((style) => !style.labelVisible);
    expect(followers.every((style) => style.lineWidth === 1)).toBe(true);
  });

  it('labels only one line per band', () => {
    const result = styles({ a: 50, b: 50.01, c: 50.02 }, 40);
    const labelled = Object.values(result).filter((style) => style.labelVisible);
    expect(labelled).toHaveLength(1);
  });

  it('says how many levels the label stands for', () => {
    const result = styles({ a: 50, b: 50.01, c: 50.02 }, 40);
    const labelled = Object.values(result).find((style) => style.labelVisible)!;
    expect(labelled.title).toMatch(/\+2$/);
  });

  it('does not decorate a lone level with a count', () => {
    const result = styles({ a: 50, b: 80, c: 20 }, 40);
    expect(result.a!.title).toBe('A');
  });

  it('colours the nearest band above violet', () => {
    // Not red: that is a candle colour, so a level drawn in it competes with
    // the bars it sits over and picks up their meaning.
    const result = styles({ a: 50, b: 80, c: 20 }, 40);
    expect(result.a!.color).toBe('#8250df');
  });

  it('colours the nearest band below amber', () => {
    const result = styles({ a: 50, b: 80, c: 20 }, 40);
    expect(result.c!.color).toBe('#9a6700');
  });

  it('keeps the two bands off the candle hues entirely', () => {
    const candles = ['#cf222e', '#1a7f37', '#f85149', '#3fb950'];
    for (const theme of ['light', 'dark'] as const) {
      const result = styles({ a: 50, b: 80, c: 20 }, 40, theme);
      expect(candles).not.toContain(result.a!.color);
      expect(candles).not.toContain(result.c!.color);
    }
  });

  it('leaves more distant levels recessive', () => {
    const result = styles({ a: 50, b: 80, c: 20 }, 40);
    expect(result.b!.color).toBe('#898781');
  });

  it('uses the dark steps in dark mode', () => {
    const result = styles({ a: 50, b: 80, c: 20 }, 40, 'dark');
    expect(result.a!.color).toBe('#a371f7');
    expect(result.c!.color).toBe('#d29922');
  });

  it('covers every level in the clusters', () => {
    const result = styles({ a: 50, b: 80, c: 20 }, 40);
    expect(Object.keys(result).sort()).toEqual(['a', 'b', 'c']);
  });
});

describe('buildOhlcv', () => {
  const bar: WireBar = { t: 1_700_000_000, o: 10, h: 11, l: 9.5, c: 10.5, v: 1000, n: 20 };
  const readout = (over: Partial<import('@/store/useTerminalStore').Readout> = {}) => ({
    bar,
    previousClose: 10,
    values: {},
    sessionVolume: null,
    ...over,
  });

  it('is null without a readout', () => {
    expect(buildOhlcv(null)).toBeNull();
  });

  it('computes the bar-over-bar change', () => {
    expect(buildOhlcv(readout())?.barChange?.absolute).toBeCloseTo(0.5);
  });

  it('computes the change against the previous session close', () => {
    const view = buildOhlcv(readout({ values: { prev_day_close: 8 } }));
    expect(view?.sessionChange?.percent).toBeCloseTo(31.25);
  });

  it('omits the session change without a previous close', () => {
    expect(buildOhlcv(readout())?.sessionChange).toBeNull();
  });

  it('flags an extended-hours bar', () => {
    const view = buildOhlcv(readout({ bar: { ...bar, x: 1 }, previousClose: null }));
    expect(view?.extendedHours).toBe(true);
  });

  it('leaves regular-hours bars unflagged', () => {
    expect(buildOhlcv(readout({ previousClose: null }))?.extendedHours).toBe(false);
  });

  it('derives the market cap at the bar from its close', () => {
    const info = { shares_outstanding: 9_000_000 } as InfoMessage;
    expect(buildOhlcv(readout(), info)?.marketCapAtBar).toBeCloseTo(9_000_000 * 10.5);
    expect(buildOhlcv(readout())?.marketCapAtBar).toBeNull();
    const none = { shares_outstanding: null } as unknown as InfoMessage;
    expect(buildOhlcv(readout(), none)?.marketCapAtBar).toBeNull();
  });

  it('reads the windowed RVOL from the server-stamped series', () => {
    // Computed backend-side off the 20-day minute base and delivered like
    // any indicator value, so it reaches 10-second bars too.
    expect(buildOhlcv(readout({ values: { wrvol: 3.2 } }))?.windowRvol).toBeCloseTo(3.2);
    expect(buildOhlcv(readout())?.windowRvol).toBeNull();
  });

  it('derives the session pace and rotation as of the bar', () => {
    const info = { avg_vol_10d: 2_000_000, float_shares: 5_000_000 } as InfoMessage;
    const view = buildOhlcv(readout({ sessionVolume: 4_000_000 }), info);
    expect(view?.sessionVolume).toBe(4_000_000);
    expect(view?.rvolAtBar).toBeCloseTo(2.0);
    expect(view?.rotationAtBar).toBeCloseTo(0.8);
  });

  it('leaves pace and rotation out without reference data', () => {
    const view = buildOhlcv(readout({ sessionVolume: 4_000_000 }));
    expect(view?.rvolAtBar).toBeNull();
    expect(view?.rotationAtBar).toBeNull();
    const zeroed = { avg_vol_10d: 0, float_shares: null } as unknown as InfoMessage;
    const guarded = buildOhlcv(readout({ sessionVolume: 4_000_000 }), zeroed);
    expect(guarded?.rvolAtBar).toBeNull();
    expect(guarded?.rotationAtBar).toBeNull();
  });

  it('reads the VWAP distance at the bar from the plotted series', () => {
    const view = buildOhlcv(readout({ values: { vwap: 10.0 } }));
    expect(view?.vwapDeltaPercent).toBeCloseTo(5.0);
    expect(buildOhlcv(readout())?.vwapDeltaPercent).toBeNull();
  });
});

describe('indicator grouping', () => {
  it('separates overlays from key levels', () => {
    expect(overlayIndicators(SPECS, '1m').map((s) => s.id)).toEqual(['ema9']);
  });

  it('collects key levels and daily moving averages', () => {
    expect(levelIndicators(SPECS, '1m').map((s) => s.id)).toEqual([
      'pm_high',
      'prev_day_close',
      'high_52w',
      'd_sma20',
    ]);
  });

  it('excludes indicators not configured for the timeframe', () => {
    expect(overlayIndicators(SPECS, '1d')).toHaveLength(0);
  });
});

describe('buildQuoteView', () => {
  const quote = (bid: number, ask: number) => ({
    type: 'quote' as const,
    symbol: 'RUN',
    bid,
    ask,
    bs: 300,
    as: 1200,
    t: 1_700_000_000,
  });

  it('derives spread, mid and percent', () => {
    const view = buildQuoteView(quote(5.0, 5.05));
    expect(view).not.toBeNull();
    expect(view!.spread).toBeCloseTo(0.05);
    expect(view!.mid).toBeCloseTo(5.025);
    expect(view!.spreadPercent).toBeCloseTo((0.05 / 5.025) * 100);
  });

  it('rejects crossed or empty quotes', () => {
    expect(buildQuoteView(quote(5.1, 5.0))).toBeNull();
    expect(buildQuoteView(quote(0, 5.0))).toBeNull();
    expect(buildQuoteView(null)).toBeNull();
  });

  it('grades the spread against the playbook thresholds', () => {
    expect(spreadTone(0.04)).toBe('tight');
    expect(spreadTone(0.15)).toBe('ok');
    expect(spreadTone(0.35)).toBe('wide');
    expect(spreadTone(0.6)).toBe('untradeable');
  });
});

describe('buildInfoView', () => {
  const info = {
    type: 'info' as const,
    symbol: 'RUN',
    float_shares: 5_000_000,
    market_cap: 40_000_000,
    shares_outstanding: 9_000_000,
    avg_vol_10d: 2_000_000,
    all_time_high: null,
    description: 'Runner Inc',
    exchange: 'NASDAQ',
    sector: 'Health',
    day_volume: 10_000_000,
    pm_volume: 800_000,
    prev_close: 4.0,
    rel_vol: 5.0,
    float_rotation: 2.0,
    pm_float_rotation: 0.16,
    halt_ref: 5.0,
    halt_up: 5.5,
    halt_down: 4.5,
    halt_active: true,
    halt_band_pct: 10,
    halt_band_cents: null,
    listed_days: null,
    shortable: null,
    shortable_shares: null,
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
    generated_at: 0,
  };

  it('computes the session change from the previous close', () => {
    const view = buildInfoView(info, 5.0);
    expect(view!.sessionChange!.percent).toBeCloseTo(25);
    expect(view!.sessionChange!.direction).toBe('up');
  });

  it('measures distance to the halt bands from the last price', () => {
    const view = buildInfoView(info, 5.2);
    expect(view!.haltUpDistance).toBeCloseTo(0.3);
    expect(view!.haltDownDistance).toBeCloseTo(0.7);
  });

  it('is null without a message', () => {
    expect(buildInfoView(null, 5.0)).toBeNull();
  });

  it('leaves the change out without a previous close', () => {
    const view = buildInfoView({ ...info, prev_close: null }, 5.0);
    expect(view!.sessionChange).toBeNull();
  });

  it('reports halt headroom as a percentage of the last price', () => {
    const view = buildInfoView(info, 5.0);
    expect(view!.haltUpPercent).toBeCloseTo(10);
    expect(view!.haltDownPercent).toBeCloseTo(10);
  });

  it('flags a float larger than the shares outstanding', () => {
    expect(buildInfoView(info, 5.0)!.floatSuspect).toBe(false);
    const broken = { ...info, float_shares: 10_000_000, shares_outstanding: 9_000_000 };
    expect(buildInfoView(broken, 5.0)!.floatSuspect).toBe(true);
  });

  it('does not flag the float when either side is missing', () => {
    expect(buildInfoView({ ...info, shares_outstanding: null }, 5.0)!.floatSuspect).toBe(false);
    expect(buildInfoView({ ...info, float_shares: null }, 5.0)!.floatSuspect).toBe(false);
  });

  it('prices the reference market cap off the previous close', () => {
    // 9M shares on yesterday's $4.00 — what the company was worth before
    // today, and it must not wobble with the tape. The current-price twin
    // lives beside it in the panel.
    expect(buildInfoView(info, 5.0)!.marketCap).toBe(36_000_000);
    expect(buildInfoView(info, 6.0)!.marketCap).toBe(36_000_000);
  });

  it('falls back to the reported cap with no share count', () => {
    const view = buildInfoView({ ...info, shares_outstanding: null }, 5.0)!;
    expect(view.marketCap).toBe(40_000_000);
    expect(view.reportedMarketCap).toBe(40_000_000);
  });

  it('carries the band tier, which the two headroom numbers do not say', () => {
    // ±10% up and ±10% down is what a 20% band looks like from a price
    // sitting in the middle of it. The tier is the session-long fact.
    expect(buildInfoView(info, 5.0)!.haltBandPercent).toBe(10);
    const cheap = { ...info, halt_band_pct: null, halt_band_cents: 15 };
    expect(buildInfoView(cheap, 5.0)!.haltBandCents).toBe(15);
  });

  // 5 March 2026 is a Thursday and still on EST, so 14:00Z is 09:00 in New
  // York and 15:30Z is 10:30 — either side of the cohort's boundary.
  const NINE_AM = Date.UTC(2026, 2, 5, 14, 0) / 1000;
  const TEN_THIRTY = Date.UTC(2026, 2, 5, 15, 30) / 1000;

  const reopened = (resumedAt: number, secondsSince: number) => ({
    ...info,
    halted: false,
    halts_today: 1,
    halt_resumed_at: resumedAt,
    generated_at: resumedAt + secondsSince,
  });

  it('has nothing to say about a stock that never halted', () => {
    expect(buildInfoView(info, 5.0)!.reopen).toBeNull();
  });

  it('says nothing while the stock is still halted', () => {
    const frozen = { ...reopened(NINE_AM, 30), halted: true };
    expect(buildInfoView(frozen, 5.0)!.reopen).toBeNull();
  });

  it('counts up from the resume inside the measured window', () => {
    const view = buildInfoView(reopened(NINE_AM, 95), 5.0)!;
    expect(view.reopen).toEqual({ secondsSince: 95, tone: 'aligned', wideBand: false });
  });

  it('expires when the fifteen minutes the study covers are up', () => {
    expect(buildInfoView(reopened(NINE_AM, 900), 5.0)!.reopen).not.toBeNull();
    expect(buildInfoView(reopened(NINE_AM, 901), 5.0)!.reopen).toBeNull();
  });

  it('marks a reopen after ten as outside the cohort', () => {
    expect(buildInfoView(reopened(TEN_THIRTY, 60), 5.0)!.reopen!.tone).toBe('late');
  });

  it('judges the hour on the resume, not on now', () => {
    // Resumed at 09:58 with the window running past ten: the stock is still
    // in the cohort it reopened into.
    const justBefore = Date.UTC(2026, 2, 5, 14, 58) / 1000;
    expect(buildInfoView(reopened(justBefore, 600), 5.0)!.reopen!.tone).toBe('aligned');
  });

  it('flags an already-extended reopen ahead of the hour', () => {
    // prev_close 4.00, so 5.40 is +35% — the one bucket that measured
    // negative, and it outranks a merely-uncovered hour.
    expect(buildInfoView(reopened(NINE_AM, 60), 5.4)!.reopen!.tone).toBe('extended');
    expect(buildInfoView(reopened(TEN_THIRTY, 60), 5.4)!.reopen!.tone).toBe('extended');
  });

  it('notes the wide band the study mildly preferred', () => {
    const wide = { ...reopened(NINE_AM, 60), halt_band_pct: 20 };
    expect(buildInfoView(wide, 5.0)!.reopen!.wideBand).toBe(true);
  });
});

describe('isFarLevel', () => {
  it('leaves a level anyone could reach alone', () => {
    expect(isFarLevel(45.68)).toBe(false);
    expect(isFarLevel(-99)).toBe(false);
    expect(isFarLevel(999)).toBe(false);
  });

  it('marks anything past ten times the price', () => {
    expect(isFarLevel(1001)).toBe(true);
    // CHAI's split-adjusted high against a 38-cent tape.
    expect(isFarLevel(24_283_875_452)).toBe(true);
  });

  it('says nothing without a distance', () => {
    expect(isFarLevel(null)).toBe(false);
  });
});

describe('athLevel', () => {
  const withAth = (allTimeHigh: number | null) => ({ all_time_high: allTimeHigh });

  it('is a key level like any other', () => {
    const level = athLevel(withAth(22.0), {}, 10.0)!;
    expect(level.id).toBe('ath');
    expect(level.label).toBe('ATH');
    expect(level.value).toBe(22.0);
    expect(level.side).toBe('above');
    expect(level.distancePercent).toBeCloseTo(120);
    expect(level.visible).toBe(true);
  });

  it('follows its own eye in the panel', () => {
    expect(athLevel(withAth(22.0), { ath: false }, 10.0)!.visible).toBe(false);
  });

  it('sits below the price in blue sky', () => {
    expect(athLevel(withAth(8.0), {}, 10.0)!.side).toBe('below');
  });

  it('is still listed when the split adjustment broke it', () => {
    // CHAI: a $93M split-adjusted high on a 38-cent tape. It stays in the
    // ladder — the panel shows it out of reach rather than dropping it, so
    // "this name's all-time high is meaningless" is visible rather than
    // indistinguishable from the provider never answering.
    const level = athLevel(withAth(93_250_082.12), {}, 0.384)!;
    expect(level.value).toBe(93_250_082.12);
    expect(isFarLevel(level.distancePercent)).toBe(true);
  });

  it('is left out without a usable high', () => {
    expect(athLevel(withAth(null), {}, 10.0)).toBeNull();
    expect(athLevel(withAth(0), {}, 10.0)).toBeNull();
    expect(athLevel(null, {}, 10.0)).toBeNull();
  });
});

describe('plottableAth', () => {
  it('passes an ordinary high through', () => {
    expect(plottableAth(22.0, 10.0)).toBe(22.0);
  });

  it('withholds an out-of-reach high from the chart', () => {
    // Listed in the ladder, but a line ten times off-screen only puts a
    // stray tag on the price axis.
    expect(plottableAth(93_250_082.12, 0.384)).toBeNull();
    expect(plottableAth(50, 1.0)).toBeNull();
  });

  it('draws what it cannot judge', () => {
    // No price yet is not evidence the high is wrong.
    expect(plottableAth(22.0, null)).toBe(22.0);
  });

  it('withholds a missing or impossible high', () => {
    expect(plottableAth(null, 10)).toBeNull();
    expect(plottableAth(0, 10)).toBeNull();
  });
});

describe('pullbackTone', () => {
  it('is healthy when depth, volume and freshness all agree', () => {
    expect(pullbackTone(38, 0.4, 4)).toBe('healthy');
  });

  it('fails past the deepest fib regardless of the rest', () => {
    expect(pullbackTone(80, 0.3, 2)).toBe('failed');
  });

  it('is stale ten minutes off the high', () => {
    expect(pullbackTone(30, 0.4, 10)).toBe('stale');
  });

  it('is merely ok when volume never dried up', () => {
    expect(pullbackTone(38, 0.9, 4)).toBe('ok');
    expect(pullbackTone(38, null, 4)).toBe('ok');
  });

  it('is merely ok when the retrace is deep but not fatal', () => {
    expect(pullbackTone(60, 0.3, 4)).toBe('ok');
  });
});

describe('floatDisagreement', () => {
  it('is the divergence over the smaller source', () => {
    expect(floatDisagreement(2_500_000, 3_500_000)).toBeCloseTo(40);
    expect(floatDisagreement(3_500_000, 2_500_000)).toBeCloseTo(40);
  });

  it('one source silent is not a disagreement', () => {
    expect(floatDisagreement(null, 3_500_000)).toBeNull();
    expect(floatDisagreement(2_500_000, null)).toBeNull();
    expect(floatDisagreement(0, 3_500_000)).toBeNull();
  });
});

describe('buildInfoView tranches 2-3', () => {
  const base = {
    type: 'info' as const,
    symbol: 'RUN',
    float_shares: 5_000_000,
    market_cap: 40_000_000,
    shares_outstanding: 9_000_000,
    avg_vol_10d: null,
    all_time_high: null,
    description: '',
    exchange: '',
    sector: '',
    day_volume: 0,
    pm_volume: 0,
    prev_close: null,
    rel_vol: null,
    float_rotation: null,
    pm_float_rotation: null,
    halt_ref: null,
    halt_up: null,
    halt_down: null,
    halt_active: false,
    halt_band_pct: null,
    halt_band_cents: null,
    listed_days: null,
    shortable: null,
    shortable_shares: null,
    halted: true,
    halts_today: 3,
    halt_halted_at: null,
    halt_resumed_at: null,
    reverse_split_ratio: 12.0,
    reverse_split_days: 45,
    yahoo_float: 7_500_000,
    pullback_depth_pct: 38,
    pullback_vol_ratio: 0.4,
    pullback_bars: 4,
    pullback_leg_pct: 20,
    dilution: null,
    generated_at: 0,
  };

  it('carries the halt state and count', () => {
    const view = buildInfoView(base, 5.0)!;
    expect(view.halted).toBe(true);
    expect(view.haltsToday).toBe(3);
  });

  it('pairs the reverse split ratio with its recency', () => {
    expect(buildInfoView(base, 5.0)!.reverseSplit).toEqual({ ratio: 12.0, daysAgo: 45 });
    expect(buildInfoView({ ...base, reverse_split_ratio: null }, 5.0)!.reverseSplit).toBeNull();
  });

  it('scores the float disagreement between the sources', () => {
    expect(buildInfoView(base, 5.0)!.floatDisagreePercent).toBeCloseTo(50);
  });

  it('assembles the pullback view with its tone', () => {
    const view = buildInfoView(base, 5.0)!;
    expect(view.pullback).toEqual({
      depthPercent: 38,
      volumeRatio: 0.4,
      bars: 4,
      legPercent: 20,
      tone: 'healthy',
    });
    expect(buildInfoView({ ...base, pullback_depth_pct: null }, 5.0)!.pullback).toBeNull();
  });
});

describe('borrowStatus', () => {
  it('buckets the IBKR magnitude the way TWS colours it', () => {
    expect(borrowStatus(3.0)).toBe('easy');
    expect(borrowStatus(2.5)).toBe('locate');
    expect(borrowStatus(1.5)).toBe('locate');
    expect(borrowStatus(1.49)).toBe('none');
  });

  it('is null with nothing reported', () => {
    expect(borrowStatus(null)).toBeNull();
  });
});


describe('budgetTone', () => {
  it('is ok with at least half the window left', () => {
    expect(budgetTone(0, 200)).toBe('ok');
    expect(budgetTone(100, 200)).toBe('ok');
  });

  it('warns from half down to a fifth remaining', () => {
    expect(budgetTone(101, 200)).toBe('warn');
    expect(budgetTone(160, 200)).toBe('warn');
  });

  it('is hot below a fifth remaining', () => {
    expect(budgetTone(161, 200)).toBe('hot');
    expect(budgetTone(200, 200)).toBe('hot');
    expect(budgetTone(59, 60)).toBe('hot');
  });

  it('treats a missing limit as hot', () => {
    expect(budgetTone(0, 0)).toBe('hot');
  });
});

describe('buildBands', () => {
  function bands(values: Record<string, number>, price: number, theme: 'light' | 'dark' = 'light') {
    const specs = Object.keys(values).map((id) => spec({ id, label: id.toUpperCase() }));
    const levels = buildKeyLevels(specs, values, {}, theme, price);
    return buildBands(clusterLevels(levels, price), theme);
  }

  it('shades a shelf from its lowest member to its highest', () => {
    const [band] = bands({ a: 50, b: 50.05, c: 50.1 }, 40);
    expect(band).toBeDefined();
    expect(band!.low).toBeCloseTo(50);
    expect(band!.high).toBeCloseTo(50.1);
  });

  it('leaves a lone level unshaded', () => {
    // One level is a line. Shading it would invent a thickness the data
    // does not have.
    expect(bands({ a: 50, b: 80, c: 20 }, 40)).toHaveLength(0);
  });

  it('carries the band colour with an alpha so candles read through it', () => {
    const [band] = bands({ a: 50, b: 50.05 }, 40);
    expect(band).toBeDefined();
    expect(band!.color).toMatch(/^rgba\(/);
    const alpha = Number(band!.color.split(',').pop()!.replace(')', '').trim());
    expect(alpha).toBeGreaterThan(0);
    expect(alpha).toBeLessThan(0.5);
  });

  it('tints the nearest band overhead violet, not a candle colour', () => {
    const [band] = bands({ a: 50, b: 50.05 }, 40);
    expect(band).toBeDefined();
    expect(band!.color).toBe('rgba(130, 80, 223, 0.16)');
  });

  it('recedes a band that is neither the nearest above nor below', () => {
    const all = bands({ a: 50, b: 50.05, c: 90, d: 90.05, e: 20 }, 40);
    const distant = all.find((band) => band.low > 80)!;
    const nearest = all.find((band) => band.low < 60)!;
    const alphaOf = (c: string) => Number(c.split(',').pop()!.replace(')', '').trim());
    expect(alphaOf(distant.color)).toBeLessThan(alphaOf(nearest.color));
  });
});

describe('buildDilutionView', () => {
  const summary = (overrides: Partial<DilutionSummary> = {}): DilutionSummary => ({
    tone: 'serial',
    warrant_overhang: 0.89,
    warrant_strike: 3.0,
    runway_months: 5.6,
    reasons: ['warrants 89% of shares outstanding', '5.6 months of cash at current burn'],
    ...overrides,
  });

  it('says nothing about a clean company', () => {
    // An ordinary large cap should cost the strip no width at all.
    expect(buildDilutionView(summary({ tone: 'clean' }), 4)).toBeNull();
  });

  it('says nothing without a read', () => {
    expect(buildDilutionView(null, 4)).toBeNull();
    expect(buildDilutionView(undefined, 4)).toBeNull();
  });

  it('flags warrants in the money against the live price', () => {
    const view = buildDilutionView(summary(), 4.1)!;
    expect(view.warrantsInTheMoney).toBe(true);
    expect(view.label).toBe('W 89% ITM');
  });

  it('drops the ITM marker below the strike', () => {
    const view = buildDilutionView(summary(), 2.5)!;
    expect(view.warrantsInTheMoney).toBe(false);
  });

  it('cannot judge the strike without a price', () => {
    const view = buildDilutionView(summary(), null)!;
    expect(view.warrantsInTheMoney).toBeNull();
  });

  it('ranks by how soon the supply can arrive', () => {
    // Out of the money, the warrants are latent; five months of cash means an
    // offering is coming regardless of where the stock trades.
    expect(buildDilutionView(summary(), 2.5)!.label).toBe('CASH 5.6MO');
    // With the runway comfortable, the overhang is the thing worth saying.
    expect(buildDilutionView(summary({ runway_months: 30 }), 2.5)!.label).toBe('W 89%');
  });

  it('falls back to the runway when there are no warrants', () => {
    const view = buildDilutionView(
      summary({ warrant_overhang: null, warrant_strike: null, runway_months: 4.2 }),
      4,
    )!;
    expect(view.label).toBe('CASH 4.2MO');
  });

  it('prefers in-the-money warrants even over an urgent runway', () => {
    // Warrants that can be exercised and sold today outrank an offering that
    // is still weeks away.
    const view = buildDilutionView(summary({ runway_months: 2 }), 4.1)!;
    expect(view.label).toBe('W 89% ITM');
  });

  it('names the tone when nothing else is quantified', () => {
    const view = buildDilutionView(
      summary({
        tone: 'heavy',
        warrant_overhang: null,
        warrant_strike: null,
        runway_months: null,
      }),
      4,
    )!;
    expect(view.label).toBe('HEAVY');
  });

  it('ignores a warrant overhang too small to matter', () => {
    const view = buildDilutionView(
      summary({ tone: 'watch', warrant_overhang: 0.04, runway_months: null }),
      4.1,
    )!;
    expect(view.label).toBe('WATCH');
  });

  it('carries every reason for the tooltip', () => {
    const view = buildDilutionView(summary(), 4.1)!;
    expect(view.detail).toContain('89% of shares outstanding');
    expect(view.detail).toContain('5.6 months of cash');
  });
});

describe('dilutionWorseThan', () => {
  it('ranks the tones', () => {
    expect(dilutionWorseThan('serial', 'heavy')).toBe(true);
    expect(dilutionWorseThan('heavy', 'watch')).toBe(true);
    expect(dilutionWorseThan('watch', 'clean')).toBe(true);
    expect(dilutionWorseThan('clean', 'watch')).toBe(false);
    expect(dilutionWorseThan('heavy', 'heavy')).toBe(false);
  });
});


/**
 * Headroom.
 *
 * The ladder makes the next level readable; this states it. Part of the
 * decision it feeds is taken before the entry — a runner with a moving
 * average sitting just above is a base hit whatever the setup looks like,
 * and one with nothing overhead is worth laddering into.
 *
 * The fixture puts the price at 10 with a 20-day average at 10.40, a
 * pre-market high at 12.50, a 52-week high at 18.00 that is switched off,
 * and yesterday's close below at 9.80.
 */
describe('headroom', () => {
  const at = (price: number) =>
    headroom(buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', price), price);

  it('names the nearest level overhead', () => {
    const view = at(10)!;
    expect(view.level?.label).toBe('1D SMA 20');
    expect(view.percent).toBeCloseTo(4);
    expect(view.tone).toBe('clear');
  });

  it('calls it capped when the target costs more to reach than it pays', () => {
    // 10.30 to a 10.40 average is under 1%: there is no base hit in it once
    // the round trip is paid for.
    expect(at(10.3)!.tone).toBe('capped');
  });

  it('skips a level the trader has switched off', () => {
    // The 52-week high at 18.00 is hidden, so it is not the thing in the way
    // — but the pre-market high above the average still is.
    const view = headroom(
      buildKeyLevels(SPECS, VALUES, { ...VISIBILITY, d_sma20: false }, 'light', 10),
      10,
    );
    expect(view!.level?.label).toBe('PM High');
  });

  it('reports blue sky with nothing left overhead', () => {
    const view = at(20)!;
    expect(view.tone).toBe('blue-sky');
    expect(view.level).toBeNull();
  });

  it('does not mistake missing levels for open sky', () => {
    expect(headroom([], 10)).toBeNull();
  });

  it('is silent without a price to measure from', () => {
    expect(headroom(buildKeyLevels(SPECS, VALUES, VISIBILITY, 'light', null), null)).toBeNull();
  });

  it('ignores a level a thousand percent up', () => {
    // A split-adjusted all-time high compounds every reverse split into
    // itself. It belongs in the ladder as context, never as the next thing
    // in the way.
    const levels = buildKeyLevels(
      SPECS,
      { ...VALUES, pm_high: 900_000, d_sma20: 900_000 },
      VISIBILITY,
      'light',
      10,
    );
    expect(headroom(levels, 10)!.tone).toBe('blue-sky');
  });
});
