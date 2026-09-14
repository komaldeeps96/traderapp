import { describe, expect, it } from 'vitest';

import { sessionVolumes } from '@/lib/session';
import type { WireBar } from '@/types/protocol';

import { BarData } from './barData';

// 09:30 New York on 5 March 2024.
const OPEN = 1_709_649_000;

function bar(minute: number, close: number, volume = 100): WireBar {
  return { t: OPEN + minute * 60, o: close, h: close, l: close, c: close, v: volume, n: 1 };
}

function loaded(...bars: WireBar[]): BarData {
  const data = new BarData();
  data.load(bars);
  return data;
}

describe('BarData', () => {
  it('keeps its own copy, so a second chart on one snapshot appends nothing to it', () => {
    const snapshot = [bar(0, 10), bar(1, 11)];
    const main = new BarData();
    const mini = new BarData();
    main.load(snapshot);
    mini.load(snapshot);

    main.upsert(bar(2, 12));
    mini.upsert(bar(2, 12));

    expect(main.count).toBe(3);
    expect(main.previousClose(OPEN + 120)).toBe(11);
    expect(snapshot).toHaveLength(2);
  });

  it('refuses a bar older than its last', () => {
    const data = loaded(bar(0, 10), bar(2, 12));
    expect(data.upsert(bar(1, 11))).toBe(false);
    expect(data.count).toBe(2);
  });

  it('knows each series’ newest value whatever order points arrive in', () => {
    const data = loaded(bar(0, 10));
    data.setSeries('ema', [
      [OPEN + 60, 2],
      [OPEN, 1],
    ]);
    data.remember('ema', OPEN + 30, 9);
    expect(data.latestValue('ema')).toBe(2);
    data.remember('ema', OPEN + 120, 3);
    expect(data.latestValue('ema')).toBe(3);
  });

  it('appends a new period and revises one it already holds', () => {
    const data = loaded(bar(0, 10), bar(1, 11));

    data.upsert(bar(2, 12));
    data.upsert(bar(1, 11.5));

    expect(data.count).toBe(3);
    expect(data.at(OPEN + 60)?.c).toBe(11.5);
    expect(data.last()?.c).toBe(12);
    expect(data.indexOf(OPEN + 120)).toBe(2);
  });

  it('reads the previous close, and none for the first bar or an unknown time', () => {
    const data = loaded(bar(0, 10), bar(1, 11));

    expect(data.previousClose(OPEN + 60)).toBe(10);
    expect(data.previousClose(OPEN)).toBeNull();
    expect(data.previousClose(OPEN + 999)).toBeNull();
  });

  it('recomputes session volume once a bar changes', () => {
    const bars = [bar(0, 10, 100), bar(1, 11, 200)];
    const data = loaded(...bars);
    const before = data.sessionVolumeAt(OPEN + 60);
    expect(before).toBe(sessionVolumes(bars)[1]);

    data.upsert(bar(1, 11, 900));

    expect(data.sessionVolumeAt(OPEN + 60)).not.toBe(before);
    expect(data.sessionVolumeAt(OPEN + 60)).toBe(sessionVolumes([bar(0, 10, 100), bar(1, 11, 900)])[1]);
  });

  it('carries a compressed level forward to the time asked for', () => {
    const data = loaded(bar(0, 10), bar(1, 10), bar(2, 10));
    data.setSeries('pm_high', [
      [OPEN, 12],
      [OPEN + 120, 12],
    ]);

    expect(data.valuesAt(OPEN + 60)).toEqual({ pm_high: 12 });
    expect(data.valuesAt(OPEN - 60)).toEqual({});
  });

  it('takes the newest point, not the last one stored', () => {
    const data = loaded(bar(0, 10));
    data.setSeries('ema9', [
      [OPEN, 1],
      [OPEN + 60, 2],
    ]);
    data.remember('ema9', OPEN + 120, 3);
    data.remember('ema9', OPEN + 60, 2.5);

    expect(data.latestValue('ema9')).toBe(3);
    expect(data.latestValues()).toEqual({ ema9: 3 });
    expect(data.pointCounts()).toEqual({ ema9: 3 });
  });

  it('forgets everything on clear', () => {
    const data = loaded(bar(0, 10));
    data.setSeries('ema9', [[OPEN, 1]]);

    data.clear();

    expect(data.count).toBe(0);
    expect(data.last()).toBeNull();
    expect(data.valuesAt(OPEN)).toEqual({});
  });
});
