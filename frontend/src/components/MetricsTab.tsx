import { useEffect, useState } from 'react';

import { formatMetricValue, formatMoney } from '@/lib/format';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { FinancialPeriodKind, MetricsResponse } from '@/types/protocol';

/**
 * What the statements mean, and what the market is asking for them.
 *
 * The valuation strip sits on top because it is the one part that moves
 * intraday — it is priced off the live market cap, while everything below it
 * changes four times a year. Its basis is stated rather than assumed: a
 * multiple on a trailing twelve months and one on a fiscal year are
 * different numbers, and which is on screen is a question a reader should
 * never have to work out.
 *
 * A dash is a refusal, not a zero. The backend declines to divide by a
 * negative denominator — P/E on a loss, debt/equity on negative book value —
 * because those render perfectly well and read as the opposite of what they
 * mean.
 */

const PERIODS: Array<{ id: FinancialPeriodKind; label: string }> = [
  { id: 'annual', label: 'Annual' },
  { id: 'quarterly', label: 'Quarterly' },
];

export function MetricsTab() {
  const symbol = useTerminalStore((state) => state.symbol);
  const [period, setPeriod] = useState<FinancialPeriodKind>('annual');
  const [data, setData] = useState<MetricsResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    setLoading(true);
    void (async () => {
      try {
        setData(await api.metrics(symbol, period, controller.signal));
      } catch {
        if (!controller.signal.aborted) setData(null);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [symbol, period]);

  const valuation = data?.valuation ?? null;
  const empty = data !== null && data.groups.length === 0;

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface" data-testid="metrics-tab">
      <header className="flex shrink-0 items-center gap-3 border-b border-line px-3 py-1.5">
        <h2 className="font-mono text-[11px] font-semibold tracking-wide text-ink-2">METRICS</h2>
        <div className="flex gap-1" role="group" aria-label="Reporting period">
          {PERIODS.map((choice) => (
            <button
              key={choice.id}
              type="button"
              onClick={() => setPeriod(choice.id)}
              aria-pressed={period === choice.id}
              data-testid={`metrics-period-${choice.id}`}
              className={`rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-bold leading-4 ${
                period === choice.id
                  ? 'bg-accent/20 text-accent-text'
                  : 'text-ink-3 hover:text-ink-2'
              }`}
            >
              {choice.label.toUpperCase()}
            </button>
          ))}
        </div>
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

      {empty ? (
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
