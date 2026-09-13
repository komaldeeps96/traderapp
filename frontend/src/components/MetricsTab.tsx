import { useState } from 'react';

import { useSymbolResource } from '@/hooks/useSymbolResource';
import { formatMetricValue, formatMoney } from '@/lib/format';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { FinancialPeriodKind } from '@/types/protocol';

import { LoadError, PeriodToggle } from './PeriodToggle';

/**
 * What the statements mean, and what the market is asking for them.
 *
 * The valuation strip is on top as the one part that moves intraday, priced off
 * the live market cap while everything below changes quarterly. Its basis is
 * stated rather than assumed: a trailing-twelve-month multiple and a
 * fiscal-year one are different numbers.
 *
 * A dash is a refusal, not a zero — the backend declines to divide by a
 * negative denominator, which renders fine and reads as the opposite of what
 * it means.
 */

export function MetricsTab() {
  const symbol = useTerminalStore((state) => state.symbol);
  const [period, setPeriod] = useState<FinancialPeriodKind>('annual');
  const { data, error, loading } = useSymbolResource(
    symbol ? `${symbol}|${period}` : '',
    (signal) => api.metrics(symbol, period, signal),
  );

  const valuation = data?.valuation ?? null;
  const empty = data !== null && data.groups.length === 0;

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface" data-testid="metrics-tab">
      <header className="flex shrink-0 items-center gap-3 border-b border-line px-3 py-1.5">
        <h2 className="font-mono text-[11px] font-semibold tracking-wide text-ink-2">METRICS</h2>
        <PeriodToggle value={period} onChange={setPeriod} testIdPrefix="metrics" />
        {data?.currency && data.groups.length > 0 && (
          <span
            className="font-mono text-[10px] text-ink-3"
            data-testid="metrics-currency"
            title="The currency this company files its statements in"
          >
            in {data.currency}
          </span>
        )}
        {loading && <span className="font-mono text-[10px] text-ink-3">loading…</span>}
      </header>

      {valuation && (
        <section
          className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-1 border-b border-line bg-panel px-3 py-2"
          data-testid="valuation-strip"
          aria-label="Valuation"
        >
          <Figure label="MCAP" value={formatMoney(valuation.market_cap)} />
          {valuation.note === null && (
            <Figure label="EV" value={formatMoney(valuation.enterprise_value)} />
          )}
          {valuation.multiples.map((multiple) => (
            <Figure
              key={multiple.key}
              label={multiple.label}
              value={formatMetricValue(multiple.value, 'multiple')}
              testId={`multiple-${multiple.key}`}
            />
          ))}
          {/* Why the multiples are blank, when they are. A row of dashes
              with no reason reads as missing data rather than a refusal. */}
          <span className="ml-auto font-mono text-[9px] uppercase tracking-wide text-ink-3">
            {valuation.note ? (
              <span className="normal-case text-down" data-testid="valuation-note">
                {valuation.note}
              </span>
            ) : (
              `multiples on ${valuation.basis}${
                valuation.source === 'filings' ? '' : ` · via ${valuation.source}`
              }`
            )}
          </span>
        </section>
      )}

      {error ? (
        <LoadError what={`${symbol}'s metrics`} error={error} testId="metrics-error" />
      ) : empty ? (
        <p className="p-4 font-mono text-[11px] text-ink-3" data-testid="metrics-empty">
          {data?.available === false
            ? 'SEC filings are switched off for this terminal.'
            : `Nothing to measure — no statements on file for ${symbol}.`}
        </p>
      ) : (
        <div className="scroll-thin min-h-0 flex-1 overflow-auto">
          <table className="tnum w-full border-collapse font-mono text-[11px]">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr className="border-b border-line-strong">
                <th
                  scope="col"
                  className="sticky left-0 z-10 bg-surface px-3 py-1.5 text-left font-semibold text-ink-2"
                >
                  {data?.period === 'quarterly' ? 'Quarter' : 'Fiscal year'}
                </th>
                {(data?.periods ?? []).map((entry) => (
                  <th
                    key={entry.key}
                    scope="col"
                    className="whitespace-nowrap px-3 py-1.5 text-right font-semibold text-ink"
                  >
                    {entry.key}
                    <span className="block text-[9px] font-normal text-ink-3">{entry.end}</span>
                  </th>
                ))}
              </tr>
            </thead>
            {(data?.groups ?? []).map((group) => (
              <tbody key={group.label} data-testid={`metric-group-${group.label.toLowerCase()}`}>
                <tr>
                  <th
                    scope="colgroup"
                    colSpan={(data?.periods.length ?? 0) + 1}
                    className="sticky left-0 bg-elevated px-3 py-1 text-left text-[10px] font-bold uppercase tracking-wide text-ink-3"
                  >
                    {group.label}
                  </th>
                </tr>
                {group.metrics.map((row) => (
                  <tr key={row.key} className="border-b border-line/50 hover:bg-elevated/60">
                    <th
                      scope="row"
                      data-testid={`metric-row-${row.key}`}
                      className="sticky left-0 z-[1] whitespace-nowrap bg-surface px-3 py-1 text-left font-normal text-ink-2"
                    >
                      {row.label}
                    </th>
                    {row.values.map((value, index) => (
                      <td
                        key={data?.periods[index]?.key ?? index}
                        className={`whitespace-nowrap px-3 py-1 text-right ${
                          value == null ? 'text-ink-3' : value < 0 ? 'text-down' : 'text-ink'
                        }`}
                      >
                        {formatMetricValue(value, row.unit, data?.symbol_prefix)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
    </div>
  );
}

function Figure({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <span className="flex items-baseline gap-1.5" data-testid={testId}>
      <span className="font-mono text-[9px] uppercase tracking-wide text-ink-3">{label}</span>
      <span className="tnum font-mono text-[12px] font-semibold text-ink">{value}</span>
    </span>
  );
}
