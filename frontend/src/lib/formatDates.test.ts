import { describe, expect, it } from 'vitest';

import { formatNyDate, formatSignedPercent } from './format';

describe('formatNyDate', () => {
  it('names a report by the New York day it is scheduled on', () => {
    // TradingView stamps a report with its time, in UTC: COST at 16:15 New
    // York is 20:15 UTC, the same calendar day.
    expect(formatNyDate(1_790_280_900)).toBe('2026-09-24');
  });

  it('keeps a late evening report on its own day, where UTC has moved on', () => {
    // 20:30 New York on 28 Oct 2026 is 00:30 UTC on the 29th, which the
    // UTC date read a day late.
    const lateEvening = Date.UTC(2026, 9, 29, 0, 30) / 1000;
    expect(formatNyDate(lateEvening)).toBe('2026-10-28');
  });
});

describe('formatSignedPercent', () => {
  it.each([
    [2.345, '+2.3%'],
    [-4.21, '-4.2%'],
    [0, '0.0%'],
    [1234, '+1.2K%'],
    [null, '—'],
    [Number.NaN, '—'],
  ])('%s reads %s', (value, shown) => {
    expect(formatSignedPercent(value)).toBe(shown);
  });
});
