import { describe, expect, it } from 'vitest';

import {
  formatCountdown,
  hasCandleCountdown,
  isCandleClosing,
  secondsToCandleClose,
} from './session';

/**
 * The bar countdown, which now rides on each chart's price axis.
 *
 * Every chart counts its own timeframe, so all of this has to hold from a
 * 10-second bar up to a daily one — the reason the rules are proportional
 * rather than a fixed number of seconds.
 */
describe('secondsToCandleClose', () => {
  // Divides exactly by 10, 60 and 300, so one instant opens a bar on every
  // timeframe the countdown runs on and the arithmetic below reads directly.
  const BAR_OPEN = 1_700_000_100;

  it('counts down within the current bar', () => {
    expect(secondsToCandleClose('10s', BAR_OPEN + 3)).toBe(7);
  });

  it('reads a full bar exactly on the boundary', () => {
    expect(secondsToCandleClose('10s', BAR_OPEN)).toBe(10);
  });

  it('scales to the timeframe', () => {
    expect(secondsToCandleClose('1m', BAR_OPEN + 10)).toBe(50);
    expect(secondsToCandleClose('5m', BAR_OPEN + 10)).toBe(290);
  });

  it('ignores sub-second precision', () => {
    expect(secondsToCandleClose('10s', BAR_OPEN + 3.99)).toBe(7);
  });
});

describe('formatCountdown', () => {
  it('uses bare seconds on a sub-minute bar', () => {
    // "0:09" on a 10-second chart is three characters of nothing.
    expect(formatCountdown('10s', 9)).toBe('9s');
  });

  it('uses minutes and seconds above that', () => {
    expect(formatCountdown('1m', 47)).toBe('0:47');
    expect(formatCountdown('5m', 192)).toBe('3:12');
  });

  it('pads the seconds so the label does not jitter', () => {
    expect(formatCountdown('5m', 65)).toBe('1:05');
  });

  it('handles a whole number of minutes', () => {
    expect(formatCountdown('5m', 300)).toBe('5:00');
  });
});

describe('isCandleClosing', () => {
  it('is quiet through most of the bar', () => {
    expect(isCandleClosing('10s', 9)).toBe(false);
    expect(isCandleClosing('5m', 200)).toBe(false);
  });

  it('warns in the final tenth', () => {
    expect(isCandleClosing('1m', 6)).toBe(true);
    expect(isCandleClosing('5m', 30)).toBe(true);
  });

  it('keeps a two-second floor so a fast bar still warns', () => {
    // A tenth of a 10-second bar is one second — too brief to register, so
    // the floor takes over.
    expect(isCandleClosing('10s', 2)).toBe(true);
    expect(isCandleClosing('10s', 3)).toBe(false);
  });
});

describe('hasCandleCountdown', () => {
  it('covers every intraday timeframe', () => {
    for (const timeframe of ['10s', '1m', '5m', '15m', '1h'] as const) {
      expect(hasCandleCountdown(timeframe)).toBe(true);
    }
  });

  it('skips bars that do not close within the day', () => {
    // Counting down 14 hours to the close is not a trading signal.
    expect(hasCandleCountdown('1d')).toBe(false);
    expect(hasCandleCountdown('1w')).toBe(false);
  });
});
