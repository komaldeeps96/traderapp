/**
 * Display formatting.
 *
 * Everything here is pure so the numbers on screen are directly testable.
 * Timestamps are always rendered in New York time — a US equities chart read
 * in local time would put the open in the wrong place.
 */

import type { Timeframe } from '@/types/protocol';

export const NY_TIMEZONE = 'America/New_York';

// Intl formatters are expensive to construct, and these run on every crosshair
// move, so they are built once.
const dayFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: NY_TIMEZONE,
  month: 'short',
  day: 'numeric',
});

// Sortable YYYY-MM-DD in New York, used only to answer "is this bar from the
// session on screen right now?" — never rendered.
const nyDayKey = new Intl.DateTimeFormat('en-CA', {
  timeZone: NY_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

const dayYearFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: NY_TIMEZONE,
  year: 'numeric',
  month: 'short',
  day: 'numeric',
});

const timeFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: NY_TIMEZONE,
  hour12: false,
  hour: '2-digit',
  minute: '2-digit',
});

const timeWithSecondsFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: NY_TIMEZONE,
  hour12: false,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

const dateTimeFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: NY_TIMEZONE,
  month: 'short',
  day: 'numeric',
  hour12: false,
  hour: '2-digit',
  minute: '2-digit',
});

const dateTimeWithSecondsFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: NY_TIMEZONE,
  month: 'short',
  day: 'numeric',
  hour12: false,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

/**
 * Decimal places appropriate to a price's magnitude.
 *
 * Sub-dollar tickers are the whole point of a small-cap terminal, and two
 * decimals throws away most of what matters there: at $0.37 a cent is nearly
 * 3%, so "0.37" hides the difference between a level and the price standing on
 * it.
 */
/**
 * Decimals follow the quoting tick, not taste. Reg NMS Rule 612: a cent at
 * or above $1.00, sub-penny ($0.0001) only below it. So a $2.34 stock gets
 * two decimals — a third would be a permanent trailing zero — and only the
 * sub-dollar tape, where a whole cent is ~3% of price, earns four.
 */
export function priceDecimals(value: number): number {
  return Math.abs(value) < 1 ? 4 : 2;
}

export function formatPrice(value: number | null | undefined, digits?: number): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return value.toFixed(digits ?? priceDecimals(value));
}

export function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}%`;
}

/** Compact magnitude: 1.23M, 45.6K. */
export function formatCompact(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(digits)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(digits)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return Math.round(value).toString();
}

export function formatMoney(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `$${formatCompact(value)}`;
}

export function formatInteger(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return Math.round(value).toLocaleString('en-US');
}

/**
 * The bar's opening time, in New York.
 *
 * The date is dropped for a bar from the session on screen: "Aug 28," in
 * front of an intraday timestamp is noise every single day, and dropping it
 * leaves a clean clock that reads against the wall clock in the toolbar. It
 * comes back the moment the bar is from an earlier day, which is the only
 * case where its absence could mislead.
 */
export function formatBarTime(
  epochSeconds: number,
  timeframe: Timeframe,
  now: number = Date.now(),
): string {
  const date = new Date(epochSeconds * 1000);
  if (timeframe === '1d' || timeframe === '1w') return dayYearFormat.format(date);
  if (nyDayKey.format(date) === nyDayKey.format(new Date(now))) {
    return timeframe === '10s'
      ? timeWithSecondsFormat.format(date)
      : timeFormat.format(date);
  }
  if (timeframe === '10s') return dateTimeWithSecondsFormat.format(date);
  return dateTimeFormat.format(date);
}

export function formatAxisTime(epochSeconds: number, timeframe: Timeframe): string {
  const date = new Date(epochSeconds * 1000);
  if (timeframe === '1d' || timeframe === '1w') return dayFormat.format(date);
  if (timeframe === '10s') return timeWithSecondsFormat.format(date);
  return timeFormat.format(date);
}

export function formatClock(epochSeconds: number): string {
  return timeWithSecondsFormat.format(new Date(epochSeconds * 1000));
}

const newsDayFormat = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  timeZone: NY_TIMEZONE,
});
const newsTimeFormat = new Intl.DateTimeFormat('en-US', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: NY_TIMEZONE,
});

/**
 * A headline's timestamp: the clock for today, the date for anything older.
 *
 * A feed reaching back thirty days that shows only "09:01" makes a filing from
 * June read as this morning's news, which is the one mistake a news panel must
 * not make.
 */
export function formatNewsTime(epochSeconds: number, now: number = Date.now()): string {
  const when = new Date(epochSeconds * 1000);
  const sameDay = newsDayFormat.format(when) === newsDayFormat.format(new Date(now));
  return sameDay ? newsTimeFormat.format(when) : newsDayFormat.format(when);
}

/**
 * A price that may be nonsense.
 *
 * Reverse splits compound into split-adjusted history, so a serial diluter's
 * all-time high can print in the tens of millions against a 38-cent tape.
 * Compacting past five figures is what stops one broken reference number from
 * setting the width of an entire row.
 */
export function formatLevel(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (Math.abs(value) >= 100_000) return formatCompact(value, 1);
  return formatPrice(value);
}

/**
 * A ratio read as a multiple: ×2.4, ×18, ×243M.
 *
 * The escape hatch for percentages that have stopped being percentages —
 * "+24283875452%" is nine characters of nothing, "×243M" is the same fact in
 * five and reads instantly as out of reach.
 */
export function formatMultiple(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1000) return `×${formatCompact(value, 0)}`;
  return `×${value.toFixed(abs >= 10 ? 0 : 1)}`;
}

/**
 * Distance to a level, as a percentage until that stops being readable.
 *
 * A 52-week high on a stock that has fallen 99% — or an all-time high on one
 * that has reverse-split its way down — is a four-figure percentage in a
 * column sized for "+45.68%". Past ten times the price the multiple says the
 * same thing in half the characters.
 */
export function formatDistance(percent: number | null | undefined): string {
  if (percent == null || !Number.isFinite(percent)) return '—';
  if (Math.abs(percent) < 1000) return formatPercent(percent);
  return formatMultiple(1 + percent / 100);
}

/** Float rotation: 0.42x, 6.8x, 72x. */
export function formatRotation(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value >= 10) return `${Math.round(value)}x`;
  return `${value.toFixed(value >= 1 ? 1 : 2)}x`;
}

/**
 * A percentage that has no direction: 4.1%, 0.4%, 13%.
 *
 * `formatPercent` signs everything, which is right for a change — a bar can
 * close either way. It is wrong for a quantity that cannot be negative. A
 * spread of "+0.4%", a float rotation of "+13%" or a headroom of "+4.1%"
 * invite being read as changes, and the plus carries no information at all.
 */
export function formatUnsignedPercent(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${Math.abs(value).toFixed(digits)}%`;
}

/**
 * A short elapsed span, counting up: 0:04, 3:27, 14:59.
 *
 * Minutes and seconds throughout, with no hour field — this measures things
 * that matter for minutes, and a reading that has reached an hour has
 * already stopped meaning anything.
 */
export function formatElapsed(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '—';
  const whole = Math.floor(seconds);
  const minutes = Math.floor(whole / 60);
  return `${minutes}:${String(whole % 60).padStart(2, '0')}`;
}

/** A spread in dollars, shown in cents below one dollar: 4¢, 38¢, $1.25. */
export function formatSpread(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (Math.abs(value) >= 1) return `$${value.toFixed(2)}`;
  // Cents, with just enough decimals for the size: sub-dollar names quote in
  // hundredths of a cent, and flooring a real 0.04¢ spread to 0.0¢ reads as
  // "free" when it is a third of a percent of the price.
  const cents = value * 100;
  const digits = Math.abs(cents) < 1 ? 2 : Math.abs(cents) < 10 ? 1 : 0;
  return `${cents.toFixed(digits)}¢`;
}

/** Percentage distance from `from` to `to`, or null if it cannot be computed. */
export function percentDistance(from: number | null, to: number | null): number | null {
  if (from == null || to == null || !Number.isFinite(from) || !Number.isFinite(to) || from === 0) {
    return null;
  }
  return ((to - from) / from) * 100;
}

export interface Change {
  absolute: number;
  percent: number;
  direction: 'up' | 'down' | 'flat';
}

export function computeChange(current: number, previous: number): Change | null {
  if (!Number.isFinite(current) || !Number.isFinite(previous) || previous === 0) return null;
  const absolute = current - previous;
  return {
    absolute,
    percent: (absolute / previous) * 100,
    direction: absolute > 0 ? 'up' : absolute < 0 ? 'down' : 'flat',
  };
}

/**
 * The dollar leg's precision follows the *price level*, not the delta: a
 * $0.37 stock moves in hundredths of a cent, so two decimals would report a
 * +0.0350 move as +0.04 — a 14% lie. Pass the price the change happened at;
 * without one, cent precision is the safe floor.
 */
export function formatChange(change: Change | null, referencePrice?: number | null): string {
  if (!change) return '—';
  const sign = change.absolute >= 0 ? '+' : '';
  const digits = referencePrice != null ? priceDecimals(referencePrice) : 2;
  return `${sign}${change.absolute.toFixed(digits)} (${sign}${change.percent.toFixed(2)}%)`;
}
