import { useEffect, useState } from 'react';

import { useSymbolResource } from '@/hooks/useSymbolResource';
import { formatAsFiled, formatStatementValue } from '@/lib/format';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { ConceptsResponse, FinancialPeriodKind } from '@/types/protocol';

import { LoadError, PeriodToggle } from './PeriodToggle';

/**
 * The income statement, balance sheet and cash flow, as filed.
 *
 * Newest period at the left: a table is scanned from its label outwards.
 *
 * Two things a statement normally hides are shown. The **period end** sits
 * under every column heading, because "FY2026" is a convention companies with
 * the same January year-end disagree about. The **XBRL tags** are on each row
 * behind a hover — a revenue line stitched across an ASC 606 change is two
 * tags, and which one answered is part of reading the number.
 */

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
  const { data, error, loading } = useSymbolResource(
    symbol ? `${symbol}|${period}` : '',
    (signal) => api.financials(symbol, period, signal),
  );
  // The statement is a tenth of what a filer tags. Typing here swaps the
  // table for everything else it reported, on the same period axis.
  const [query, setQuery] = useState('');
  // Held against the search that produced it, like the statements, so an
  // answer for the previous symbol is not drawn under the next.
  const [search, setSearch] = useState<{ key: string; found: ConceptsResponse } | null>(null);
  const needle = query.trim();
  const searchKey = symbol && needle.length >= 3 ? `${symbol}|${period}|${needle}` : '';

  useEffect(() => {
    if (!searchKey) return;
    const controller = new AbortController();
    // Short enough to feel live, long enough not to search each keystroke.
    const timer = setTimeout(() => {
      api.concepts(symbol, needle, period, controller.signal).then(
        (found) => {
          if (!controller.signal.aborted) setSearch({ key: searchKey, found });
        },
        // A failed search leaves the statement on screen.
        () => undefined,
      );
    }, 250);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [searchKey, symbol, needle, period]);

  const found = search?.key === searchKey ? search.found : null;
  const searching = found !== null;
  const empty = !searching && data !== null && data.periods.length === 0;

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface" data-testid="financials-tab">
      <header className="flex shrink-0 items-center gap-3 border-b border-line px-3 py-1.5">
        <h2 className="font-mono text-[11px] font-semibold tracking-wide text-ink-2">
          FINANCIALS
        </h2>
        <PeriodToggle value={period} onChange={setPeriod} testIdPrefix="financials" />
        {/* The caption describes whichever view is on screen. Search rows
            are shown as filed, so a "converted to USD" caption above CAD
            figures would be a plain contradiction. */}
        {searching ? (
          <span
            className="font-mono text-[10px] text-ink-3"
            data-testid="financials-currency"
            title="Search results are shown in the unit the company filed them in"
          >
            as filed
          </span>
        ) : (
          data?.currency &&
          data.periods.length > 0 && (
            <span
              className="font-mono text-[10px] text-ink-3"
              data-testid="financials-currency"
              title="The currency this company files its statements in"
            >
              in {data.currency}
              {data.converted && ` · converted from ${data.native_currency}`}
            </span>
          )
        )}
        {(data?.unconverted_periods?.length ?? 0) > 0 && (
          <span
            className="font-mono text-[10px] text-down"
            data-testid="financials-unconverted"
            title="No exchange rate could be fetched for these periods, so they are left out rather than mixed into a dollar column"
          >
            no rate for {data!.unconverted_periods!.join(', ')}
          </span>
        )}
        {data?.note && (
          <span className="truncate font-mono text-[10px] text-down" title={data.note}>
            {data.note}
          </span>
        )}
        {loading && <span className="font-mono text-[10px] text-ink-3">loading…</span>}
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="search all reported data…"
          aria-label="Search every concept this company reports"
          data-testid="concept-search"
          className="ml-auto w-56 rounded-sm border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
        />
        {searching && (
          <span className="font-mono text-[10px] text-ink-3" data-testid="concept-count">
            {found.total} match{found.total === 1 ? '' : 'es'}
            {found.total > found.rows.length && ` · showing ${found.rows.length}`}
          </span>
        )}
      </header>

      {error ? (
        <LoadError what={`${symbol}'s statements`} error={error} testId="financials-error" />
      ) : empty ? (
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
                  {found ? `Matching “${found.query}”` : data?.period === 'quarterly' ? 'Quarter' : 'Fiscal year'}
                </th>
                {(found?.periods ?? data?.periods ?? []).map((entry) => (
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
            {found ? (
              <tbody data-testid="concept-results">
                {found.rows.length === 0 && (
                  <tr>
                    <td
                      colSpan={found.periods.length + 1}
                      className="px-3 py-3 text-ink-3"
                      data-testid="concept-empty"
                    >
                      Nothing reported matches “{found.query}”.
                    </td>
                  </tr>
                )}
                {found.rows.map((row) => (
                  <tr
                    key={row.key}
                    className="border-b border-line/50 hover:bg-elevated/60"
                    data-testid={`concept-row-${row.concept}`}
                  >
                    <th
                      scope="row"
                      title={`${row.taxonomy}:${row.concept} — as filed, in ${row.unit}`}
                      className="sticky left-0 z-[1] whitespace-nowrap bg-surface px-3 py-1 text-left font-normal text-ink-2"
                    >
                      {row.label}
                      <span className="ml-1.5 text-[9px] text-ink-3">{row.unit}</span>
                    </th>
                    {row.values.map((value, index) => (
                      <td
                        key={found.periods[index]?.key ?? index}
                        className={`whitespace-nowrap px-3 py-1 text-right ${
                          value == null ? 'text-ink-3' : value < 0 ? 'text-down' : 'text-ink-2'
                        }`}
                      >
                        {/* As filed: the unit is whatever the company used,
                            so the number is shown plainly rather than dressed
                            as money it might not be. */}
                        {formatAsFiled(value)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            ) : (
              (data?.statements ?? []).map((statement) => (
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
                        {formatStatementValue(value, line.unit, data?.symbol_prefix)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              ))
            )}
          </table>
        </div>
      )}
    </div>
  );
}
