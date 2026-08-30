import { useEffect, useState } from 'react';

import { daysUntil, formatCompact, formatMoney, formatPrice } from '@/lib/format';
import { api } from '@/lib/http';
import type { SwingRow, SwingScreen } from '@/types/protocol';

/**
 * Multi-day setups, from daily structure.
 *
 * Each screen states what it is looking for in a line, because a setup
 * nobody can read is a setup nobody will act on — and because two of these
 * differ only in how far off the high they want, which is not something a
 * name can carry.
 *
 * The distance from the 52-week high is the column that decides most of
 * these, so it is always shown and always signed: at the high is 0.0%, and
 * everything else is how far under.
 */

const REFRESH_MS = 60_000;

export function SwingPanel({ onSelect }: { onSelect: (symbol: string) => void }) {
  const [screens, setScreens] = useState<SwingScreen[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [rows, setRows] = useState<SwingRow[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const payload = await api.swingScreens(controller.signal);
        // Defensive about the shape, not just the request. A payload that
        // arrives without its list is a white screen for the whole terminal
        // otherwise — one panel's bad response must not take the chart down
        // with it.
        const list = Array.isArray(payload?.screens) ? payload.screens : [];
        setScreens(list);
        setActive((current) => current ?? list[0]?.id ?? null);
      } catch {
        if (!controller.signal.aborted) setNote('Could not reach the backend.');
      }
    })();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();

    const load = async () => {
      setLoading(true);
      try {
        const payload = await api.swingRows(active, controller.signal);
        setRows(Array.isArray(payload?.rows) ? payload.rows : []);
        setNote(payload?.note ?? null);
      } catch {
        if (!controller.signal.aborted) setNote('Could not reach the backend.');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };

    void load();
    // A daily setup does not change by the second, but a screen left open
    // all session should not go stale either.
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [active]);

  const screen = screens.find((entry) => entry.id === active) ?? null;

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="swing-panel">
      <div className="flex flex-wrap gap-1 border-b border-line px-2 py-1.5">
        {screens.map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => setActive(entry.id)}
            aria-pressed={entry.id === active}
            title={entry.note}
            data-testid={`swing-screen-${entry.id}`}
            className={`rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-bold leading-4 ${
              entry.id === active ? 'bg-accent/20 text-accent-text' : 'text-ink-3 hover:text-ink-2'
            }`}
          >
            {entry.label.toUpperCase()}
          </button>
        ))}
      </div>

      {screen && (
        <p className="px-2 py-1 text-[10px] leading-snug text-ink-3" data-testid="swing-note">
          {screen.note}
        </p>
      )}
      {note && (
        <p className="px-2 py-1 text-[10px] text-down" data-testid="swing-warning">
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
              <th scope="col" className="px-2 py-1 text-right font-normal" title="Below the 52-week high">
                52W
              </th>
              <th scope="col" className="px-2 py-1 text-right font-normal" title="Three-month performance">
                3M
              </th>
              <th scope="col" className="px-2 py-1 text-right font-normal">
                RVOL
              </th>
              <th scope="col" className="px-2 py-1 text-right font-normal">
                MCAP
              </th>
              <th
                scope="col"
                className="px-2 py-1 text-right font-normal"
                title="Days until the next scheduled report"
              >
                ERN
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.symbol}
                onClick={() => onSelect(row.symbol)}
                data-testid={`swing-row-${row.symbol}`}
                title={`${row.name} · ${row.sector}`}
                className="cursor-pointer border-b border-line/40 hover:bg-elevated"
              >
                <td className="px-2 py-1 font-semibold text-ink">{row.symbol}</td>
                <td className="px-2 py-1 text-right text-ink-2">{formatPrice(row.close)}</td>
                <td
                  className={`px-2 py-1 text-right ${
                    (row.change ?? 0) < 0 ? 'text-down' : 'text-up'
                  }`}
                >
                  {signed(row.change)}
                </td>
                <td className="px-2 py-1 text-right text-ink-3">{signed(row.off_high)}</td>
                <td
                  className={`px-2 py-1 text-right ${
                    (row.perf_quarter ?? 0) < 0 ? 'text-down' : 'text-ink-2'
                  }`}
                >
                  {signed(row.perf_quarter)}
                </td>
                <td className="px-2 py-1 text-right text-ink-2">
                  {row.rvol == null ? '—' : `${row.rvol.toFixed(2)}×`}
                </td>
                <td className="px-2 py-1 text-right text-ink-3">
                  {row.market_cap == null ? '—' : formatMoney(row.market_cap)}
                </td>
                <Earnings epoch={row.next_earnings} />
              </tr>
            ))}
          </tbody>
        </table>

        {!loading && rows.length === 0 && !note && (
          <p className="px-2 py-3 text-[10px] text-ink-3" data-testid="swing-empty">
            Nothing qualifies right now. That is a market state, not a fault.
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * How near the next report is.
 *
 * A breakout entered three days before earnings is a different trade, so the
 * cell shouts inside a week and stays quiet beyond it. A date already past —
 * the source keeps serving one for a while — is nothing at all.
 */
function Earnings({ epoch }: { epoch: number | null }) {
  const days = daysUntil(epoch, Date.now() / 1000);
  if (days == null || days < 0 || days > 60) {
    return <td className="px-2 py-1 text-right text-ink-3">—</td>;
  }
  return (
    <td
      className={`px-2 py-1 text-right ${days <= 7 ? 'font-semibold text-down' : 'text-ink-3'}`}
      data-testid="swing-earnings"
    >
      {days}d
    </td>
  );
}

/** A percentage that always carries its sign; distance is meaningless without one. */
function signed(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const shown = Math.abs(value) >= 1000 ? formatCompact(value, 0) : value.toFixed(1);
  return `${value > 0 ? '+' : ''}${shown}%`;
}
