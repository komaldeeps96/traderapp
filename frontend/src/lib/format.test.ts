import { describe, expect, it } from 'vitest';

import {
  computeChange,
  formatBarTime,
  formatChange,
  formatCompact,
  formatMoney,
  formatPercent,
  formatPrice,
  percentDistance,
  priceDecimals,
} from './format';

describe('formatPrice', () => {
  it('shows two decimals', () => {
    expect(formatPrice(12.3456)).toBe('12.35');
  });

  it('renders a dash for missing values', () => {
    expect(formatPrice(null)).toBe('—');
    expect(formatPrice(undefined)).toBe('—');
  });

  it('renders a dash rather than NaN', () => {
    expect(formatPrice(Number.NaN)).toBe('—');
  });

  it('honours a custom precision', () => {
    expect(formatPrice(1.23456, 4)).toBe('1.2346');
  });
});

describe('price precision', () => {
  it.each([
    [0.3738, 4],
    [0.0091, 4],
    [4.25, 3],
    [9.999, 3],
    [10, 2],
    [334.86, 2],
  ])('uses %s decimals for %s', (price, expected) => {
    expect(priceDecimals(price)).toBe(expected);
  });

  it('keeps sub-dollar detail that two decimals would destroy', () => {
    // A cent is nearly 3% at this price; rounding to 0.37 would put a level
    // and the price standing on it at the same number.
    expect(formatPrice(0.3738)).toBe('0.3738');
    expect(formatPrice(0.3712)).toBe('0.3712');
  });

  it('does not clutter a large price', () => {
    expect(formatPrice(334.8599)).toBe('334.86');
  });

  it('handles negative magnitudes by size', () => {
    expect(priceDecimals(-0.5)).toBe(4);
  });
});

describe('formatPercent', () => {
  it('signs a gain', () => {
    expect(formatPercent(2.5)).toBe('+2.50%');
  });

  it('signs a loss', () => {
    expect(formatPercent(-2.5)).toBe('-2.50%');
  });

  it('renders a dash for missing values', () => {
    expect(formatPercent(null)).toBe('—');
  });
});

describe('formatCompact', () => {
  it.each([
    [1_500_000_000, '1.50B'],
    [2_400_000, '2.40M'],
    [45_600, '45.6K'],
    [812, '812'],
  ])('formats %s as %s', (input, expected) => {
    expect(formatCompact(input)).toBe(expected);
  });

  it('keeps the sign on negatives', () => {
    expect(formatCompact(-2_400_000)).toBe('-2.40M');
  });

  it('renders a dash for missing values', () => {
    expect(formatCompact(null)).toBe('—');
  });
});

describe('formatMoney', () => {
  it('prefixes a dollar sign', () => {
    expect(formatMoney(2_400_000)).toBe('$2.40M');
  });
});

describe('percentDistance', () => {
  it('measures upward distance', () => {
    expect(percentDistance(100, 110)).toBeCloseTo(10);
  });

  it('measures downward distance', () => {
    expect(percentDistance(100, 90)).toBeCloseTo(-10);
  });

  it('is undefined against a zero reference', () => {
    expect(percentDistance(0, 10)).toBeNull();
  });

  it('is undefined with a missing side', () => {
    expect(percentDistance(null, 10)).toBeNull();
  });
});

describe('computeChange', () => {
  it('reports an upward move', () => {
    const change = computeChange(110, 100);
    expect(change).toMatchObject({ absolute: 10, percent: 10, direction: 'up' });
  });

  it('reports a downward move', () => {
    expect(computeChange(90, 100)?.direction).toBe('down');
  });

  it('reports no move', () => {
    expect(computeChange(100, 100)?.direction).toBe('flat');
  });

  it('is undefined against a zero base', () => {
    expect(computeChange(10, 0)).toBeNull();
  });
});

describe('formatChange', () => {
  it('shows absolute and percentage together', () => {
    expect(formatChange(computeChange(110, 100))).toBe('+10.00 (+10.00%)');
  });

  it('renders a dash for nothing', () => {
    expect(formatChange(null)).toBe('—');
  });
});

describe('formatBarTime', () => {
  // 2024-03-05 14:30 UTC is 09:30 in New York — the opening bell.
  const openingBell = Date.UTC(2024, 2, 5, 14, 30) / 1000;

  it('renders intraday bars in New York time', () => {
    expect(formatBarTime(openingBell, '1m')).toContain('09:30');
  });

  it('renders daily bars as a date', () => {
    const formatted = formatBarTime(openingBell, '1d');
    expect(formatted).toContain('Mar');
    expect(formatted).toContain('2024');
  });

  it('does not use the local timezone', () => {
    // Guards against a chart that puts the US open in the wrong place for
    // anyone outside New York.
    expect(formatBarTime(openingBell, '1m')).not.toContain('14:30');
  });
});
