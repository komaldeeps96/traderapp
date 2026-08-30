import { useEffect, useState } from 'react';

import { formatAsFiled, formatStatementValue } from '@/lib/format';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type {
  ConceptsResponse,
  FinancialPeriodKind,
  FinancialsResponse,
} from '@/types/protocol';

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
  // The statement is a tenth of what a filer tags. Typing here swaps the
  // table for everything else it reported, on the same period axis.
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<ConceptsResponse | null>(null);

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

  useEffect(() => {
    const needle = query.trim();
    if (!symbol || needle.length < 3) {
      setFound(null);
      return;
    }
    const controller = new AbortController();
    // Short enough to feel live, long enough not to search each keystroke.
    const timer = setTimeout(() => {
      void (async () => {
        try {
          setFound(await api.concepts(symbol, needle, period, controller.signal));
        } catch {
          if (!controller.signal.aborted) setFound(null);
        }
      })();
    }, 250);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [symbol, query, period]);

  const searching = found !== null;
  const empty = !searching && data !== null && data.periods.length === 0;

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
