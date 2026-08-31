import { useEffect, useState } from 'react';

import { daysUntil, formatCompact, formatMoney, formatPrice } from '@/lib/format';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { WatchlistRow } from '@/types/protocol';

/**
 * The symbols this desk is watching. Nothing else.
 *
 * No folders, no groups, no sort. The order is the order things were added,
 * because that order is itself information: the name put here this morning is
 * usually the one being worked, and a list that re-sorts itself under the
 * cursor costs more than the tidiness is worth.
 *
 * The list lives on the server, so both windows and a page reload see the
 * same one. Edits are sent and not applied locally — the broadcast that comes
 * back is what renders, which is what keeps two open terminals in step.
 */
export function WatchlistPanel({ onSelect }: { onSelect: (symbol: string) => void }) {
  const symbols = useTerminalStore((state) => state.watchlist);
  const rows = useTerminalStore((state) => state.watchlistRows);
  const note = useTerminalStore((state) => state.watchlistNote);
  const setWatchlist = useTerminalStore((state) => state.setWatchlist);
  const add = useTerminalStore((state) => state.addToWatchlist);
  const remove = useTerminalStore((state) => state.removeFromWatchlist);
  const [draft, setDraft] = useState('');

  // The socket pushes the list on connect and after every edit. This is the
  // one case it cannot cover: a reload that lands before the socket is up.
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const payload = await api.watchlist(controller.signal);
        setWatchlist({
          symbols: Array.isArray(payload?.symbols) ? payload.symbols : [],
          rows: Array.isArray(payload?.rows) ? payload.rows : [],
          note: payload?.note ?? null,
        });
      } catch {
        // The socket will fill it in a moment; an empty list is the honest
        // thing to show until then.
      }
    })();
    return () => controller.abort();
  }, [setWatchlist]);

  const submit = () => {
    const wanted = draft.trim().toUpperCase();
    if (!wanted) return;
    add(wanted);
    setDraft('');
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="watchlist-panel">
      <div className="flex items-center gap-1 border-b border-line px-2 py-1.5">
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') submit();
          }}
          placeholder="ADD SYMBOL"
          aria-label="Add a symbol to the watchlist"
          data-testid="watchlist-input"
          maxLength={12}
          spellCheck={false}
          className="min-w-0 flex-1 rounded-sm border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] uppercase text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
        />
        <button
          type="button"
          onClick={submit}
          data-testid="watchlist-add"
          className="rounded-sm border border-line px-1.5 py-0.5 font-mono text-[10px] font-bold text-ink-2 hover:border-accent hover:text-accent-text"
        >
          ADD
        </button>
      </div>

      {note && (
        <p className="px-2 py-1 text-[10px] text-down" data-testid="watchlist-warning">
          {note}
        </p>
      )}

      <div className="scroll-thin min-h-0 flex-1 overflow-auto">
        <table className="tnum w-full font-mono text-[11px]">
          <thead className="sticky top-0 bg-panel text-[10px] text-ink-3">
            <tr>
              <th scope="col" className="px-2 py-1 text-left font-normal">
                SYM
              </th>
              <th scope="col" className="px-2 py-1 text-right font-normal">
                PRICE
              </th>
              <th scope="col" className="px-2 py-1 text-right font-normal">
                CHG
              </th>
              <th
                scope="col"
                className="px-2 py-1 text-right font-normal"
                title="Pre-market change, from the previous close"
              >
                PM
              </th>
              <th scope="col" className="px-2 py-1 text-right font-normal">
                RVOL
              </th>
              <th
                scope="col"
                className="px-2 py-1 text-right font-normal"
                title="Days until the next scheduled report"
              >
                ERN
              </th>
              {/* The remove control's column. Unlabelled: a header over an
                  icon reads as another data column. */}
              <th scope="col" className="w-6 px-1 py-1" aria-label="Remove" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Row key={row.symbol} row={row} onSelect={onSelect} onRemove={remove} />
            ))}
          </tbody>
        </table>

        {symbols.length === 0 && (
          <p className="px-2 py-3 text-[10px] leading-snug text-ink-3" data-testid="watchlist-empty">
            Nothing on the list. Type a symbol above, or hit the star beside the
            chart symbol.
          </p>
        )}
      </div>
    </div>
  );
}

function Row({
  row,
  onSelect,
  onRemove,
}: {
  row: WatchlistRow;
  onSelect: (symbol: string) => void;
  onRemove: (symbol: string) => void;
}) {
  // A symbol the screener does not know still gets a row — a delisted or
  // mistyped ticker has to stay visible, because it is still on the list and
  // this is the only place it can be taken off.
  const unknown = row.close == null;

  return (
    <tr
      onClick={() => onSelect(row.symbol)}
      data-testid={`watchlist-row-${row.symbol}`}
      title={rowTitle(row)}
      className="group cursor-pointer border-b border-line/40 hover:bg-elevated"
    >
      <td className={`px-2 py-1 font-semibold ${unknown ? 'text-ink-3' : 'text-ink'}`}>
        {row.symbol}
      </td>
      <td className="px-2 py-1 text-right text-ink-2">{formatPrice(row.close)}</td>
      <td className={`px-2 py-1 text-right ${tint(row.change, 'text-up')}`}>
        {signed(row.change)}
      </td>
      <td className={`px-2 py-1 text-right ${tint(row.premarket_change, 'text-ink-3')}`}>
        {signed(row.premarket_change)}
      </td>
      <td className="px-2 py-1 text-right text-ink-2">
        {row.rvol == null ? '—' : `${row.rvol.toFixed(2)}×`}
      </td>
      <Earnings epoch={row.next_earnings} />
      <td className="w-6 px-1 py-1 text-right">
        <button
          type="button"
          onClick={(event) => {
            // Otherwise removing a row also loads its chart, which is the
            // opposite of what the click meant.
            event.stopPropagation();
            onRemove(row.symbol);
          }}
          aria-label={`Remove ${row.symbol} from the watchlist`}
          data-testid={`watchlist-remove-${row.symbol}`}
          className="px-0.5 text-[11px] leading-none text-ink-3 opacity-0 transition-opacity hover:text-down focus:opacity-100 group-hover:opacity-100"
        >
          ×
        </button>
      </td>
    </tr>
  );
}

/**
 * The name, and the size — on hover rather than in a column.
 *
 * Market capitalisation does not change while the panel is open, so it earns
 * no width in a 320px sidebar that has to fit seven live numbers. It is still
 * a fact worth having about a name you are watching, so it goes here.
 */
function rowTitle(row: WatchlistRow): string {
  if (!row.name) return 'No quote for this symbol';
  if (row.market_cap == null) return row.name;
  return `${row.name} · ${formatMoney(row.market_cap)}`;
}

/** Same rule the swing panel uses: shout inside a week, quiet beyond it. */
function Earnings({ epoch }: { epoch: number | null }) {
  const days = daysUntil(epoch, Date.now() / 1000);
  if (days == null || days < 0 || days > 60) {
    return <td className="px-2 py-1 text-right text-ink-3">—</td>;
  }
  return (
    <td
      className={`px-2 py-1 text-right ${days <= 7 ? 'font-semibold text-down' : 'text-ink-3'}`}
      data-testid="watchlist-earnings"
    >
      {days}d
    </td>
  );
}

/**
 * Red below zero, `whenUp` above it — and neither when there is no number.
 *
 * A dash tinted green reads as a small gain rather than as nothing known,
 * which on a delisted symbol is the opposite of the truth.
 */
function tint(value: number | null, whenUp: string): string {
  if (value == null || !Number.isFinite(value)) return 'text-ink-3';
  return value < 0 ? 'text-down' : whenUp;
}

/** A percentage that always carries its sign. */
function signed(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const shown = Math.abs(value) >= 1000 ? formatCompact(value, 0) : value.toFixed(1);
  return `${value > 0 ? '+' : ''}${shown}%`;
}
