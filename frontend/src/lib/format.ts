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
export function priceDecimals(value: number): number {
  const magnitude = Math.abs(value);
  if (magnitude < 1) return 4;
  if (magnitude < 10) return 3;
  return 2;
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

export function formatBarTime(epochSeconds: number, timeframe: Timeframe): string {
  const date = new Date(epochSeconds * 1000);
  if (timeframe === '1d' || timeframe === '1w') return dayYearFormat.format(date);
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

/** Float rotation: 0.42x, 6.8x, 72x. */
export function formatRotation(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value >= 10) return `${Math.round(value)}x`;
  return `${value.toFixed(value >= 1 ? 1 : 2)}x`;
}

/** A spread in dollars, shown in cents below one dollar: 4¢, 38¢, $1.25. */
export function formatSpread(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (Math.abs(value) < 1) return `${(value * 100).toFixed(value < 0.1 ? 1 : 0)}¢`;
  return `$${value.toFixed(2)}`;
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

export function formatChange(change: Change | null): string {
  if (!change) return '—';
  const sign = change.absolute >= 0 ? '+' : '';
  return `${sign}${change.absolute.toFixed(2)} (${sign}${change.percent.toFixed(2)}%)`;
}
