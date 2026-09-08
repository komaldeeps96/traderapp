/**
 * The time-and-sales rules.
 *
 * The order the filters run in is the part worth pinning down: aggregation
 * before the size floor is what lets "≥ 500" keep a 5,000-share group built
 * from fifty 100-share prints, and irregulars before aggregation is what
 * stops a late report at a stale price being folded into a live group.
 */

import { describe, expect, it } from 'vitest';

import {
  DEFAULT_TAPE_FILTERS,
  TAPE_AGGREGATE_WINDOW_MS,
  TAPE_KEPT,
  balance,
  isIrregular,
  mergePrints,
  sideClass,
  visiblePrints,
  type TapeFilters,
} from './tape';
import type { Aggressor, TapePrint } from '@/types/protocol';

const T0 = 1_700_000_000_000;

/** Newest-first, as the store holds them: q counts down as t does. */
function print(
  q: number,
  over: Partial<TapePrint> & { a?: Aggressor } = {},
): TapePrint {
  return { q, t: T0 - q * 10, p: 2.5, s: 100, a: 'ask', ...over };
}

function filters(over: Partial<TapeFilters> = {}): TapeFilters {
  return { ...DEFAULT_TAPE_FILTERS, ...over };
}

describe('visiblePrints', () => {
  it('passes everything through by default', () => {
    const prints = [print(3), print(2), print(1)];
    expect(visiblePrints(prints, filters()).map((row) => row.q)).toEqual([3, 2, 1]);
  });

  it('marks every unaggregated row as one print', () => {
    expect(visiblePrints([print(1)], filters())[0]!.n).toBe(1);
  });

  it('drops what is under the size floor', () => {
    const prints = [print(3, { s: 100 }), print(2, { s: 900 }), print(1, { s: 500 })];
    expect(visiblePrints(prints, filters({ minSize: 500 })).map((row) => row.s)).toEqual([
      900, 500,
    ]);
  });

  it('keeps irregular prints unless asked not to', () => {
    const prints = [print(2, { f: 0 }), print(1)];
    expect(visiblePrints(prints, filters())).toHaveLength(2);
    expect(visiblePrints(prints, filters({ regularOnly: true })).map((row) => row.q)).toEqual([1]);
  });

  it('caps what it returns', () => {
    const prints = Array.from({ length: 50 }, (_, i) => print(50 - i));
    expect(visiblePrints(prints, filters(), 10)).toHaveLength(10);
  });
});

describe('aggregation', () => {
  it('merges prints at the same price and side into one row', () => {
    const prints = [print(3), print(2), print(1)];
    const [row] = visiblePrints(prints, filters({ aggregate: true }));
    expect(row!.s).toBe(300);
    expect(row!.n).toBe(3);
  });

  it('keeps the newest print as the row', () => {
    const prints = [print(3), print(2), print(1)];
    const [row] = visiblePrints(prints, filters({ aggregate: true }));
    expect(row!.q).toBe(3);
    expect(row!.t).toBe(T0 - 30);
  });

  it('does not merge across a price', () => {
    const prints = [print(3, { p: 2.51 }), print(2), print(1)];
    const rows = visiblePrints(prints, filters({ aggregate: true }));
    expect(rows.map((row) => row.s)).toEqual([100, 200]);
  });

  it('does not merge across a side', () => {
    const prints = [print(3, { a: 'bid' }), print(2), print(1)];
    expect(visiblePrints(prints, filters({ aggregate: true }))).toHaveLength(2);
  });

  it('does not merge a late report into a live group', () => {
    const prints = [print(3), print(2, { f: 0 }), print(1)];
    const rows = visiblePrints(prints, filters({ aggregate: true }));
    expect(rows.map((row) => row.n)).toEqual([1, 1, 1]);
  });

  it('does not merge across a gap in time', () => {
    // One order sliced across venues lands together; the same price a minute
    // later is a different event and must not be invented into a block.
    const newest = print(2);
    const stale = { ...print(1), t: newest.t - TAPE_AGGREGATE_WINDOW_MS - 1 };
    expect(visiblePrints([newest, stale], filters({ aggregate: true }))).toHaveLength(2);

    // One millisecond inside the window and they are one order again.
    const together = { ...print(1), t: newest.t - TAPE_AGGREGATE_WINDOW_MS };
    expect(visiblePrints([newest, together], filters({ aggregate: true }))).toHaveLength(1);
  });

  it('measures the size floor against the group, not the print', () => {
    const prints = Array.from({ length: 5 }, (_, i) => print(5 - i, { s: 100 }));
    const rows = visiblePrints(prints, filters({ aggregate: true, minSize: 500 }));
    expect(rows).toHaveLength(1);
    expect(rows[0]!.s).toBe(500);

    // Without aggregation the same floor hides every one of them.
    expect(visiblePrints(prints, filters({ minSize: 500 }))).toEqual([]);
  });
});

describe('isIrregular', () => {
  it('is the flag the wire sets and nothing else', () => {
    expect(isIrregular(print(1, { f: 0 }))).toBe(true);
    expect(isIrregular(print(1))).toBe(false);
  });
});

describe('sideClass', () => {
  it('gives each crossing side its own tint', () => {
    expect(sideClass('above')).toBe('tape-above');
    expect(sideClass('ask')).toBe('tape-ask');
    expect(sideClass('bid')).toBe('tape-bid');
    expect(sideClass('below')).toBe('tape-below');
  });

  it('leaves a print that took neither side untinted', () => {
    expect(sideClass('mid')).toBe('');
    expect(sideClass('unk')).toBe('');
  });
});

describe('balance', () => {
  const rows = (...prints: TapePrint[]) => prints.map((row) => ({ ...row, n: 1 }));

  it('counts both greens as buying and both reds as selling', () => {
    const lean = balance(
      rows(
        print(4, { a: 'above', s: 300 }),
        print(3, { a: 'ask', s: 200 }),
        print(2, { a: 'bid', s: 100 }),
        print(1, { a: 'below', s: 100 }),
      ),
    );
    expect(lean.buy).toBe(500);
    expect(lean.sell).toBe(200);
    expect(lean.buyShare).toBeCloseTo(500 / 700);
  });

  it('keeps prints that took neither side out of the ratio', () => {
    const lean = balance(
      rows(print(2, { a: 'mid', s: 900 }), print(1, { a: 'ask', s: 100 })),
    );
    expect(lean.neutral).toBe(900);
    expect(lean.buyShare).toBe(1);
  });

  it('has no opinion with nothing directional on screen', () => {
    expect(balance(rows(print(1, { a: 'unk' }))).buyShare).toBeNull();
    expect(balance([]).buyShare).toBeNull();
  });
});

describe('mergePrints', () => {
  it('reverses a batch so the newest print is first', () => {
    expect(mergePrints([], [print(1), print(2), print(3)], true).map((row) => row.q)).toEqual([
      3, 2, 1,
    ]);
  });

  it('a reset replaces what is held', () => {
    const held = mergePrints([], [print(1), print(2)], true);
    expect(mergePrints(held, [print(7)], true).map((row) => row.q)).toEqual([7]);
  });

  it('appends a live batch on top', () => {
    const held = mergePrints([], [print(1), print(2)], true);
    expect(mergePrints(held, [print(3), print(4)], false).map((row) => row.q)).toEqual([
      4, 3, 2, 1,
    ]);
  });

  it('drops sequences already held', () => {
    const held = mergePrints([], [print(1), print(2), print(3)], true);
    expect(mergePrints(held, [print(2), print(3)], false).map((row) => row.q)).toEqual([3, 2, 1]);
  });

  it('returns the same array when a batch is entirely overlap', () => {
    // Identity is what lets the store skip the render.
    const held = mergePrints([], [print(1)], true);
    expect(mergePrints(held, [print(1)], false)).toBe(held);
  });

  it('keeps the newest and drops the rest past the cap', () => {
    const many = Array.from({ length: TAPE_KEPT + 20 }, (_, i) => print(i + 1));
    const merged = mergePrints([], many, true);
    expect(merged).toHaveLength(TAPE_KEPT);
    expect(merged[0]!.q).toBe(TAPE_KEPT + 20);
  });

  it('caps an appended batch too', () => {
    const held = mergePrints([], Array.from({ length: TAPE_KEPT }, (_, i) => print(i + 1)), true);
    const merged = mergePrints(held, [print(TAPE_KEPT + 1)], false);
    expect(merged).toHaveLength(TAPE_KEPT);
    expect(merged[0]!.q).toBe(TAPE_KEPT + 1);
    expect(merged.at(-1)!.q).toBe(2);
  });
});
