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
 * Decimals follow the quoting tick: Reg NMS Rule 612 gives a cent at or above
 * $1.00 and sub-penny ($0.0001) only below it. So a $2.34 stock gets two, and
 * only the sub-dollar tape — where a cent is ~3% of price — earns four.
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
  // Trillions matter now that the terminal covers mega caps: Apple's market
  // cap renders as "$4665.76B" without this, which has to be counted rather
  // than read.
  if (abs >= 1e12) return `${(value / 1e12).toFixed(digits)}T`;
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
 * The date is dropped for a bar from the session on screen, leaving a clock
 * that reads against the toolbar's. It returns for a bar from an earlier day,
 * the only case where its absence could mislead.
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
 * A thirty-day feed showing only "09:01" makes a June filing read as this
 * morning's news.
 */
export function formatNewsTime(epochSeconds: number, now: number = Date.now()): string {
  const when = new Date(epochSeconds * 1000);
  const sameDay = newsDayFormat.format(when) === newsDayFormat.format(new Date(now));
  return sameDay ? newsTimeFormat.format(when) : newsDayFormat.format(when);
}

const briefDayFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
});
const nyDayParts = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: NY_TIMEZONE,
});

/**
 * How long ago something was read: "12s", "4m", "2h", "3d".
 *
 * An *age*, not a stopwatch — `formatElapsed` is mm:ss and would render eight
 * days as "11520:00". One unit, always the largest that fits.
 */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '—';
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86_400)}d`;
}

/**
 * When a brief's window opened: "Fri 16:00".
 *
 * Always shown beside the session: the pair is the whole claim, as in "for
 * Monday, since Friday's close".
 */
export function formatWindowStart(epoch: number): string {
  return windowStartFormat.format(new Date(epoch * 1000));
}

const windowStartFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: NY_TIMEZONE,
});

/**
 * The session a brief covers: "Today", or "Fri, Sep 5".
 *
 * The input is a calendar date, not an instant: `new Date('2026-09-07')` is
 * midnight UTC, which in New York is the 6th. The parts are read out of the
 * string and rebuilt as a local date, which has no timezone to be wrong about.
 */
export function formatNewsDay(iso: string, now: number = Date.now()): string {
  const [year, month, day] = iso.split('-').map(Number);
  if (!year || !month || !day) return iso;
  // en-CA renders as YYYY-MM-DD, which is the shape being compared against.
  if (nyDayParts.format(new Date(now)) === iso) return 'Today';
  return briefDayFormat.format(new Date(year, month - 1, day));
}

/**
 * A price that may be nonsense. Reverse splits compound into split-adjusted
 * history, so an all-time high can print in the tens of millions against a
 * 38-cent tape; compacting past five figures stops it setting a row's width.
 */
export function formatLevel(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (Math.abs(value) >= 100_000) return formatCompact(value, 1);
  return formatPrice(value);
}

/**
 * A ratio read as a multiple: ×2.4, ×18, ×243M. The escape hatch for
 * percentages that have stopped being percentages.
 */
export function formatMultiple(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1000) return `×${formatCompact(value, 0)}`;
  return `×${value.toFixed(abs >= 10 ? 0 : 1)}`;
}

/**
 * Distance to a level, as a percentage until that stops being readable. Past
 * ten times the price a four-figure percentage becomes a multiple, which says
 * the same thing in half the characters.
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
 * `formatPercent` signs everything, which is right for a change and wrong for a
 * quantity that cannot be negative — "+0.4%" invites being read as one.
 */
/**
 * A percentage that always carries its sign when it has one: a distance off a
 * high, or a day's move, means nothing without it. Zero is unsigned, and a
 * four-figure run is compacted rather than printed to the decimal.
 */
export function formatSignedPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const shown = Math.abs(value) >= 1000 ? formatCompact(value, 0) : value.toFixed(1);
  return `${value > 0 ? '+' : ''}${shown}%`;
}

/** YYYY-MM-DD on the New York calendar, the one a report date is scheduled on. */
export function formatNyDate(epochSeconds: number): string {
  return nyDayKey.format(new Date(epochSeconds * 1000));
}

export function formatUnsignedPercent(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${Math.abs(value).toFixed(digits)}%`;
}

/**
 * A short elapsed span, counting up: 0:04, 3:27, 14:59. No hour field — this
 * measures things that matter for minutes.
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
 * The dollar leg's precision follows the *price level*, not the delta: on a
 * $0.37 stock two decimals report a +0.0350 move as +0.04. Pass the price the
 * change happened at; without one, cent precision is the floor.
 */
export function formatChange(change: Change | null, referencePrice?: number | null): string {
  if (!change) return '—';
  const sign = change.absolute >= 0 ? '+' : '';
  const digits = referencePrice != null ? priceDecimals(referencePrice) : 2;
  return `${sign}${change.absolute.toFixed(digits)} (${sign}${change.percent.toFixed(2)}%)`;
}

/**
 * One cell of a financial statement.
 *
 * The unit decides everything. Dollars are compacted; per-share figures are
 * not, since `formatCompact` rounds under a thousand to an integer and an EPS
 * of 2.02 would become "2". Share counts compact but never take cents.
 *
 * Negatives keep their sign rather than parentheses, beside a chart where red
 * and a minus already mean down.
 */
export function formatStatementValue(
  value: number | null | undefined,
  unit: string,
  symbol = '$',
): string {
  if (value == null || !Number.isFinite(value)) return '—';
  // Matched by shape, not by name: a foreign private issuer quotes earnings
  // per share in 'CAD/shares', and testing for the literal 'USD/shares' sent
  // its EPS through the money branch, where -0.06 rendered as '-$0'.
  if (unit.endsWith('/shares')) return value.toFixed(2);
  if (unit === 'shares') return formatCompact(value, 1);
  const sign = value < 0 ? '-' : '';
  return `${sign}${symbol}${formatCompact(Math.abs(value), 2)}`;
}

/**
 * One cell of the metrics table.
 *
 * A ratio and a multiple are both bare numbers, so a multiple carries its ×.
 * Percentages get one decimal — two reads as more precise than the filings.
 */
export function formatMetricValue(
  value: number | null | undefined,
  unit: string,
  symbol = '$',
): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (unit === 'percent') return `${(value * 100).toFixed(1)}%`;
  if (unit === 'multiple') return `${value.toFixed(2)}×`;
  if (unit === 'money') return formatStatementValue(value, 'money', symbol);
  return value.toFixed(2);
}

const NY_DAY = new Intl.DateTimeFormat('en-CA', {
  timeZone: NY_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

/**
 * Whole days from now until an epoch second, counted in New York.
 *
 * *Calendar* days, not 24-hour blocks: what is being decided is how many
 * sessions a position has to survive. Both ends go through the New York
 * calendar rather than a second offset, which is only correct inside a session.
 */
export function daysUntil(
  epochSeconds: number | null | undefined,
  nowEpochSeconds: number,
): number | null {
  if (epochSeconds == null || !Number.isFinite(epochSeconds)) return null;
  const midnightUtc = (seconds: number) =>
    Date.parse(`${NY_DAY.format(new Date(seconds * 1000))}T00:00:00Z`);
  return Math.round(
    (midnightUtc(epochSeconds) - midnightUtc(nowEpochSeconds)) / 86_400_000,
  );
}

/**
 * One cell of the raw concept view, in whatever unit the company filed it.
 *
 * A search across everything a filer tags returns dollars beside lease terms in
 * years, tax rates as decimals and share counts, so this cannot assume money.
 * It keeps two decimals below the compaction threshold, since `formatCompact`
 * would round a lease term of 10.3 years to "10".
 */
export function formatAsFiled(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (Math.abs(value) >= 1e6) return formatCompact(value, 2);
  if (Number.isInteger(value)) return value.toLocaleString('en-US');
  return value.toFixed(2);
}
