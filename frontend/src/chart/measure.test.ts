import { describe, expect, it } from 'vitest';

import type { WireBar } from '@/types/protocol';

import { formatDuration, measureStats, type MeasurePoint } from './measure';

function bar(t: number, v: number): WireBar {
  return { t, o: 10, h: 10, l: 10, c: 10, v, n: 1, x: 0 };
}

const BARS = Array.from({ length: 100 }, (_, i) => bar(i * 60, 1000));

function point(index: number, price: number): MeasurePoint {
  return { index, time: index * 60, price };
}

describe('measureStats', () => {
  it('reads the move, the span and the volume of a drag', () => {
    const stats = measureStats(BARS, '1m', point(10, 5.0), point(69, 5.5));
    expect(stats.priceDelta).toBeCloseTo(0.5);
    expect(stats.percent).toBeCloseTo(10);
    expect(stats.bars).toBe(59);
    expect(stats.seconds).toBe(59 * 60);
    // Volume sums the bars inside the selection, endpoints included.
    expect(stats.volume).toBe(60_000);
    expect(stats.direction).toBe('up');
  });

  it('a right-to-left drag measures the same region', () => {
    const forward = measureStats(BARS, '1m', point(10, 5.0), point(69, 5.5));
    const backward = measureStats(BARS, '1m', point(69, 5.5), point(10, 5.0));
    expect(backward.bars).toBe(forward.bars);
    expect(backward.volume).toBe(forward.volume);
    // The price leg keeps the drag's own direction.
    expect(backward.priceDelta).toBeCloseTo(-0.5);
    expect(backward.direction).toBe('down');
  });

  it('duration follows the timeframe, not the wall clock', () => {
    expect(measureStats(BARS, '10s', point(0, 5), point(59, 5)).seconds).toBe(590);
    expect(measureStats(BARS, '5m', point(0, 5), point(59, 5)).seconds).toBe(59 * 300);
  });

  it('a zero-width drag is zero bars and one bar of volume', () => {
    const stats = measureStats(BARS, '1m', point(10, 5.0), point(10, 5.2));
    expect(stats.bars).toBe(0);
    expect(stats.volume).toBe(1000);
  });
});

describe('formatDuration', () => {
  it('uses the largest two units', () => {
    expect(formatDuration(590)).toBe('9m 50s');
    expect(formatDuration(59 * 60)).toBe('59m');
    expect(formatDuration(3_660)).toBe('1h 1m');
    expect(formatDuration(90_000)).toBe('1d 1h');
    expect(formatDuration(0)).toBe('0s');
  });
});
