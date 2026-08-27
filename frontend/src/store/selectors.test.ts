import { describe, expect, it } from 'vitest';

import type {
  IndicatorSpec,
  InfoMessage,
  WireBar,
} from '@/types/protocol';

import {
  borrowStatus,
  budgetTone,
  buildBands,
  buildInfoView,
  buildKeyLevels,
  buildLevelStyles,
  buildOhlcv,
  buildQuoteView,
  clusterLevels,
  floatDisagreement,
  levelIndicators,
  nearestLevels,
  overlayIndicators,
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
    listed_days: null,
    shortable: null,
    shortable_shares: null,
    halted: false,
    halts_today: 0,
    reverse_split_ratio: null,
    reverse_split_days: null,
    yahoo_float: null,
    pullback_depth_pct: null,
    pullback_vol_ratio: null,
    pullback_bars: null,
    pullback_leg_pct: null,
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

  it('keeps the reference market cap static', () => {
    // The live per-bar figure lives in the session strip; this one is the
    // snapshot and must not wobble with the tape.
    expect(buildInfoView(info, 5.0)!.marketCap).toBe(40_000_000);
    expect(buildInfoView(info, 6.0)!.marketCap).toBe(40_000_000);
  });

  it('measures the headroom to the all-time high', () => {
    const view = buildInfoView({ ...info, all_time_high: 10.0 }, 5.0)!;
    expect(view.allTimeHigh).toBe(10.0);
    expect(view.athDistancePercent).toBeCloseTo(100);
  });

  it('reads a negative ATH distance in blue sky', () => {
    expect(buildInfoView({ ...info, all_time_high: 4.0 }, 5.0)!.athDistancePercent).toBeCloseTo(
      -20,
    );
  });

  it('leaves the ATH distance out without the reference or a price', () => {
    expect(buildInfoView(info, 5.0)!.athDistancePercent).toBeNull();
    expect(buildInfoView({ ...info, all_time_high: 10.0 }, null)!.athDistancePercent).toBeNull();
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
    listed_days: null,
    shortable: null,
    shortable_shares: null,
    halted: true,
    halts_today: 3,
    reverse_split_ratio: 12.0,
    reverse_split_days: 45,
    yahoo_float: 7_500_000,
    pullback_depth_pct: 38,
    pullback_vol_ratio: 0.4,
    pullback_bars: 4,
    pullback_leg_pct: 20,
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
