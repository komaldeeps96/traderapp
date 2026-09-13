/** Key levels: the ladder, its confluence bands, and how the chart styles them. */

import { percentDistance } from '@/lib/format';
import type { IndicatorSpec, InfoMessage } from '@/types/protocol';

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
 * By price rather than by name, so the level directly above the current price
 * is the next thing in the way and sits directly above the price row.
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
 * Clear overhead means a runner has somewhere to go; a moving average just
 * above caps the same setup. It is one number behind decisions about size and
 * target, and the sidebar ladder makes it readable without stating them.
 *
 * Hidden levels are excluded: the ladder is the trader's own account of what
 * counts as resistance on this name.
 */
export type HeadroomTone = 'blue-sky' | 'clear' | 'capped';

export interface HeadroomView {
  /** The nearest level above the price; null in blue sky. */
  level: KeyLevel | null;
  percent: number | null;
  tone: HeadroomTone;
}

/**
 * Under this much room there is no base hit in the trade: three percent is
 * where a 15–20 cent target on a $5–10 name stops covering its own execution.
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
 * Ten times the price is context, not a target — whether honest (a dollar stock
 * that once traded at fifty) or broken (a split-adjusted all-time high
 * compounding every reverse split into itself). Both stay in the ladder, quiet;
 * neither is drawn on the chart, where the line is off-screen every session.
 */
export const FAR_LEVEL_PERCENT = 1000;

export function isFarLevel(distancePercent: number | null | undefined): boolean {
  return distancePercent != null && distancePercent > FAR_LEVEL_PERCENT;
}

/**
 * The all-time high as a key level.
 *
 * Arrives on the info stream rather than as a per-bar series, so it is not one
 * of the streamed levels, but it is used like the 52-week high beside it:
 * sorted into the ladder, with its distance.
 *
 * Listed however far away it is. The ladder marks it out of reach rather than
 * dropping it (see FAR_LEVEL_PERCENT) — silence would be indistinguishable from
 * the provider never answering.
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
 * Confluence is the point: five levels within a cent is a stronger shelf than
 * one, but as five lines it is noise and five colliding axis labels. Grouping
 * makes one band with a strength.
 *
 * Chaining is bounded to twice the tolerance, so a long ladder of near-equal
 * levels cannot collapse into one blob.
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
 * Flag the first band overhead and the first underneath — the next thing in the
 * way and the first thing that would catch a pullback, so the only two that
 * earn colour.
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
// Violet overhead, amber beneath. Not red/green: those are the candle colours,
// so a level in them competes with the bars it is drawn over. These clear the
// three EMA hues (blue, orange, green) and sit on the blue-yellow axis, which
// red-green colour blindness leaves intact.
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
 * Colour marks the two actionable bands; everything else stays recessive.
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

/** The all-time high, or null when it is too far above the tape to draw. */
export function plottableAth(
  allTimeHigh: number | null,
  lastPrice: number | null,
): number | null {
  if (allTimeHigh == null || !Number.isFinite(allTimeHigh) || allTimeHigh <= 0) return null;
  if (isFarLevel(percentDistance(lastPrice, allTimeHigh))) return null;
  return allTimeHigh;
}
