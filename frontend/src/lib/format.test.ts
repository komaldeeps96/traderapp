import { describe, expect, it } from 'vitest';

import {
  computeChange,
  formatBarTime,
  formatChange,
  formatCompact,
  formatStatementValue,
  formatElapsed,
  formatLevel,
  formatMoney,
  formatMultiple,
  formatNewsTime,
  formatPercent,
  formatPrice,
  formatSpread,
  formatUnsignedPercent,
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
    // At or above a dollar the quoting tick is a whole cent (Reg NMS 612),
    // so a third decimal could only ever be a trailing zero.
    [1.0, 2],
    [4.25, 2],
    [9.999, 2],
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

describe('formatSpread', () => {
  it('shows dollar spreads in dollars', () => {
    expect(formatSpread(1.23)).toBe('$1.23');
  });

  it('shows cent spreads in cents, decimals matched to size', () => {
    expect(formatSpread(0.5)).toBe('50¢');
    expect(formatSpread(0.04)).toBe('4.0¢');
    expect(formatSpread(0.004)).toBe('0.40¢');
    // Sub-dollar names quote in hundredths of a cent; flooring this to 0.0¢
    // would read as free liquidity.
    expect(formatSpread(0.0004)).toBe('0.04¢');
  });

  it('handles absence', () => {
    expect(formatSpread(null)).toBe('—');
  });
});

describe('formatUnsignedPercent', () => {
  it('drops a sign that carries nothing', () => {
    // A spread, a rotation and a headroom cannot be negative; "+0.4%" reads
    // as a change rather than a quantity.
    expect(formatUnsignedPercent(0.4, 1)).toBe('0.4%');
    expect(formatUnsignedPercent(13, 0)).toBe('13%');
  });

  it('never reports a magnitude as negative', () => {
    expect(formatUnsignedPercent(-4.1, 1)).toBe('4.1%');
  });

  it('handles absence', () => {
    expect(formatUnsignedPercent(null)).toBe('—');
    expect(formatUnsignedPercent(Number.NaN)).toBe('—');
  });
});

describe('formatElapsed', () => {
  it('pads the seconds so the width does not jump', () => {
    expect(formatElapsed(4)).toBe('0:04');
    expect(formatElapsed(64)).toBe('1:04');
    expect(formatElapsed(899)).toBe('14:59');
  });

  it('truncates rather than rounds, so it never runs ahead', () => {
    expect(formatElapsed(59.9)).toBe('0:59');
  });

  it('keeps counting in minutes past the hour', () => {
    expect(formatElapsed(3661)).toBe('61:01');
  });

  it('handles absence and nonsense', () => {
    expect(formatElapsed(null)).toBe('—');
    expect(formatElapsed(-1)).toBe('—');
  });
});

describe('formatChange', () => {
  it('matches the dollar precision to the price level', () => {
    // +3.5 cents on a 37-cent stock: two decimals would report +0.04.
    expect(formatChange(computeChange(0.4088, 0.3738), 0.4088)).toBe('+0.0350 (+9.36%)');
    // The same helper on a dollar-priced stock stays at cents.
    expect(formatChange(computeChange(2.69, 2.34), 2.69)).toBe('+0.35 (+14.96%)');
  });

  it('shows absolute and percentage together', () => {
    expect(formatChange(computeChange(110, 100))).toBe('+10.00 (+10.00%)');
  });

  it('renders a dash for nothing', () => {
    expect(formatChange(null)).toBe('—');
  });
});

describe('formatLevel', () => {
  it('renders an ordinary level as a price', () => {
    expect(formatLevel(22.5)).toBe('22.50');
    expect(formatLevel(0.384)).toBe('0.3840');
  });

  it('compacts a reverse-split artefact instead of printing every digit', () => {
    // CHAI's split-adjusted all-time high, against a 38-cent tape.
    expect(formatLevel(93_250_082.12)).toBe('93.3M');
  });

  it('renders a dash for missing values', () => {
    expect(formatLevel(null)).toBe('—');
    expect(formatLevel(Number.NaN)).toBe('—');
  });
});

describe('formatMultiple', () => {
  it('reads a small multiple to one decimal', () => {
    expect(formatMultiple(2.42)).toBe('×2.4');
  });

  it('drops the decimal past ten', () => {
    expect(formatMultiple(18.3)).toBe('×18');
  });

  it('compacts the multiples percentages cannot express', () => {
    expect(formatMultiple(242_838_754)).toBe('×243M');
  });

  it('renders a dash for missing values', () => {
    expect(formatMultiple(null)).toBe('—');
  });
});

describe('formatBarTime', () => {
  // 2024-03-05 14:30 UTC is 09:30 in New York — the opening bell.
  const openingBell = Date.UTC(2024, 2, 5, 14, 30) / 1000;

  it('renders intraday bars in New York time', () => {
    expect(formatBarTime(openingBell, '1m')).toContain('09:30');
  });

  it('drops the date for a bar from the session on screen', () => {
    // The bar the clock is read against needs no "Mar 5," in front of it.
    expect(formatBarTime(openingBell, '1m', openingBell * 1000)).toBe('09:30');
    expect(formatBarTime(openingBell, '10s', openingBell * 1000)).toBe('09:30:00');
  });

  it('keeps the date once the bar is from an earlier day', () => {
    const nextDay = (openingBell + 24 * 3600) * 1000;
    expect(formatBarTime(openingBell, '1m', nextDay)).toContain('Mar 5');
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

describe('formatNewsTime', () => {
  // 2026-08-28 14:30 UTC = 10:30 New York.
  const today = Date.UTC(2026, 7, 28, 18, 0, 0);

  it('shows the clock for a headline from today', () => {
    const when = Date.UTC(2026, 7, 28, 14, 30, 0) / 1000;
    expect(formatNewsTime(when, today)).toBe('10:30');
  });

  it('shows the date for an older headline', () => {
    // A feed reaching back thirty days that shows only "09:01" makes a June
    // filing read as this morning's news.
    const when = Date.UTC(2026, 5, 25, 13, 1, 0) / 1000;
    expect(formatNewsTime(when, today)).toBe('Jun 25');
  });

  it('uses New York days, not the viewer\'s', () => {
    // 03:30 UTC on the 29th is still the evening of the 28th in New York.
    const when = Date.UTC(2026, 7, 29, 3, 30, 0) / 1000;
    expect(formatNewsTime(when, today)).toBe('23:30');
  });
});

describe('formatStatementValue', () => {
  it('compacts dollars, where the scale is the meaning', () => {
    expect(formatStatementValue(416_161_000_000, 'USD')).toBe('$416.16B');
    expect(formatStatementValue(26_400_000, 'USD')).toBe('$26.40M');
  });

  it('keeps the minus sign on a loss', () => {
    expect(formatStatementValue(-13_254_000, 'USD')).toBe('-$13.25M');
  });

  it('does not compact earnings per share', () => {
    // formatCompact rounds anything under a thousand to an integer, which
    // turns an EPS of 2.02 into "2".
    expect(formatStatementValue(2.02, 'USD/shares')).toBe('2.02');
    expect(formatStatementValue(-0.35, 'USD/shares')).toBe('-0.35');
  });

  it('compacts share counts without cents', () => {
    expect(formatStatementValue(15_408_095_000, 'shares')).toBe('15.4B');
  });

  it('shows a dash where nothing was filed', () => {
    expect(formatStatementValue(null, 'USD')).toBe('—');
    expect(formatStatementValue(undefined, 'USD')).toBe('—');
    expect(formatStatementValue(Number.NaN, 'USD')).toBe('—');
  });

  it('shows a real zero rather than a dash', () => {
    // A company that reported nothing and a company that reported zero are
    // different facts.
    expect(formatStatementValue(0, 'USD')).toBe('$0');
  });
});
