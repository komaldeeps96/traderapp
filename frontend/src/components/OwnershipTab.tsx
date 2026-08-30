import { useEffect, useState } from 'react';

import { formatCompact, formatMoney, formatPrice } from '@/lib/format';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { InsiderIntent, InsiderTrade, OwnershipResponse } from '@/types/protocol';

/**
 * What insiders have actually done.
 *
 * Most of a Form 4 trail is payroll. Grants, option exercises and shares
 * withheld to cover the tax on a vest move the share count and say nothing
 * about what anyone thinks — counting them is how "insiders dumped stock"
 * headlines get written about a vesting date.
 *
 * So the summary leads with the two things that carry information: cash
 * spent at the market, and sales that were *decided* rather than scheduled.
 * A 10b5-1 plan sale is set months ahead and is as automatic as a payroll
 * deduction, so it is shown separately rather than netted.
 *
 * The rows below keep everything, because the reason a number is small
 * matters: "no insider buying" and "no insider filings at all" are different
 * facts about a company.
 */

const INTENT_CLASS: Record<InsiderIntent, string> = {
  buy: 'text-up font-semibold',
  sell: 'text-down',
  compensation: 'text-ink-3',
  other: 'text-ink-3',
};

export function OwnershipTab() {
  const symbol = useTerminalStore((state) => state.symbol);
  const [data, setData] = useState<OwnershipResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    setLoading(true);
    void (async () => {
      try {
        setData(await api.ownership(symbol, controller.signal));
      } catch {
        if (!controller.signal.aborted) setData(null);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [symbol]);

  const summary = data?.summary ?? null;
  const trades = data?.trades ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface" data-testid="ownership-tab">
      <header className="flex shrink-0 items-center gap-3 border-b border-line px-3 py-1.5">
        <h2 className="font-mono text-[11px] font-semibold tracking-wide text-ink-2">INSIDERS</h2>
        {summary && (
          <span className="font-mono text-[10px] text-ink-3">
            last {summary.window_days} days
          </span>
        )}
        {loading && <span className="font-mono text-[10px] text-ink-3">loading…</span>}
        {data?.note && (
          <span className="truncate font-mono text-[10px] text-down" title={data.note}>
            {data.note}
          </span>
        )}
      </header>

      {summary && (
        <section
          className="shrink-0 border-b border-line bg-panel px-3 py-2"
          data-testid="insider-summary"
          aria-label="Insider activity"
        >
          <p className="mb-1.5 font-mono text-[12px] font-semibold text-ink" data-testid="insider-verdict">
            {summary.verdict}
          </p>
          <div className="flex flex-wrap gap-x-5 gap-y-1">
            <Total label="Bought" tone="text-up" total={summary.buys} testId="insider-buys" />
            <Total
              label="Sold (decided)"
              tone="text-down"
              total={summary.discretionary_sells}
              testId="insider-sells"
            />
            <Total
              label="Sold (10b5-1 plan)"
              tone="text-ink-3"
              total={summary.planned_sells}
              testId="insider-planned"
            />
            <Total
              label="Compensation"
              tone="text-ink-3"
              total={summary.compensation}
              testId="insider-comp"
            />
          </div>
        </section>
      )}

      {trades.length === 0 ? (
        <p className="p-4 font-mono text-[11px] text-ink-3" data-testid="ownership-empty">
          {data?.available === false
            ? 'SEC filings are switched off for this terminal.'
            : `No Form 4 filings on record for ${symbol}.`}
        </p>
      ) : (
        <div className="scroll-thin min-h-0 flex-1 overflow-auto">
          <table className="tnum w-full border-collapse font-mono text-[11px]">
            <thead className="sticky top-0 z-10 bg-surface text-[10px] text-ink-3">
              <tr className="border-b border-line-strong">
                <th scope="col" className="px-3 py-1.5 text-left font-normal">DATE</th>
                <th scope="col" className="px-3 py-1.5 text-left font-normal">INSIDER</th>
                <th scope="col" className="px-3 py-1.5 text-left font-normal">ACTION</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">SHARES</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">PRICE</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">VALUE</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal" title="Shares held afterwards">
                  AFTER
                </th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade, index) => (
                <Row key={`${trade.url}-${index}`} trade={trade} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Row({ trade }: { trade: InsiderTrade }) {
  return (
    <tr
      className="border-b border-line/50 hover:bg-elevated/60"
      data-testid={`insider-row-${trade.code}`}
      data-intent={trade.intent}
    >
      <td className="whitespace-nowrap px-3 py-1 text-ink-3">{trade.traded}</td>
      <td className="px-3 py-1 text-ink-2" title={trade.role}>
        {trade.owner}
      </td>
      <td className={`whitespace-nowrap px-3 py-1 ${INTENT_CLASS[trade.intent]}`}>
        {trade.note}
        {trade.planned && (
          <span
            className="ml-1.5 rounded-sm bg-elevated px-1 text-[9px] font-bold text-ink-3"
            title="Scheduled under a 10b5-1 plan adopted months earlier, not a decision made now"
          >
            PLAN
          </span>
        )}
      </td>
      <td className="px-3 py-1 text-right text-ink-2">
        {trade.shares == null ? '—' : formatCompact(trade.shares, 0)}
      </td>
      <td className="px-3 py-1 text-right text-ink-3">
        {trade.price ? formatPrice(trade.price) : '—'}
      </td>
      <td className={`px-3 py-1 text-right ${INTENT_CLASS[trade.intent]}`}>
        {trade.value ? formatMoney(trade.value) : '—'}
      </td>
      <td className="px-3 py-1 text-right text-ink-3">
        {trade.shares_after == null ? '—' : formatCompact(trade.shares_after, 0)}
      </td>
    </tr>
  );
}

function Total({
  label,
  tone,
  total,
  testId,
}: {
  label: string;
  tone: string;
  total: { count: number; value: number; people: number };
  testId: string;
}) {
  return (
    <span className="flex items-baseline gap-1.5" data-testid={testId}>
      <span className="font-mono text-[9px] uppercase tracking-wide text-ink-3">{label}</span>
      <span className={`tnum font-mono text-[12px] font-semibold ${tone}`}>
        {total.count === 0 ? '—' : formatMoney(total.value)}
      </span>
      {total.count > 0 && (
        <span className="font-mono text-[9px] text-ink-3">
          {total.count}× · {total.people} {total.people === 1 ? 'person' : 'people'}
        </span>
      )}
    </span>
  );
}
