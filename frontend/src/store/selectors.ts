/**
 * Derived views.
 *
 * Pure functions over state so the numbers a trader acts on are unit-testable
 * without rendering anything.
 */

import type { PriceBand } from '@/chart/bands';
import { computeChange, daysUntil, percentDistance, type Change } from '@/lib/format';
import { sessionView } from '@/lib/session';
import type {
  DilutionSummary,
  DilutionTone,
  IndicatorSpec,
  InfoMessage,
  QuoteMessage,
  WireBar,
} from '@/types/protocol';

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

// ── headroom ───────────────────────────────────────────────────────────

/**
 * The next thing in the way, and how much room there is before it.
 *
 * The daily chart is not background here — it is the variable that selects
 * which regime the trade is in. Clear overhead and a runner has somewhere to
 * go, so it is worth laddering into and holding; a 200-day moving average
 * sitting just above and the same setup is a base hit at best, because the
 * move stops there. Both are decisions about size and target taken before
 * the entry, off one number, and the ladder in the sidebar makes them
 * readable but never states them.
 *
 * Hidden levels are excluded. The ladder is the trader's own account of what
 * counts as resistance on this name, and naming a level they have switched
 * off as the thing in the way would contradict it.
 */
export type HeadroomTone = 'blue-sky' | 'clear' | 'capped';

export interface HeadroomView {
  /** The nearest level above the price; null in blue sky. */
  level: KeyLevel | null;
  percent: number | null;
  tone: HeadroomTone;
}

/**
 * Under this much room there is no base hit in the trade.
 *
 * A 15–20 cent target on a $5–10 name is 2–4%, and the round trip costs 10–20
 * cents of slippage before it. Three percent is where the target stops
 * covering its own execution.
 */
export const CAPPED_HEADROOM_PERCENT = 3;

export function headroom(levels: KeyLevel[], price: number | null): HeadroomView | null {
  // No levels at all is missing data, not open sky.
  if (price == null || levels.length === 0) return null;

  // A level a thousand percent up is context, not a ceiling — see
  // `FAR_LEVEL_PERCENT`. Naming it as the next resistance would be a lie
  // told with a real number.
  const candidates = levels.filter(
    (level) => level.visible && !isFarLevel(level.distancePercent),
  );
  const nearest = nearestLevels(candidates).above;

  if (nearest === null) return { level: null, percent: null, tone: 'blue-sky' };
  const percent = nearest.distancePercent;
  return {
    level: nearest,
    percent,
    tone: percent != null && percent < CAPPED_HEADROOM_PERCENT ? 'capped' : 'clear',
  };
}

/** The id the all-time high goes by everywhere — store, panel, chart. */
export const ATH_LEVEL_ID = 'ath';

/**
 * Past this distance a level is out of reach and reads as such.
 *
 * Ten times the price is not a target, a stop or a magnet; it is context. It
 * arises honestly — a dollar stock that once traded at fifty — and it arises
 * from broken data, because a split-adjusted all-time high compounds every
 * reverse split into itself: CHAI prints $93,250,082 against a $0.38 tape.
 * Both stay in the ladder, quiet, at the top where they belong. Neither is
 * drawn on the chart, where a line that far out is off-screen in every
 * session and only puts a stray tag on the axis.
 */
export const FAR_LEVEL_PERCENT = 1000;

export function isFarLevel(distancePercent: number | null | undefined): boolean {
  return distancePercent != null && distancePercent > FAR_LEVEL_PERCENT;
}

/**
 * The all-time high as a key level.
 *
 * It arrives on the info stream rather than as a per-bar series, so it is not
 * one of the levels the backend streams — but it is the same kind of thing as
 * the 52-week high sitting next to it in the list, and reading it there is
 * how it gets used: sorted into the ladder, with the distance to it, and an
 * eye to take it off the chart. That is why it is no longer a field in the
 * panel above.
 *
 * It is listed however far away it is, including when reverse splits have put
 * it millions of times above the tape. The ladder marks it out of reach
 * rather than dropping it (see FAR_LEVEL_PERCENT): silence would be
 * indistinguishable from the provider never answering, and "the all-time high
 * is meaningless on this name" is itself worth knowing.
 */
export function athLevel(
  info: Pick<InfoMessage, 'all_time_high'> | null,
  visibility: Record<string, boolean>,
  referencePrice: number | null,
): KeyLevel | null {
  const value = info?.all_time_high ?? null;
  if (value == null || !Number.isFinite(value) || value <= 0) return null;

  const distancePercent = percentDistance(referencePrice, value);
  return {
    id: ATH_LEVEL_ID,
    label: 'ATH',
    color: NEUTRAL_LEVEL.dark,
    value,
    distancePercent,
    side: sideOf(distancePercent),
    visible: visibility[ATH_LEVEL_ID] ?? true,
    group: 'key_levels',
  };
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

  // The return type is annotated rather than inferred: `emphasis` starts at
  // 'normal' and `markNearest` reassigns it, so without this the literal
  // narrows to 'normal' and the reassignment does not typecheck.
  const clusters = groups.map((members): LevelCluster => {
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
      emphasis: 'normal',
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
  /** This one candle's move: close against the previous bar's close. */
  barChange: Change | null;
  /** Change against the previous session's close — the gap, intraday. */
  sessionChange: Change | null;
  extendedHours: boolean;
  /** Cumulative session volume as of this bar. */
  sessionVolume: number | null;
  /** The day's pace at this bar: session volume so far over the 10-day avg. */
  rvolAtBar: number | null;
  /** Time-matched RVOL: this window against the same window on prior days. */
  windowRvol: number | null;
  /** Float turns as of this bar: session volume so far over the float. */
  rotationAtBar: number | null;
  /** Distance from VWAP at this bar, % — the polarity read, at that moment. */
  vwapDeltaPercent: number | null;
  /** Market cap at this bar's close: shares outstanding × close. */
  marketCapAtBar: number | null;
}

export function buildOhlcv(readout: Readout | null, info?: InfoMessage | null): OhlcvView | null {
  if (!readout) return null;
  const { bar, previousClose, values, sessionVolume } = readout;
  const prevDayClose = values['prev_day_close'];
  const vwap = values['vwap'];
  const avgVol = info?.avg_vol_10d;
  const floatShares = info?.float_shares;

  return {
    bar,
    barChange: previousClose != null ? computeChange(bar.c, previousClose) : null,
    sessionChange: prevDayClose != null ? computeChange(bar.c, prevDayClose) : null,
    extendedHours: bar.x === 1,
    sessionVolume: sessionVolume ?? null,
    rvolAtBar:
      sessionVolume != null && avgVol != null && avgVol > 0 ? sessionVolume / avgVol : null,
    // Server-computed off the 20-day minute base and stamped per bar, so it
    // exists on the 10-second chart too (stepping once a minute there).
    windowRvol: values['wrvol'] ?? null,
    rotationAtBar:
      sessionVolume != null && floatShares != null && floatShares > 0
        ? sessionVolume / floatShares
        : null,
    vwapDeltaPercent: vwap != null && vwap > 0 ? ((bar.c - vwap) / vwap) * 100 : null,
    marketCapAtBar:
      info?.shares_outstanding != null && info.shares_outstanding > 0
        ? info.shares_outstanding * bar.c
        : null,
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
  /**
   * Market cap on the previous close: shares outstanding × yesterday's close.
   *
   * The day's reference, and deliberately fixed for the whole session — it is
   * what the name was worth before the move, so "a $12M company up 50%" has
   * one meaning at 09:31 and the same meaning at 15:59. Its moving twin is
   * the current cap in the panel beside it.
   */
  marketCap: number | null;
  /** TradingView's own snapshot, the fallback with no share count. */
  reportedMarketCap: number | null;
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
  /**
   * The session's LULD band width — 10 or 20 percent, or the fixed cents
   * below $0.75. Fixed by last night's close, so it is a property of the
   * name for the whole day rather than of the moment.
   */
  haltBandPercent: number | null;
  haltBandCents: number | null;
  /** Distance from the last price to each band, in dollars. */
  haltUpDistance: number | null;
  haltDownDistance: number | null;
  /** Headroom to each band as a percentage of the last price. */
  haltUpPercent: number | null;
  haltDownPercent: number | null;
  /** Days since listing, when young enough to matter. */
  listedDays: number | null;
  /** Days until the next scheduled report; negative once it has passed. */
  earningsInDays: number | null;
  borrow: BorrowStatus | null;
  shortableShares: number | null;
  /** Halted right now. */
  halted: boolean;
  haltsToday: number;
  /** Live only inside the fifteen minutes the reopen study covers. */
  reopen: ReopenView | null;
  /** The latest reverse split: 10 means 1-for-10, `daysAgo` its recency. */
  reverseSplit: { ratio: number; daysAgo: number } | null;
  yahooFloat: number | null;
  /** Divergence between the two float sources; null unless both answered. */
  floatDisagreePercent: number | null;
  pullback: PullbackView | null;
  /** Float exceeding shares outstanding — stale or broken reference data. */
  floatSuspect: boolean;
  description: string;
  exchange: string;
  sector: string;
}

/**
 * IBKR's shortable magnitude, bucketed the way TWS colours it: above 2.5
 * there is stock to borrow, 1.5–2.5 needs a locate, below 1.5 there is none.
 */
export type BorrowStatus = 'easy' | 'locate' | 'none';

export function borrowStatus(shortable: number | null): BorrowStatus | null {
  if (shortable == null) return null;
  if (shortable > 2.5) return 'easy';
  if (shortable >= 1.5) return 'locate';
  return 'none';
}

/** Show the IPO badge for listings younger than this. */
export const RECENT_IPO_DAYS = 90;

/** Show the reverse-split badge inside this window — the diluter's year. */
export const RECENT_SPLIT_DAYS = 365;

/** Sources disagreeing on the float by at least this much get the badge. */
export const FLOAT_DISAGREE_PERCENT = 25;

/** The all-time high, or null when it is too far above the tape to draw. */
export function plottableAth(
  allTimeHigh: number | null,
  lastPrice: number | null,
): number | null {
  if (allTimeHigh == null || !Number.isFinite(allTimeHigh) || allTimeHigh <= 0) return null;
  if (isFarLevel(percentDistance(lastPrice, allTimeHigh))) return null;
  return allTimeHigh;
}

/**
 * How far the two float sources diverge, as a percentage of the smaller.
 * Null unless both actually answered — one source is silence, not agreement.
 */
export function floatDisagreement(
  tv: number | null,
  yahoo: number | null,
): number | null {
  if (tv == null || yahoo == null || tv <= 0 || yahoo <= 0) return null;
  return (Math.abs(tv - yahoo) / Math.min(tv, yahoo)) * 100;
}

// ── pullback quality ───────────────────────────────────────────────────

export interface PullbackView {
  depthPercent: number;
  volumeRatio: number | null;
  bars: number;
  legPercent: number;
  tone: PullbackTone;
}

/**
 * The playbook's first-pullback judgment, from the raw measurements.
 *
 * `failed` past the 78.6% fib — the deepest retrace that still counts as
 * holding; `stale` at ten minutes off the high — that is a downtrend with a
 * story; `healthy` when the top half of the leg holds AND volume has dried
 * to half the rally's pace; anything in between is merely `ok`.
 */
export type PullbackTone = 'healthy' | 'ok' | 'failed' | 'stale';

export function pullbackTone(
  depthPercent: number,
  volumeRatio: number | null,
  bars: number,
): PullbackTone {
  if (depthPercent >= 78.6) return 'failed';
  if (bars >= 10) return 'stale';
  if (depthPercent <= 50 && volumeRatio != null && volumeRatio <= 0.5) return 'healthy';
  return 'ok';
}

// ── the reopen window ──────────────────────────────────────────────────

/**
 * The fifteen minutes after a halt lifts.
 *
 * This is the one condition in the playbook with a large measured effect
 * behind it. Across 66,785 reopens the following fifteen minutes averaged
 * +0.33%; the 2,805 that reopened before 10:00 ET averaged **+3.10%**
 * (median +2.44%, t = 9.2, 61% up). The same study found the sign flips on a
 * name that has already run: the 3,121 reopens on stocks extended 30–100%
 * averaged **−1.09%** (t = −4.6). A wide 20% band beat a narrow 10% one,
 * +0.66% against +0.19% — real but small next to the other two.
 *
 * None of that has ever been traded, and nothing here says to. The read
 * states which of the measured conditions hold right now and gets out of the
 * way; `extended` is the one that says something happened, because it is the
 * only bucket that measured negative.
 */
export const REOPEN_WINDOW_SECONDS = 15 * 60;

/** Reopens after this New York minute fall outside the measured cohort. */
export const REOPEN_LATE_MINUTE = 10 * 60;

/** Day change at or above this put the reopen in the negative bucket. */
export const REOPEN_EXTENDED_PERCENT = 30;

/** The wide LULD tier, which the study mildly preferred. */
const WIDE_BAND_PERCENT = 20;

export type ReopenTone = 'aligned' | 'late' | 'extended';

export interface ReopenView {
  /** Seconds since the tape came back. */
  secondsSince: number;
  tone: ReopenTone;
  /** On the 20% band rather than the 10% one. */
  wideBand: boolean;
}

/**
 * Both clocks here are the server's — `generated_at` and the resume stamp
 * come from the same process — so a client whose clock is minutes out still
 * reads the right elapsed time.
 *
 * The time-of-day test runs against the *resume*, not against now: the
 * cohort is defined by when the stock came back, and a reopen at 09:58 stays
 * in it while its window plays out past ten.
 */
export function reopenRead(info: InfoMessage, changePercent: number | null): ReopenView | null {
  if (info.halted || info.halt_resumed_at == null) return null;
  const secondsSince = info.generated_at - info.halt_resumed_at;
  if (secondsSince < 0 || secondsSince > REOPEN_WINDOW_SECONDS) return null;

  const resumedMinute = sessionView(new Date(info.halt_resumed_at * 1000)).minutes;
  const extended = changePercent != null && changePercent >= REOPEN_EXTENDED_PERCENT;
  return {
    secondsSince,
    tone: extended ? 'extended' : resumedMinute >= REOPEN_LATE_MINUTE ? 'late' : 'aligned',
    wideBand: info.halt_band_pct === WIDE_BAND_PERCENT,
  };
}

export function buildInfoView(info: InfoMessage | null, lastPrice: number | null): InfoView | null {
  if (!info) return null;
  const sessionChange =
    lastPrice != null && info.prev_close != null && info.prev_close !== 0
      ? computeChange(lastPrice, info.prev_close)
      : null;
  return {
    floatShares: info.float_shares,
    // Derived from the previous close rather than taken from TradingView,
    // because TradingView's snapshot is priced at whenever it last refreshed
    // — which on a runner is neither yesterday nor now. The reported figure
    // stays as the fallback for names with no share count.
    marketCap:
      info.shares_outstanding != null && info.shares_outstanding > 0 && info.prev_close != null
        ? info.shares_outstanding * info.prev_close
        : info.market_cap,
    reportedMarketCap: info.market_cap,
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
    haltBandPercent: info.halt_band_pct,
    haltBandCents: info.halt_band_cents,
    haltUpDistance:
      info.halt_up != null && lastPrice != null ? info.halt_up - lastPrice : null,
    haltDownDistance:
      info.halt_down != null && lastPrice != null ? lastPrice - info.halt_down : null,
    haltUpPercent:
      info.halt_up != null && lastPrice != null && lastPrice > 0
        ? ((info.halt_up - lastPrice) / lastPrice) * 100
        : null,
    haltDownPercent:
      info.halt_down != null && lastPrice != null && lastPrice > 0
        ? ((lastPrice - info.halt_down) / lastPrice) * 100
        : null,
    listedDays: info.listed_days,
    earningsInDays: daysUntil(info.earnings_next, info.generated_at),
    borrow: borrowStatus(info.shortable),
    shortableShares: info.shortable_shares,
    halted: info.halted,
    haltsToday: info.halts_today,
    reopen: reopenRead(info, sessionChange?.percent ?? null),
    reverseSplit:
      info.reverse_split_ratio != null && info.reverse_split_days != null
        ? { ratio: info.reverse_split_ratio, daysAgo: info.reverse_split_days }
        : null,
    yahooFloat: info.yahoo_float,
    floatDisagreePercent: floatDisagreement(info.float_shares, info.yahoo_float),
    pullback:
      info.pullback_depth_pct != null && info.pullback_bars != null && info.pullback_leg_pct != null
        ? {
            depthPercent: info.pullback_depth_pct,
            volumeRatio: info.pullback_vol_ratio,
            bars: info.pullback_bars,
            legPercent: info.pullback_leg_pct,
            tone: pullbackTone(info.pullback_depth_pct, info.pullback_vol_ratio, info.pullback_bars),
          }
        : null,
    floatSuspect:
      info.float_shares != null &&
      info.shares_outstanding != null &&
      info.float_shares > info.shares_outstanding,
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
      spec.pane === 'price' &&
      !spec.readout_only &&
      !isKeyLevel(spec) &&
      spec.timeframes[timeframe] !== undefined,
  );
}

export function levelIndicators(specs: IndicatorSpec[], timeframe: string): IndicatorSpec[] {
  return specs.filter((spec) => isKeyLevel(spec) && spec.timeframes[timeframe] !== undefined);
}

export function paneIndicators(specs: IndicatorSpec[], timeframe: string): IndicatorSpec[] {
  return specs.filter(
    (spec) =>
      spec.pane !== 'price' && !spec.readout_only && spec.timeframes[timeframe] !== undefined,
  );
}

// ── dilution ───────────────────────────────────────────────────────────

/**
 * The supply read, in the idiom the strip already uses for spread, pullback
 * and borrow: a word beside the numbers, never instead of them.
 *
 * `clean` says nothing and renders nothing — an ordinary large cap should
 * cost the strip no width at all. Everything above it earns its place.
 */
export interface DilutionView {
  /** Never `clean`: a clean read produces no chip at all. */
  tone: Exclude<DilutionTone, 'clean'>;
  /** The compact chip text, e.g. `W 89%` or `CASH 5.6M`. */
  label: string;
  /** Every reason, for the title attribute. */
  detail: string;
  /** Warrants trading above their strike, so exercise is live supply.
   *  Decided here because this is where the live price is. */
  warrantsInTheMoney: boolean | null;
}

const DILUTION_RANK: Record<DilutionTone, number> = {
  clean: 0,
  watch: 1,
  heavy: 2,
  serial: 3,
};

/**
 * Build the chip, or null when there is nothing worth saying.
 *
 * The label picks the single worst fact rather than concatenating them: the
 * strip has room for one chip, and "89% warrants" stops a trade faster than a
 * three-item list nobody reads at speed. The rest go to the tooltip.
 */
export function buildDilutionView(
  dilution: DilutionSummary | null | undefined,
  lastPrice: number | null,
): DilutionView | null {
  if (!dilution || dilution.tone === 'clean') return null;

  const inTheMoney =
    dilution.warrant_strike != null && lastPrice != null
      ? lastPrice > dilution.warrant_strike
      : null;

  return {
    tone: dilution.tone,
    label: dilutionLabel(dilution, inTheMoney),
    detail: dilution.reasons.join(' · '),
    warrantsInTheMoney: inTheMoney,
  };
}

/**
 * The single worst fact, ranked by how soon the supply can reach the tape:
 *
 *   1. warrants in the money — exercisable and sellable today
 *   2. under six months of cash — an offering is coming whatever the price
 *   3. a large overhang out of the money — supply that arms if it runs
 *   4. under eighteen months of cash — eventual
 */
function dilutionLabel(dilution: DilutionSummary, inTheMoney: boolean | null): string {
  const overhang = dilution.warrant_overhang;
  const runway = dilution.runway_months;

  if (overhang != null && overhang >= 0.1 && inTheMoney) {
    return `W ${Math.round(overhang * 100)}% ITM`;
  }
  if (runway != null && runway < 6) return `CASH ${runway.toFixed(1)}MO`;
  if (overhang != null && overhang >= 0.1) return `W ${Math.round(overhang * 100)}%`;
  if (runway != null && runway < 18) return `CASH ${runway.toFixed(1)}MO`;
  return dilution.tone.toUpperCase();
}

/** Whether `a` is a worse read than `b` — for sorting, and for tests. */
export function dilutionWorseThan(a: DilutionTone, b: DilutionTone): boolean {
  return DILUTION_RANK[a] > DILUTION_RANK[b];
}
