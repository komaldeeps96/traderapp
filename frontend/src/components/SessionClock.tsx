import { useEffect, useState } from 'react';

import { formatClock } from '@/lib/format';
import { sessionView } from '@/lib/session';

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
    </div>
  );
}
