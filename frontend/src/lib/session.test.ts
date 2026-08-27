import { describe, expect, it } from 'vitest';

import {
  formatCountdown,
  hasCandleCountdown,
  isCandleClosing,
  nyDayIndex,
  secondsToCandleClose,
  sessionAt,
  sessionVolumes,
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

  it('aligns a half-hour bar to the half hour', () => {
    // 09:44 New York, so the bar that opened at 09:30 has 16 minutes left.
    const at0944 = Date.UTC(2024, 2, 5, 14, 44) / 1000;
    expect(secondsToCandleClose('30m', at0944)).toBe(16 * 60);
  });

  it('splits the four-hour bar on the New York day, not on UTC', () => {
    // 10:37 New York sits in the 08:00-12:00 bar either side of the DST
    // switch. Counted off UTC the winter one would close an hour early.
    const winter = Date.UTC(2024, 2, 5, 15, 37) / 1000; // 10:37 EST
    const summer = Date.UTC(2024, 6, 10, 14, 37) / 1000; // 10:37 EDT
    expect(secondsToCandleClose('4h', winter)).toBe(83 * 60);
    expect(secondsToCandleClose('4h', summer)).toBe(83 * 60);
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

  it('shows hours on a bar long enough to have them', () => {
    // The same figure in minutes reads "83:00", which nobody parses as an
    // hour and twenty-three minutes.
    expect(formatCountdown('4h', 83 * 60)).toBe('1:23:00');
    expect(formatCountdown('4h', 3 * 3600 + 4 * 60 + 9)).toBe('3:04:09');
  });

  it('stays in minutes below an hour', () => {
    expect(formatCountdown('4h', 59 * 60 + 30)).toBe('59:30');
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
    for (const timeframe of ['10s', '1m', '5m', '15m', '30m', '1h', '4h'] as const) {
      expect(hasCandleCountdown(timeframe)).toBe(true);
    }
  });

  it('skips bars that do not close within the day', () => {
    // Counting down 14 hours to the close is not a trading signal.
    expect(hasCandleCountdown('1d')).toBe(false);
    expect(hasCandleCountdown('1w')).toBe(false);
  });
});

describe('session volume', () => {
  // 2026-08-18 (EDT): 4:00 ET pre-market open is 08:00 UTC.
  const PRE_OPEN = Date.UTC(2026, 7, 18, 8, 0) / 1000;
  const bar = (t: number, v: number) => ({ t, v });

  it('accumulates through one session', () => {
    const bars = [bar(PRE_OPEN, 100), bar(PRE_OPEN + 60, 200), bar(PRE_OPEN + 120, 50)];
    expect(sessionVolumes(bars)).toEqual([100, 300, 350]);
  });

  it('restarts at the New York day boundary', () => {
    const afterHours = PRE_OPEN + 15 * 3600; // 19:00 ET same day
    const nextOpen = PRE_OPEN + 24 * 3600; // 4:00 ET next day
    const bars = [bar(PRE_OPEN, 100), bar(afterHours, 200), bar(nextOpen, 40)];
    expect(sessionVolumes(bars)).toEqual([100, 300, 40]);
    expect(nyDayIndex(afterHours)).toBe(nyDayIndex(PRE_OPEN));
    expect(nyDayIndex(nextOpen)).toBe(nyDayIndex(PRE_OPEN) + 1);
  });

  it('buckets identically in winter, when New York is on EST', () => {
    // 2026-01-20: 4:00 ET is 09:00 UTC; 20:00 ET close is 01:00 UTC next day.
    const winterOpen = Date.UTC(2026, 0, 20, 9, 0) / 1000;
    const winterClose = Date.UTC(2026, 0, 21, 1, 0) / 1000;
    expect(nyDayIndex(winterClose)).toBe(nyDayIndex(winterOpen));
    expect(nyDayIndex(winterOpen + 86_400)).toBe(nyDayIndex(winterOpen) + 1);
  });

  it('names the session a bar printed in', () => {
    expect(sessionAt(PRE_OPEN)).toBe('PRE');
    expect(sessionAt(PRE_OPEN + 6 * 3600)).toBe('RTH'); // 10:00 ET
    expect(sessionAt(PRE_OPEN + 13 * 3600)).toBe('AH'); // 17:00 ET
  });
});
