import { useEffect, useState } from 'react';

import { formatStatementValue } from '@/lib/format';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { FinancialPeriodKind, FinancialsResponse } from '@/types/protocol';

/**
 * The income statement, balance sheet and cash flow, as filed.
 *
 * Read left to right, newest first, the way a chart is read — the most
 * recent close sits at the right edge of the price pane and the most recent
 * period sits at the left of this table, because a table is scanned from its
 * label outwards rather than from its far edge inwards.
 *
 * Two things are shown that a statement normally hides.
 *
 * The **period end** sits under every column heading. "FY2026" is a
 * convention and companies with the same January year-end disagree about it,
 * so the close is printed as the fact and the label as the shorthand.
 *
 * The **XBRL tags** are on each row, behind a hover. Which concept answered
 * is part of reading the number: a revenue line stitched across an ASC 606
 * change is two tags, and a reader comparing to a filing needs to know which
 * one they are looking at.
 */

const PERIODS: Array<{ id: FinancialPeriodKind; label: string }> = [
  { id: 'annual', label: 'Annual' },
  { id: 'quarterly', label: 'Quarterly' },
];

/** Lines whose row is a subtotal rather than a component. */
const EMPHASISED = new Set([
  'revenue',
  'gross_profit',
  'operating_income',
  'net_income',
  'total_assets',
  'total_liabilities',
  'equity',
  'operating_cash_flow',
]);

export function FinancialsTab() {
  const symbol = useTerminalStore((state) => state.symbol);
  const [period, setPeriod] = useState<FinancialPeriodKind>('annual');
  const [data, setData] = useState<FinancialsResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    setLoading(true);
    void (async () => {
      try {
        setData(await api.financials(symbol, period, controller.signal));
      } catch {
        if (!controller.signal.aborted) setData(null);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [symbol, period]);

  const empty = data !== null && data.periods.length === 0;

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface" data-testid="financials-tab">
      <header className="flex shrink-0 items-center gap-3 border-b border-line px-3 py-1.5">
        <h2 className="font-mono text-[11px] font-semibold tracking-wide text-ink-2">
          FINANCIALS
        </h2>
        <div className="flex gap-1" role="group" aria-label="Reporting period">
          {PERIODS.map((choice) => (
            <button
              key={choice.id}
              type="button"
              onClick={() => setPeriod(choice.id)}
              aria-pressed={period === choice.id}
              data-testid={`financials-period-${choice.id}`}
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
        {data?.note && (
          <span className="truncate font-mono text-[10px] text-down" title={data.note}>
            {data.note}
          </span>
        )}
        {loading && <span className="font-mono text-[10px] text-ink-3">loading…</span>}
      </header>

      {empty ? (
        <p className="p-4 font-mono text-[11px] text-ink-3" data-testid="financials-empty">
          {data?.available === false
            ? 'SEC filings are switched off for this terminal.'
            : `No XBRL statements on file for ${symbol}.`}
        </p>
      ) : (
        /* The table scrolls inside its own box: twelve quarters is wider than
           the column, and the terminal must never scroll sideways as a whole. */
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
            {(data?.statements ?? []).map((statement) => (
              <tbody key={statement.key} data-testid={`statement-${statement.key}`}>
                <tr>
                  <th
                    scope="colgroup"
                    colSpan={(data?.periods.length ?? 0) + 1}
                    className="sticky left-0 bg-elevated px-3 py-1 text-left text-[10px] font-bold uppercase tracking-wide text-ink-3"
                  >
                    {statement.label}
                  </th>
                </tr>
                {statement.lines.map((line) => (
                  <tr key={line.key} className="border-b border-line/50 hover:bg-elevated/60">
                    <th
                      scope="row"
                      title={line.concepts.join(' · ')}
                      data-testid={`financials-row-${line.key}`}
                      className={`sticky left-0 z-[1] whitespace-nowrap bg-surface px-3 py-1 text-left font-normal ${
                        EMPHASISED.has(line.key) ? 'font-semibold text-ink' : 'text-ink-2'
                      }`}
                    >
                      {line.label}
                    </th>
                    {line.values.map((value, index) => (
                      <td
                        key={data?.periods[index]?.key ?? index}
                        className={`whitespace-nowrap px-3 py-1 text-right ${
                          value == null
                            ? 'text-ink-3'
                            : value < 0
                              ? 'text-down'
                              : EMPHASISED.has(line.key)
                                ? 'font-semibold text-ink'
                                : 'text-ink-2'
                        }`}
                      >
                        {formatStatementValue(value, line.unit)}
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
