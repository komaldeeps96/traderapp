import { describe, expect, it } from 'vitest';

import type { BarMessage, SnapshotMessage, WireBar } from '@/types/protocol';

import { withBar } from './snapshot';

function bar(t: number, c: number): WireBar {
  return { t, o: c, h: c, l: c, c, v: 100, n: 1, x: 0 };
}

const SNAPSHOT: SnapshotMessage = {
  type: 'snapshot',
  symbol: 'RUN',
  timeframe: '1m',
  bars: [bar(60, 1), bar(120, 2)],
  series: { ema9: [[60, 1], [120, 1.5]] },
  source: 'alpaca',
  delayed: false,
  generated_at: 120,
};

function live(t: number, c: number, ema: number): BarMessage {
  return { type: 'bar', symbol: 'RUN', timeframe: '1m', bar: bar(t, c), series: { ema9: ema } };
}

describe('withBar', () => {
  it('appends a bar for a new period, and its indicator value', () => {
    const next = withBar(SNAPSHOT, live(180, 3, 2));
    expect(next.bars.map((b) => b.t)).toEqual([60, 120, 180]);
    expect(next.series.ema9).toEqual([[60, 1], [120, 1.5], [180, 2]]);
  });

  it('replaces the forming bar rather than adding a second', () => {
    const next = withBar(SNAPSHOT, live(120, 2.4, 1.6));
    expect(next.bars.map((b) => b.c)).toEqual([1, 2.4]);
    expect(next.series.ema9!.at(-1)).toEqual([120, 1.6]);
  });

  it('leaves alone a bar older than the snapshot already carries', () => {
    const next = withBar(SNAPSHOT, live(60, 9, 9));
    expect(next.bars).toEqual(SNAPSHOT.bars);
  });

  it('never edits the snapshot a chart may still be holding', () => {
    const before = SNAPSHOT.bars;
    withBar(SNAPSHOT, live(180, 3, 2));
    expect(SNAPSHOT.bars).toBe(before);
    expect(SNAPSHOT.bars).toHaveLength(2);
  });

  it('starts a series the snapshot did not yet have', () => {
    const next = withBar(SNAPSHOT, { ...live(180, 3, 2), series: { vwap: 2.5 } });
    expect(next.series.vwap).toEqual([[180, 2.5]]);
  });
});
