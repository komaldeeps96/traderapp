import { describe, expect, it } from 'vitest';

import type { WireBar } from '@/types/protocol';

import { dollarLevels } from './dollarGrid';

function bar(low: number, high: number): WireBar {
  return { t: 0, o: low, h: high, l: low, c: high, v: 100, n: 1 };
}

describe('dollarLevels', () => {
  it('draws every half dollar across a narrow range, padded by half a dollar', () => {
    expect(dollarLevels([bar(9.8, 10.3)])).toEqual({ prices: [9.5, 10, 10.5], low: 9.8, high: 10.3 });
  });

  it('widens the step until the grid stops being wallpaper', () => {
    const levels = dollarLevels([bar(100, 150)])!;
    expect(levels.prices).toEqual([100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 150]);
  });

  it('draws no line at or below zero on a sub-dollar ticker', () => {
    expect(dollarLevels([bar(0.3, 0.4)])!.prices).toEqual([0.5]);
  });

  it('has nothing to draw without bars', () => {
    expect(dollarLevels([])).toBeNull();
  });
});
