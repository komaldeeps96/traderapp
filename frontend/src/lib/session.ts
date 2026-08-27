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

/** The session a historical bar printed in. */
export function sessionAt(epochSeconds: number): SessionName {
  return sessionView(new Date(epochSeconds * 1000)).session;
}

/**
 * Which New York trading day an epoch second belongs to.
 *
 * A fixed 4.5-hour offset instead of a real timezone lookup, on purpose: the
 * tape only prints between 4:00 and 20:00 ET, and any offset between 4 and 5
 * hours buckets every such timestamp identically under both EST and EDT. That
 * makes the day boundary pure arithmetic — this runs once per bar over
 * thousands of bars every time the session cache rebuilds.
 */
export function nyDayIndex(epochSeconds: number): number {
  return Math.floor((epochSeconds - 16_200) / 86_400);
}

/**
 * Cumulative volume through each bar, restarting at every New York day.
 *
 * `result[i]` is the session volume *as of* bar i — what the day had done by
 * that moment, which is the honest way to read a historical setup. On daily
 * and weekly bars every bar is its own "day", so the figure degrades to the
 * bar's own volume.
 */
export function sessionVolumes(bars: readonly { t: number; v: number }[]): number[] {
  const result: number[] = new Array(bars.length);
  let day = Number.NaN;
  let sum = 0;
  for (let i = 0; i < bars.length; i += 1) {
    const bar = bars[i]!;
    const barDay = nyDayIndex(bar.t);
    if (barDay !== day) {
      day = barDay;
      sum = 0;
    }
    sum += bar.v;
    result[i] = sum;
  }
  return result;
}

export function timeframeSeconds(timeframe: Timeframe): number {
  return TIMEFRAME_SECONDS[timeframe];
}

const TIMEFRAME_SECONDS: Record<Timeframe, number> = {
  '10s': 10,
  '1m': 60,
  '5m': 300,
  '15m': 900,
  '30m': 1800,
  '1h': 3600,
  '4h': 14_400,
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
  const now = Math.floor(epochSeconds);
  // Bars align to the New York wall clock (backend: market/resample.py). A
  // size that divides an hour lands on the same boundaries either way — US
  // offsets are whole hours — so it skips the timezone lookup. The 4-hour
  // bar is the one that does not: counted off UTC it would close an hour
  // early all winter, and the countdown would disagree with the candle.
  if (3600 % size === 0) return size - (now % size);
  const local = now + nyOffsetSeconds(now);
  return size - (((local % size) + size) % size);
}

const NY_OFFSET = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  timeZoneName: 'longOffset',
});

/** New York's UTC offset at an instant, in seconds (negative, whole hours). */
function nyOffsetSeconds(epochSeconds: number): number {
  const name = NY_OFFSET.formatToParts(new Date(epochSeconds * 1000)).find(
    (part) => part.type === 'timeZoneName',
  )?.value;
  const match = name ? /GMT([+-])(\d{2}):(\d{2})/.exec(name) : null;
  // Standard time is the safe fallback: an engine without longOffset support
  // would otherwise put the boundary an hour out for eight months of the year.
  if (!match) return -5 * 3600;
  return (match[1] === '-' ? -1 : 1) * (Number(match[2]) * 3600 + Number(match[3]) * 60);
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
  const seconds = remaining % 60;
  const minutes = Math.floor(remaining / 60);
  // Hours once there are hours to show: "239:14" is a 4-hour bar's countdown
  // in minutes, and nobody reads that as "just under four hours".
  if (remaining >= 3600) {
    const hours = Math.floor(remaining / 3600);
    return `${hours}:${String(minutes % 60).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }
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
