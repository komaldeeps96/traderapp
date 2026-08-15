/**
 * Derived views.
 *
 * Pure functions over state so the numbers a trader acts on are unit-testable
 * without rendering anything.
 */

import type { PriceBand } from '@/chart/bands';
import { computeChange, percentDistance, type Change } from '@/lib/format';
import type { InfoMessage, IndicatorSpec, QuoteMessage, WireBar } from '@/types/protocol';

import type { Readout } from './useTerminalStore';

export interface KeyLevel {
  id: string;
  label: string;
  color: string;
  value: number;
  /** Signed distance from the reference price, in percent. */
  distancePercent: number | null;
  /** Above the price is potential resistance; below is potential support. */
  side: 'above' | 'below' | 'at';
  visible: boolean;
  group: string;
}

const LEVEL_GROUPS = new Set(['key_levels', 'daily_ma']);

export function isKeyLevel(spec: IndicatorSpec): boolean {
  return LEVEL_GROUPS.has(spec.group);
}

/**
 * Every key level with its distance from the last trade, sorted high to low.
 *
 * Sorting by price rather than by name is what makes this readable while
 * trading: the level directly above the current price is the next thing in
 * the way, and it sits directly above the price row in the list.
 */
export function buildKeyLevels(
  specs: IndicatorSpec[],
  values: Record<string, number>,
  visibility: Record<string, boolean>,
  theme: 'light' | 'dark',
  referencePrice: number | null,
): KeyLevel[] {
  const levels: KeyLevel[] = [];

  for (const spec of specs) {
    if (!isKeyLevel(spec)) continue;
    const value = values[spec.id];
    if (value === undefined || !Number.isFinite(value)) continue;

    const distancePercent = percentDistance(referencePrice, value);
    levels.push({
      id: spec.id,
      label: spec.label,
      color: theme === 'dark' ? spec.color_dark : spec.color,
      value,
      distancePercent,
      side: sideOf(distancePercent),
      visible: visibility[spec.id] ?? true,
      group: spec.group,
    });
  }

  return levels.sort((a, b) => b.value - a.value);
}

function sideOf(distancePercent: number | null): KeyLevel['side'] {
  if (distancePercent == null || distancePercent === 0) return 'at';
  return distancePercent > 0 ? 'above' : 'below';
}

/** The nearest level above and below the price — the immediate target and stop. */
export function nearestLevels(levels: KeyLevel[]): {
  above: KeyLevel | null;
  below: KeyLevel | null;
} {
  let above: KeyLevel | null = null;
  let below: KeyLevel | null = null;

  for (const level of levels) {
    if (level.side === 'above') {
      if (!above || level.value < above.value) above = level;
    } else if (level.side === 'below') {
      if (!below || level.value > below.value) below = level;
    }
  }
  return { above, below };
}

// ── confluence ─────────────────────────────────────────────────────────

export type LevelEmphasis = 'resistance' | 'support' | 'normal';

export interface LevelCluster {
  /** Stable identity: the ids of its members. */
  key: string;
  members: KeyLevel[];
  /** How many levels agree on this price. */
  strength: number;
  /** Mid-price of the band. */
  value: number;
  low: number;
  high: number;
  side: KeyLevel['side'];
  distancePercent: number | null;
  emphasis: LevelEmphasis;
}

/** Levels within this percentage of each other are the same price in practice. */
export const DEFAULT_CLUSTER_TOLERANCE_PERCENT = 0.35;

/**
 * Group levels that sit at effectively the same price.
 *
 * Confluence is the point: five levels stacked within a cent is a far stronger
 * shelf than one level alone, but drawn as five separate lines it reads as
 * noise and five colliding axis labels. Grouping turns that into one band with
 * a strength.
 *
 * Chaining is bounded — a cluster may not span more than twice the tolerance —
 * so a long ladder of near-equal levels cannot collapse into a single
 * meaningless blob.
 */
export function clusterLevels(
  levels: KeyLevel[],
  referencePrice: number | null,
  tolerancePercent = DEFAULT_CLUSTER_TOLERANCE_PERCENT,
): LevelCluster[] {
  if (levels.length === 0) return [];

  const sorted = [...levels].sort((a, b) => b.value - a.value);
  const groups: KeyLevel[][] = [];

  for (const level of sorted) {
    const current = groups.at(-1);
    if (current) {
      const previous = current.at(-1)!;
      const tolerance = (Math.abs(previous.value) * tolerancePercent) / 100;
      const spread = Math.abs(current[0]!.value - level.value);
      const maxSpread = (Math.abs(current[0]!.value) * tolerancePercent * 2) / 100;
      if (Math.abs(previous.value - level.value) <= tolerance && spread <= maxSpread) {
        current.push(level);
        continue;
      }
    }
    groups.push([level]);
  }

  const clusters = groups.map((members) => {
    const values = members.map((member) => member.value);
    const high = Math.max(...values);
    const low = Math.min(...values);
    const value = (high + low) / 2;
    const distancePercent = percentDistance(referencePrice, value);

    return {
      key: members.map((member) => member.id).join('+'),
      members,
      strength: members.length,
      value,
      low,
      high,
      side: sideOf(distancePercent),
      distancePercent,
      emphasis: 'normal' as LevelEmphasis,
    };
  });

  return markNearest(clusters);
}

/**
 * Flag the first band overhead and the first underneath.
 *
 * Those two are what a trade is planned against — the next thing in the way
 * and the first thing that would catch a pullback — so they are the only
 * levels that earn colour.
 */
function markNearest(clusters: LevelCluster[]): LevelCluster[] {
  let resistance: LevelCluster | null = null;
  let support: LevelCluster | null = null;

  for (const cluster of clusters) {
    if (cluster.side === 'above') {
      if (!resistance || cluster.value < resistance.value) resistance = cluster;
    } else if (cluster.side === 'below') {
      if (!support || cluster.value > support.value) support = cluster;
    }
  }

  if (resistance) resistance.emphasis = 'resistance';
  if (support) support.emphasis = 'support';
  return clusters;
}

export interface LevelStyle {
  color: string;
  lineWidth: 1 | 2 | 3 | 4;
  /** Only one label per band, so stacked levels stop colliding on the axis. */
  labelVisible: boolean;
  title: string;
}

const NEUTRAL_LEVEL = { light: '#898781', dark: '#898781' };
// Violet overhead, amber beneath.
//
// Deliberately not red/green: those are the candle colours, so a level in
// them competes with the bars it is drawn over and inherits their meaning.
// These two also clear the three EMA hues (blue, orange, green), and they sit
// on the blue-yellow axis — the one axis red-green colour blindness leaves
// intact, so the pair stays separable where red/green would collapse.
const OVERHEAD = { light: '#8250df', dark: '#a371f7' };
const BENEATH = { light: '#9a6700', dark: '#d29922' };

function paletteFor(cluster: LevelCluster): { light: string; dark: string } {
  return cluster.emphasis === 'resistance'
    ? OVERHEAD
    : cluster.emphasis === 'support'
      ? BENEATH
      : NEUTRAL_LEVEL;
}

/**
 * Turn clusters into per-series chart styling.
 *
 * Colour marks the two actionable bands; everything else stays recessive so
 * those two can be seen at all. Weight no longer counts the members — a
 * multi-level shelf is drawn as a shaded zone instead (see buildBands), which
 * shows where it starts and stops rather than only that it is there.
 */
export function buildLevelStyles(
  clusters: LevelCluster[],
  theme: 'light' | 'dark',
): Record<string, LevelStyle> {
  const styles: Record<string, LevelStyle> = {};

  for (const cluster of clusters) {
    const color = paletteFor(cluster)[theme];

    // One line per band carries the label; the rest go quiet so a five-deep
    // shelf does not stack five colliding tags on the price axis.
    const [lead, ...rest] = cluster.members;
    if (!lead) continue;

    styles[lead.id] = {
      color,
      lineWidth: cluster.emphasis === 'normal' ? 1 : 2,
      labelVisible: true,
      title: cluster.strength > 1 ? `${lead.label} +${cluster.strength - 1}` : lead.label,
    };

    for (const member of rest) {
      styles[member.id] = {
        color,
        lineWidth: 1,
        labelVisible: false,
        title: member.label,
      };
    }
  }

  return styles;
}

/** Fill opacity for a shaded zone — enough to read as an area, not a block. */
const BAND_ALPHA = { resistance: 0.16, support: 0.16, normal: 0.08 } as const;

function withAlpha(hex: string, alpha: number): string {
  const value = hex.replace('#', '');
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * The shaded zones behind the lines.
 *
 * Only clusters holding more than one level get a band: a lone level is a
 * line, and shading it would invent a thickness the data does not have.
 */
export function buildBands(clusters: LevelCluster[], theme: 'light' | 'dark'): PriceBand[] {
  const bands: PriceBand[] = [];

  for (const cluster of clusters) {
    if (cluster.strength < 2 || cluster.high <= cluster.low) continue;
    bands.push({
      low: cluster.low,
      high: cluster.high,
      color: withAlpha(paletteFor(cluster)[theme], BAND_ALPHA[cluster.emphasis]),
    });
  }

  return bands;
}

export interface OhlcvView {
  bar: WireBar;
  barChange: Change | null;
  /** Change against the previous session's close — the gap, intraday. */
  sessionChange: Change | null;
  extendedHours: boolean;
}

export function buildOhlcv(readout: Readout | null): OhlcvView | null {
  if (!readout) return null;
  const { bar, previousClose, values } = readout;
  const prevDayClose = values['prev_day_close'];

  return {
    bar,
    barChange: previousClose != null ? computeChange(bar.c, previousClose) : null,
    sessionChange: prevDayClose != null ? computeChange(bar.c, prevDayClose) : null,
    extendedHours: bar.x === 1,
  };
}

// ── level 1 quote ──────────────────────────────────────────────────────

/**
 * Spread tiers, in the units the decision is made in.
 *
 * Roughly ten cents is where a spread starts to bite on a single-digit
 * stock, twenty is where trades start being declined, and fifty cents is the
 * stated hard ceiling — no trade past it, full stop.
 */
export type SpreadTone = 'tight' | 'ok' | 'wide' | 'untradeable';

export interface QuoteView {
  bid: number;
  ask: number;
  bidSize: number;
  askSize: number;
  mid: number;
  /** Absolute spread in dollars. */
  spread: number;
  /** Spread as a percentage of the mid. */
  spreadPercent: number;
  tone: SpreadTone;
  ageSeconds: number | null;
}

export function buildQuoteView(quote: QuoteMessage | null, now?: number): QuoteView | null {
  if (!quote || quote.bid <= 0 || quote.ask <= 0 || quote.ask < quote.bid) return null;
  const spread = quote.ask - quote.bid;
  const mid = (quote.ask + quote.bid) / 2;
  return {
    bid: quote.bid,
    ask: quote.ask,
    bidSize: quote.bs,
    askSize: quote.as,
    mid,
    spread,
    spreadPercent: mid > 0 ? (spread / mid) * 100 : 0,
    tone: spreadTone(spread),
    ageSeconds: now !== undefined && quote.t > 0 ? Math.max(0, now - quote.t) : null,
  };
}

export function spreadTone(spread: number): SpreadTone {
  if (spread > 0.5) return 'untradeable';
  if (spread > 0.2) return 'wide';
  if (spread > 0.1) return 'ok';
  return 'tight';
}

// ── request budgets ────────────────────────────────────────────────────

/**
 * How much headroom a request window has left.
 *
 * `ok` while at least half remains, `warn` down to a fifth, `hot` below
 * that — hot means the next burst of ticker switches will start queueing
 * behind the limiter.
 */
export type BudgetTone = 'ok' | 'warn' | 'hot';

export function budgetTone(used: number, limit: number): BudgetTone {
  if (limit <= 0) return 'hot';
  // Compare on the used fraction: `1 - 160/200` misses 0.2 by an ulp.
  const usedFraction = used / limit;
  if (usedFraction <= 0.5) return 'ok';
  if (usedFraction <= 0.8) return 'warn';
  return 'hot';
}

// ── info strip ─────────────────────────────────────────────────────────

export interface InfoView {
  floatShares: number | null;
  marketCap: number | null;
  dayVolume: number;
  pmVolume: number;
  avgVol10d: number | null;
  relVol: number | null;
  /** Times the float has turned over today. */
  floatRotation: number | null;
  /** Fraction of the float traded before the open — ≥10% flags a runner. */
  pmFloatRotation: number | null;
  prevClose: number | null;
  /** Gap/day change versus the previous close, from the latest price. */
  sessionChange: Change | null;
  haltUp: number | null;
  haltDown: number | null;
  haltActive: boolean;
  /** Distance from the last price to each band, in dollars. */
  haltUpDistance: number | null;
  haltDownDistance: number | null;
  description: string;
  exchange: string;
  sector: string;
}

export function buildInfoView(info: InfoMessage | null, lastPrice: number | null): InfoView | null {
  if (!info) return null;
  const sessionChange =
    lastPrice != null && info.prev_close != null && info.prev_close !== 0
      ? computeChange(lastPrice, info.prev_close)
      : null;
  return {
    floatShares: info.float_shares,
    marketCap: info.market_cap,
    dayVolume: info.day_volume,
    pmVolume: info.pm_volume,
    avgVol10d: info.avg_vol_10d,
    relVol: info.rel_vol,
    floatRotation: info.float_rotation,
    pmFloatRotation: info.pm_float_rotation,
    prevClose: info.prev_close,
    sessionChange,
    haltUp: info.halt_up,
    haltDown: info.halt_down,
    haltActive: info.halt_active,
    haltUpDistance:
      info.halt_up != null && lastPrice != null ? info.halt_up - lastPrice : null,
    haltDownDistance:
      info.halt_down != null && lastPrice != null ? lastPrice - info.halt_down : null,
    description: info.description,
    exchange: info.exchange,
    sector: info.sector,
  };
}

/** Indicators drawn on the price pane that are not key levels. */
export function overlayIndicators(
  specs: IndicatorSpec[],
  timeframe: string,
): IndicatorSpec[] {
  return specs.filter(
    (spec) =>
      spec.pane === 'price' && !isKeyLevel(spec) && spec.timeframes[timeframe] !== undefined,
  );
}

export function levelIndicators(specs: IndicatorSpec[], timeframe: string): IndicatorSpec[] {
  return specs.filter((spec) => isKeyLevel(spec) && spec.timeframes[timeframe] !== undefined);
}

export function paneIndicators(specs: IndicatorSpec[], timeframe: string): IndicatorSpec[] {
  return specs.filter(
    (spec) => spec.pane !== 'price' && spec.timeframes[timeframe] !== undefined,
  );
}
