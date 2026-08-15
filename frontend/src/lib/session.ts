/**
 * US equity session state, in New York wall-clock time.
 *
 * The session drives more than a label: the momentum window is 7:00–9:30,
 * halts only exist 9:30–16:00, and after 11:00 the edge is gone — so the
 * clock carries a phase read, not just the time.
 */

import type { Timeframe } from '@/types/protocol';

export type SessionName = 'PRE' | 'RTH' | 'AH' | 'CLOSED';

/** The working windows of the momentum day, per the playbook. */
export type SessionPhase = 'prime' | 'conditional' | 'wind-down' | 'off';

const NY_PARTS = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour12: false,
  weekday: 'short',
  hour: 'numeric',
  minute: 'numeric',
  second: 'numeric',
});

export interface SessionView {
  session: SessionName;
  phase: SessionPhase;
  /** Minutes since New York midnight. */
  minutes: number;
  weekend: boolean;
}

export function sessionView(now: Date = new Date()): SessionView {
  const parts = NY_PARTS.formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  const weekday = get('weekday');
  const weekend = weekday === 'Sat' || weekday === 'Sun';
  const hour = Number(get('hour')) % 24;
  const minutes = hour * 60 + Number(get('minute'));

  let session: SessionName = 'CLOSED';
  if (!weekend) {
    if (minutes >= 4 * 60 && minutes < 9 * 60 + 30) session = 'PRE';
    else if (minutes >= 9 * 60 + 30 && minutes < 16 * 60) session = 'RTH';
    else if (minutes >= 16 * 60 && minutes < 20 * 60) session = 'AH';
  }

  let phase: SessionPhase = 'off';
  if (!weekend) {
    if (minutes >= 7 * 60 && minutes < 9 * 60 + 30) phase = 'prime';
    else if (minutes >= 9 * 60 + 30 && minutes < 10 * 60) phase = 'conditional';
    else if (minutes >= 10 * 60 && minutes < 11 * 60) phase = 'wind-down';
  }

  return { session, phase, minutes, weekend };
}

const TIMEFRAME_SECONDS: Record<Timeframe, number> = {
  '10s': 10,
  '1m': 60,
  '5m': 300,
  '15m': 900,
  '1h': 3600,
  '1d': 86_400,
  '1w': 604_800,
};

/**
 * Seconds until the current candle closes.
 *
 * The read on a candle firms up in its final seconds — with ~20 left the
 * shape is probably final; in the first few it can still flip completely.
 */
export function secondsToCandleClose(timeframe: Timeframe, epochSeconds: number): number {
  const size = TIMEFRAME_SECONDS[timeframe];
  return size - (Math.floor(epochSeconds) % size);
}

/**
 * The countdown as it reads on the price axis.
 *
 * Bare seconds while a bar is under a minute long, because "0:09" on a
 * 10-second chart is three characters of nothing. Minutes and seconds above
 * that, where a bare "247s" would have to be divided in the head.
 */
export function formatCountdown(timeframe: Timeframe, remaining: number): string {
  if (TIMEFRAME_SECONDS[timeframe] < 60) return `${remaining}s`;
  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/**
 * Is the bar in its closing stretch?
 *
 * Proportional rather than a fixed number of seconds: five seconds is half a
 * 10-second bar and a rounding error on a 5-minute one. The final tenth marks
 * the point where the shape is unlikely to change again — with a two-second
 * floor so a fast timeframe still gives some warning.
 */
export function isCandleClosing(timeframe: Timeframe, remaining: number): boolean {
  return remaining <= Math.max(2, TIMEFRAME_SECONDS[timeframe] / 10);
}

/** A countdown only means something on a bar that closes within the day. */
export function hasCandleCountdown(timeframe: Timeframe): boolean {
  return TIMEFRAME_SECONDS[timeframe] < 86_400;
}
