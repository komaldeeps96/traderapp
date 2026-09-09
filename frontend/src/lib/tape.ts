/**
 * The time-and-sales window: what a row means, and what can be filtered out.
 *
 * Five verdicts, in the two-greens-two-reds convention every direct-access
 * platform uses:
 *
 *     above   somebody paid through the offer          strong green
 *     ask     a buyer lifted the offer                 green
 *     mid     neither side gave way                    no tint
 *     bid     a seller hit the bid                     red
 *     below   somebody sold through the bid            strong red
 *
 * The verdict is the server's — see `backend/app/domain/tape.py`.
 *
 * The filters are a size floor, a block threshold that emphasises rather than
 * hides, a switch for irregular prints, same-price aggregation, and a freeze.
 * Everything here is pure so tests assert on rules rather than pixels.
 */

import type { Aggressor, TapePrint } from '@/types/protocol';

/**
 * Prints kept in the store, per symbol — deep enough to scroll back through the
 * burst after a halt lifts. The server holds more (`tape.buffer`).
 */
export const TAPE_KEPT = 400;

/**
 * Rows actually rendered. Past this nobody is reading — they are scrolling —
 * and a fast name would otherwise reconcile hundreds of rows every second.
 */
export const TAPE_RENDERED = 200;

/**
 * How far apart two prints can be and still merge into one aggregated row.
 *
 * One order sliced across five venues lands inside milliseconds; a second at
 * the same price half a minute later is a different event, and merging them
 * would invent a block that never traded.
 */
export const TAPE_AGGREGATE_WINDOW_MS = 1_000;

/** Size floors the picker offers. 0 is "everything". */
export const TAPE_MIN_SIZES = [0, 100, 500, 1_000, 5_000] as const;

/** Sizes at or above which a row is called a block and emphasised. */
export const TAPE_BLOCK_SIZES = [500, 1_000, 2_500, 5_000, 10_000] as const;

export interface TapeFilters {
  /** Hide anything smaller. Applied *after* aggregation — see `visiblePrints`. */
  minSize: number;
  /** At or above this a row is emphasised. Never hides anything. */
  blockSize: number;
  /** Drop late reports, average-price blocks and the rest of the irregulars. */
  regularOnly: boolean;
  /** Merge same-price, same-side prints that land together. */
  aggregate: boolean;
  /** Freeze the window. The store keeps filling behind it. */
  paused: boolean;
}

export const DEFAULT_TAPE_FILTERS: TapeFilters = {
  // Everything, by default. IBKR's stream already omits odd lots (see
  // docs/time-and-sales.md), so the tape arrives filtered to round lots and
  // up — putting a floor on top of that by default would hide the ordinary
  // 100-share prints that *are* the tape on a small cap.
  minSize: 0,
  // On a $2 name a thousand shares is $2,000 and worth a glance; ten thousand
  // is the print that turns a head.
  blockSize: 1_000,
  // Shown by default, marked with a dot. They are real volume, and a tape
  // that quietly drops prints is a tape that cannot be trusted for what it
  // does show.
  regularOnly: false,
  aggregate: false,
  paused: false,
};

/** A row after filtering: a print, plus how many prints were folded into it. */
export interface TapeRow extends TapePrint {
  /** 1 for an ordinary print; higher for an aggregated group. */
  n: number;
}

/** True for a print the sale conditions marked as not price-forming. */
export function isIrregular(print: TapePrint): boolean {
  return print.f === 0;
}

/**
 * What the window shows, newest first. The order is load-bearing:
 *
 * 1. **Irregulars first**, so a late report at a stale price cannot merge into
 *    a group of live ones.
 * 2. **Then aggregation**, turning fifty 100-share prints at 2.50 into one
 *    5,000-share row.
 * 3. **Then the size floor**, measuring the row as displayed — filtering first
 *    would throw away every print the group was built from.
 */
export function visiblePrints(
  prints: readonly TapePrint[],
  filters: TapeFilters,
  limit: number = TAPE_RENDERED,
): TapeRow[] {
  const kept = filters.regularOnly ? prints.filter((print) => !isIrregular(print)) : prints;
  const rows = filters.aggregate ? aggregate(kept) : kept.map((print) => ({ ...print, n: 1 }));
  const floored = filters.minSize > 0 ? rows.filter((row) => row.s >= filters.minSize) : rows;
  return floored.slice(0, limit);
}

/**
 * Merge runs of same-price, same-side prints that landed together. Input is
 * newest first, so the group's representative is its newest print and the size
 * is the total that went through at that price.
 */
function aggregate(prints: readonly TapePrint[]): TapeRow[] {
  const rows: TapeRow[] = [];
  for (const print of prints) {
    const open = rows[rows.length - 1];
    if (
      open &&
      open.p === print.p &&
      open.a === print.a &&
      isIrregular(open) === isIrregular(print) &&
      open.t - print.t <= TAPE_AGGREGATE_WINDOW_MS
    ) {
      open.s += print.s;
      open.n += 1;
      continue;
    }
    rows.push({ ...print, n: 1 });
  }
  return rows;
}

/** The tint a row carries. Empty for the two verdicts that carry none. */
export function sideClass(side: Aggressor): string {
  switch (side) {
    case 'above':
      return 'tape-above';
    case 'ask':
      return 'tape-ask';
    case 'bid':
      return 'tape-bid';
    case 'below':
      return 'tape-below';
    default:
      return '';
  }
}

/** Spelled out for the row's tooltip and for screen readers. */
export const SIDE_LABELS: Record<Aggressor, string> = {
  above: 'paid through the offer',
  ask: 'lifted the offer',
  mid: 'inside the spread',
  bid: 'hit the bid',
  below: 'sold through the bid',
  unk: 'no quote standing',
};

export interface TapeBalance {
  /** Shares that crossed the spread upward, over the visible rows. */
  buy: number;
  sell: number;
  /** Shares that took neither side, or had no book to be judged against. */
  neutral: number;
  /** Buy share of the two directional totals, 0-1. Null when neither traded. */
  buyShare: number | null;
}

/**
 * Which way the visible tape leans. Computed over exactly what is on screen,
 * filters included, so it cannot disagree with the rows above it.
 */
export function balance(rows: readonly TapeRow[]): TapeBalance {
  let buy = 0;
  let sell = 0;
  let neutral = 0;
  for (const row of rows) {
    if (row.a === 'ask' || row.a === 'above') buy += row.s;
    else if (row.a === 'bid' || row.a === 'below') sell += row.s;
    else neutral += row.s;
  }
  const directional = buy + sell;
  return { buy, sell, neutral, buyShare: directional > 0 ? buy / directional : null };
}

/**
 * Fold a batch off the wire into the list the window renders.
 *
 * The list is newest first, the wire sends oldest first. Sequences at or below
 * what is held are dropped, absorbing the deliberate overlap between a
 * subscribe's backlog and the first incremental batch.
 */
export function mergePrints(
  held: readonly TapePrint[],
  incoming: readonly TapePrint[],
  reset: boolean,
): TapePrint[] {
  if (reset) return [...incoming].reverse().slice(0, TAPE_KEPT);
  const newest = held[0]?.q ?? 0;
  const fresh = incoming.filter((print) => print.q > newest);
  if (!fresh.length) return held as TapePrint[];
  return [...fresh.reverse(), ...held].slice(0, TAPE_KEPT);
}
