import { useNow } from '@/hooks/useNow';
import { EARNINGS_HORIZON_DAYS, EARNINGS_URGENT_DAYS } from '@/lib/earnings';
import { daysUntil } from '@/lib/format';

/**
 * How near the next report is, as a table cell. A breakout entered three days
 * before earnings is a different trade, so the cell shouts inside a week and
 * stays quiet beyond. A date already past — the source keeps serving one — is
 * nothing at all.
 */
export function EarningsCell({ epoch, testId }: { epoch: number | null; testId: string }) {
  const days = daysUntil(epoch, useNow(60_000));
  if (days == null || days < 0 || days > EARNINGS_HORIZON_DAYS) {
    return <td className="px-2 py-1 text-right text-ink-3">—</td>;
  }
  return (
    <td
      className={`px-2 py-1 text-right ${
        days <= EARNINGS_URGENT_DAYS ? 'font-semibold text-down' : 'text-ink-3'
      }`}
      data-testid={testId}
    >
      {days}d
    </td>
  );
}
