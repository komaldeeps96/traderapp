import { useEffect, useState } from 'react';

import { formatMetricValue, formatMoney } from '@/lib/format';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { PeerRank, PeerRow, PeersResponse } from '@/types/protocol';

/**
 * The company beside the ones it competes with.
 *
 * A ratio on its own is not a judgement: 39× earnings is expensive for a
 * utility and cheap for a chip designer. The ranking strip at the top says
 * where this company sits in its own industry on each measure, and the
 * median beside it says what "normal" is here — which is the number that
 * makes the company's own figure mean something.
 *
 * First is always best, and which end that is depends on the measure: a low
 * P/E ranks well, a low gross margin does not. The backend decides that; the
 * table only draws it.
 */

const RANK_TONE = (position: number | null, total: number): string => {
  if (position === null || total < 2) return 'text-ink-3';
  const share = (position - 1) / (total - 1);
  if (share <= 0.25) return 'text-up';
  if (share >= 0.75) return 'text-down';
  return 'text-ink-2';
};

export function PeersTab() {
  const symbol = useTerminalStore((state) => state.symbol);
  const [data, setData] = useState<PeersResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    setLoading(true);
    void (async () => {
      try {
        setData(await api.peers(symbol, controller.signal));
      } catch {
        if (!controller.signal.aborted) setData(null);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [symbol]);

  const rows = data?.rows ?? [];
  const ranks = data?.ranks ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface" data-testid="peers-tab">
      <header className="flex shrink-0 items-center gap-3 border-b border-line px-3 py-1.5">
        <h2 className="font-mono text-[11px] font-semibold tracking-wide text-ink-2">PEERS</h2>
        {data?.industry && (
          <span className="font-mono text-[10px] text-ink-3" data-testid="peers-industry">
            {data.industry} · {rows.length}
          </span>
        )}
        {loading && <span className="font-mono text-[10px] text-ink-3">loading…</span>}
        {data?.note && (
          <span className="truncate font-mono text-[10px] text-down" title={data.note}>
            {data.note}
          </span>
        )}
      </header>

      {ranks.length > 0 && (
        <section
          className="grid shrink-0 grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-x-4 gap-y-1 border-b border-line bg-panel px-3 py-2"
          data-testid="peer-ranks"
          aria-label="Rank within the industry"
        >
          {ranks.map((entry) => (
            <Rank key={entry.key} entry={entry} />
          ))}
        </section>
      )}

      {rows.length === 0 ? (
        <p className="p-4 font-mono text-[11px] text-ink-3" data-testid="peers-empty">
          {data?.available === false
            ? 'The TradingView screener is switched off for this terminal.'
            : `No industry peers on file for ${symbol}.`}
        </p>
      ) : (
        <div className="scroll-thin min-h-0 flex-1 overflow-auto">
          <table className="tnum w-full border-collapse font-mono text-[11px]">
            <thead className="sticky top-0 z-10 bg-surface text-[10px] text-ink-3">
              <tr className="border-b border-line-strong">
                <th scope="col" className="sticky left-0 bg-surface px-3 py-1.5 text-left font-normal">
                  SYM
                </th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">MCAP</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">P/E</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">P/S</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">P/B</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">GM</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">OM</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">ROE</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">D/E</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">YTD</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <Row key={row.symbol} row={row} subject={row.symbol === symbol} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Rank({ entry }: { entry: PeerRank }) {
  return (
    <span className="flex items-baseline gap-1.5" data-testid={`peer-rank-${entry.key}`}>
      <span className="font-mono text-[9px] uppercase tracking-wide text-ink-3">
        {entry.label}
      </span>
      <span className={`tnum font-mono text-[12px] font-semibold ${RANK_TONE(entry.position, entry.total)}`}>
        {entry.position === null ? '—' : `${entry.position}/${entry.total}`}
      </span>
      <span className="font-mono text-[9px] text-ink-3" title="Industry median">
        med {formatMetricValue(entry.median, entry.unit)}
      </span>
    </span>
  );
}

function Row({ row, subject }: { row: PeerRow; subject: boolean }) {
  const cell = (value: number | null, unit: string) => (
    <td className={`whitespace-nowrap px-3 py-1 text-right ${subject ? 'text-ink' : 'text-ink-2'}`}>
      {formatMetricValue(value, unit)}
    </td>
  );

  return (
    <tr
      data-testid={`peer-row-${row.symbol}`}
      data-subject={subject}
      title={row.name}
      className={`border-b border-line/50 ${
        subject ? 'bg-accent/10 font-semibold' : 'hover:bg-elevated/60'
      }`}
    >
      <th
        scope="row"
        className={`sticky left-0 z-[1] px-3 py-1 text-left font-normal ${
          subject ? 'bg-accent/10 font-semibold text-accent-text' : 'bg-surface text-ink'
        }`}
      >
        {row.symbol}
      </th>
      <td className="whitespace-nowrap px-3 py-1 text-right text-ink-3">
        {row.market_cap == null ? '—' : formatMoney(row.market_cap)}
      </td>
      {cell(row.price_earnings, 'multiple')}
      {cell(row.price_sales, 'multiple')}
      {cell(row.price_book, 'multiple')}
      {/* Percentages arrive as fractions; the backend converts TradingView's
          whole percents once, so the median in the strip above agrees. */}
      {cell(row.gross_margin, 'percent')}
      {cell(row.operating_margin, 'percent')}
      {cell(row.return_on_equity, 'percent')}
      {cell(row.debt_to_equity, 'ratio')}
      {cell(row.perf_ytd, 'percent')}
    </tr>
  );
}
