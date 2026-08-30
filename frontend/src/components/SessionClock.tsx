import { useEffect, useState } from 'react';

import { formatClock, formatElapsed } from '@/lib/format';
import {
  LAST_INITIATION_MINUTE,
  newsWindow,
  sessionView,
  slotLabel,
  type NewsWindow,
} from '@/lib/session';

const SESSION_TONE: Record<string, string> = {
  PRE: 'text-accent-text border-accent/50',
  RTH: 'text-up border-up/50',
  AH: 'text-ink-3 border-line-strong',
  CLOSED: 'text-ink-3 border-line',
};

const PHASE_LABEL: Record<string, string | null> = {
  prime: 'PRIME',
  conditional: 'COND',
  'wind-down': 'WIND-DN',
  off: null,
};

/**
 * New York clock and session badge.
 *
 * The candle countdown used to live here too and has moved onto the price
 * axis of each chart, under the last-price label. It matters most in a
 * candle's closing seconds, which is exactly when the eye is on the right
 * edge of the chart — reading it up here meant looking away from the thing
 * it describes, and it could only ever count one chart's timeframe.
 */
export function SessionClock() {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, []);

  const epoch = now / 1000;
  const view = sessionView(new Date(now));
  const phase = PHASE_LABEL[view.phase];

  return (
    <div className="tnum flex items-center gap-1.5 font-mono text-[11px]" data-testid="session-clock">
      <span className="font-semibold text-ink" data-testid="clock-time">
        {formatClock(epoch)}
      </span>
      <span
        className={`rounded-sm border px-1 text-[9px] font-bold leading-4 ${SESSION_TONE[view.session]}`}
        data-testid="session-badge"
        data-session={view.session}
      >
        {view.session}
      </span>
      {phase && (
        <span
          className="rounded-sm bg-elevated px-1 text-[9px] font-bold leading-4 text-ink-3"
          title="7:00–9:30 is the prime window; 9:30–10:00 conditional; 10:00–11:00 wind-down"
          data-testid="session-phase"
        >
          {phase}
        </span>
      )}
      <NewsSlot window={newsWindow(new Date(now))} minutes={view.minutes} />
    </div>
  );
}

/**
 * The next scheduled release window.
 *
 * Issuers file on the hour and the half hour, densest at 8:00 and 8:30, and
 * the day's profit distribution sits directly behind that calendar. So the
 * useful clock is not "how long until the open" — it is "how long until the
 * next time news can land", and then whether it did.
 *
 * Past 9:15 the chip stops counting and says so instead: no slot is left to
 * wait for, and a position opened after it has no runway to recover in.
 */
function NewsSlot({ window, minutes }: { window: NewsWindow | null; minutes: number }) {
  if (minutes >= LAST_INITIATION_MINUTE && minutes < 16 * 60) {
    return (
      <span
        className="rounded-sm bg-elevated px-1 text-[9px] font-bold leading-4 text-ink-3"
        title="Past 9:15 — the last scheduled headline has come and gone, and a first trade taken now has no time to recover before the window shuts. Managing what is already open is a different question."
        data-testid="news-slot"
        data-state="late"
      >
        NO NEW
      </span>
    );
  }
  if (!window) return null;

  return (
    <span
      className={`rounded-sm px-1 text-[9px] font-bold leading-4 ${
        window.open ? 'bg-accent/20 text-accent-text' : 'bg-elevated text-ink-3'
      }`}
      title={
        window.open
          ? `${slotLabel(window.slot)} has passed — anything moving now is presumed to be moving on it. Silence through this window closes it.`
          : `Next scheduled release window.${window.dense ? ' 8:00 and 8:30 are the densest of the day.' : ''}`
      }
      data-testid="news-slot"
      data-state={window.open ? 'open' : 'waiting'}
      data-dense={window.dense}
    >
      {slotLabel(window.slot)}
      {/* Past an hour out the countdown stops being a countdown: a terminal
          left open overnight would read "7:00 300:00", which is five hours
          stated in minutes. The slot alone is the useful half by then. */}
      {window.open || window.seconds <= 3600
        ? ` ${window.open ? '+' : ''}${formatElapsed(window.seconds)}`
        : ''}
    </span>
  );
}
