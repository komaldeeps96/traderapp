import { budgetTone, type BudgetTone } from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { ApiWindow } from '@/types/protocol';

const FILL: Record<BudgetTone, string> = {
  ok: 'bg-up',
  warn: 'bg-warn',
  hot: 'bg-down',
};

const TEXT: Record<BudgetTone, string> = {
  ok: 'text-ink-3',
  warn: 'text-warn',
  hot: 'text-down',
};

/**
 * Request-budget meters for the two upstreams.
 *
 * Switching tickers burns historical-data requests, and the punishments
 * differ — Alpaca throttles past 200 REST calls a minute, IBKR pacing
 * rejects past ~60 historical requests in ten minutes. The bars fill as the
 * windows fill: green means switch freely, amber means the window is half
 * spent, red means the next flurry of switches will queue behind the
 * limiter rather than hitting the upstream.
 */
export function ApiMeters() {
  const usage = useTerminalStore((state) => state.apiUsage);
  if (!usage) return null;

  return (
    <div className="flex items-center gap-2.5" data-testid="api-meters" aria-label="API request budgets">
      <Meter label="ALP" window={usage.alpaca} />
      <Meter label="IBKR" window={usage.ibkr} />
    </div>
  );
}

function Meter({ label, window: budget }: { label: string; window: ApiWindow }) {
  const tone = budgetTone(budget.used, budget.limit);
  const fraction = budget.limit > 0 ? Math.min(1, budget.used / budget.limit) : 1;
  const windowText =
    budget.window_s % 60 === 0 && budget.window_s >= 60
      ? `${budget.window_s / 60}m`
      : `${budget.window_s}s`;

  return (
    <div
      className="flex items-center gap-1"
      data-testid={`api-meter-${label.toLowerCase()}`}
      data-tone={tone}
      title={`${label === 'ALP' ? 'Alpaca' : 'IBKR'}: ${budget.used}/${budget.limit} requests in the last ${windowText}`}
    >
      <span className="text-[9px] font-bold tracking-wide text-ink-3">{label}</span>
      <span
        className="relative h-1.5 w-14 overflow-hidden rounded-full bg-line"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={budget.limit}
        aria-valuenow={budget.used}
        aria-label={`${label} requests used, ${budget.used} of ${budget.limit} per ${windowText}`}
      >
        <span
          className={`absolute inset-y-0 left-0 ${FILL[tone]}`}
          style={{ width: `${Math.round(fraction * 100)}%` }}
          aria-hidden
        />
      </span>
      <span
        className={`tnum font-mono text-[9px] font-semibold leading-none ${TEXT[tone]}`}
        data-testid={`api-count-${label.toLowerCase()}`}
      >
        {budget.used}/{budget.limit}
        <span className="text-ink-3"> · {windowText}</span>
      </span>
    </div>
  );
}
