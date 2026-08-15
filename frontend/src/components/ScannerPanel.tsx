import { useEffect, useState, type FormEvent } from 'react';

import { formatCompact, formatMoney, formatPercent, formatPrice } from '@/lib/format';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { ClientCommand } from '@/types/protocol';

type ScannerOverrides = Omit<Extract<ClientCommand, { action: 'scanner.configure' }>, 'action'>;

interface ScannerPanelProps {
  onSelect: (symbol: string) => void;
  onConfigure: (config: ScannerOverrides) => void;
}

const INPUT =
  'w-full rounded-sm border border-line bg-elevated px-1 py-0.5 text-[10px] text-ink outline-none focus:border-accent';

/**
 * The IBKR trade-rate scanner.
 *
 * The edge it carries is the tape: trades-per-minute and dollar
 * volume over sliding windows, straight from live prints. IBKR-only, with no
 * fallback, so when TWS is absent the panel says so plainly.
 */
export function ScannerPanel({ onSelect, onConfigure }: ScannerPanelProps) {
  const rows = useTerminalStore((state) => state.scannerRows);
  // Availability tracks the LIVE connection state from status frames, not
  // the REST snapshot taken at page load — a page opened during a backend
  // restart would otherwise cache "unavailable" and disable the filters
  // forever, long after TWS reconnected.
  const available = useTerminalStore((state) => state.ibkrConnected);
  const note = useTerminalStore((state) => state.scannerNote);
  const activeSymbol = useTerminalStore((state) => state.symbol);
  const [showFilters, setShowFilters] = useState(false);

  return (
    <section className="flex min-h-0 flex-col border-b border-line" data-testid="scanner">
      <div className="flex shrink-0 items-center gap-2 px-2 pb-1 pt-1.5">
        <h2 className="text-[10px] font-bold uppercase tracking-wider text-ink-3">
          Trade-rate scanner
        </h2>
        <button
          type="button"
          onClick={() => setShowFilters((v) => !v)}
          aria-expanded={showFilters}
          data-testid="scanner-filter-toggle"
          className="ml-auto rounded-sm border border-line px-1 text-[9px] font-bold uppercase text-ink-3 hover:text-ink"
        >
          {showFilters ? 'Hide' : 'Filters'}
        </button>
        <span className="tnum text-[9px] font-semibold text-ink-3" data-testid="scanner-count">
          {rows.length} rows
        </span>
      </div>

      {showFilters && <ScannerFilters onConfigure={onConfigure} disabled={!available} />}

      {!available ? (
        <p className="px-2 py-2 text-[10px] leading-snug text-ink-3" data-testid="scanner-note">
          {note ?? 'Market scanner is unavailable.'}
        </p>
      ) : (
        <div className="scroll-thin min-h-0 flex-1 overflow-auto">
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">Market scanner results</caption>
            <thead className="sticky top-0 z-10 bg-panel">
              <tr className="text-[9px] font-bold uppercase tracking-wider text-ink-3">
                <th scope="col" className="py-0.5 pl-2">Sym</th>
                <th scope="col" className="py-0.5 pr-1 text-right">Price</th>
                <th scope="col" className="py-0.5 pr-1 text-right">Chg</th>
                <th scope="col" className="py-0.5 pr-1 text-right">Vol</th>
                <th scope="col" className="py-0.5 pr-1 text-right" title="Free float in shares — from TradingView">
                  Float
                </th>
                <th scope="col" className="py-0.5 pr-1 text-right" title="Market capitalisation">
                  MCap
                </th>
                <th scope="col" className="py-0.5 pr-1 text-right" title="Trades per minute — IBKR's own rate, as in TWS">
                  T/1m
                </th>
                <th scope="col" className="py-0.5 pr-2 text-right" title="Dollar volume per minute (volume rate × price)">
                  $/1m
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-2 py-3 text-center text-[10px] text-ink-3">
                    Waiting for scanner results…
                  </td>
                </tr>
              )}
              {rows.map((row) => (
                <tr
                  key={row.symbol}
                  data-testid={`scanner-row-${row.symbol}`}
                  className={`cursor-pointer border-t border-line/60 hover:bg-elevated ${
                    row.symbol === activeSymbol ? 'bg-accent/10' : ''
                  }`}
                  onClick={() => onSelect(row.symbol)}
                >
                  <th scope="row" className="py-0.5 pl-2 text-left text-[10px] font-bold text-ink">
                    <button type="button" className="hover:text-accent">
                      {row.symbol}
                    </button>
                    <RankMove delta={row.rank_delta} entered={row.entered} />
                  </th>
                  <td className="tnum py-0.5 pr-1 text-right font-mono text-[10px] text-ink-2">
                    {formatPrice(row.price)}
                  </td>
                  <td
                    className={`tnum py-0.5 pr-1 text-right font-mono text-[10px] font-semibold ${
                      (row.pct_change ?? 0) >= 0 ? 'text-up' : 'text-down'
                    }`}
                  >
                    {formatPercent(row.pct_change, 0)}
                  </td>
                  <td className="tnum py-0.5 pr-1 text-right font-mono text-[9px] text-ink-3">
                    {formatCompact(row.volume, 1)}
                  </td>
                  <td className="tnum py-0.5 pr-1 text-right font-mono text-[9px] text-ink-3">
                    {row.float_shares == null ? '·' : formatCompact(row.float_shares, 1)}
                  </td>
                  <td className="tnum py-0.5 pr-1 text-right font-mono text-[9px] text-ink-3">
                    {row.market_cap == null ? '·' : formatMoney(row.market_cap)}
                  </td>
                  <td className="tnum py-0.5 pr-1 text-right font-mono text-[9px] text-ink-3">
                    {formatCompact(row.trades_1m)}
                  </td>
                  <td className="tnum py-0.5 pr-2 text-right font-mono text-[9px] text-ink-3">
                    {formatMoney(row.dollar_vol_1m)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ScannerFilters({
  onConfigure,
  disabled,
}: {
  onConfigure: (config: ScannerOverrides) => void;
  disabled: boolean;
}) {
  const config = useTerminalStore((state) => state.scannerConfig);
  const scanCodes = useTerminalStore((state) => state.scanCodes);
  const [draft, setDraft] = useState({
    scan_code: 'TOP_TRADE_RATE',
    above_price: '',
    below_price: '50',
    above_volume: '',
    change_perc_above: '',
    market_cap_above: '',
    market_cap_below: '',
  });
  const [hydrated, setHydrated] = useState(false);

  // Adopt the server's filters once. Re-syncing on every broadcast would wipe
  // edits in progress whenever an unrelated scanner refresh arrived.
  useEffect(() => {
    if (!config || hydrated) return;
    setHydrated(true);
    setDraft({
      scan_code: config.scan_code,
      above_price: config.above_price?.toString() ?? '',
      below_price: config.below_price?.toString() ?? '',
      above_volume: config.above_volume != null ? String(config.above_volume / 1e3) : '',
      change_perc_above: config.change_perc_above?.toString() ?? '',
      market_cap_above: config.market_cap_above != null ? String(config.market_cap_above / 1e6) : '',
      market_cap_below: config.market_cap_below != null ? String(config.market_cap_below / 1e6) : '',
    });
  }, [config, hydrated]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const num = (raw: string, scale = 1) => {
      const value = Number(raw.trim());
      return raw.trim() && Number.isFinite(value) ? value * scale : undefined;
    };
    onConfigure({
      scan_code: draft.scan_code,
      above_price: num(draft.above_price),
      below_price: num(draft.below_price),
      above_volume: num(draft.above_volume, 1e3),
      change_perc_above: num(draft.change_perc_above) ?? 'clear',
      market_cap_above: num(draft.market_cap_above, 1e6) ?? 'clear',
      market_cap_below: num(draft.market_cap_below, 1e6) ?? 'clear',
    });
  }

  const field = (key: keyof typeof draft, label: string, title?: string) => (
    <label className="flex min-w-0 flex-col gap-0.5" title={title}>
      <span className="text-[8px] font-bold uppercase tracking-wide text-ink-3">{label}</span>
      <input
        className={INPUT}
        inputMode="decimal"
        value={draft[key]}
        disabled={disabled}
        data-testid={`scanner-${key}`}
        onChange={(event) => setDraft((d) => ({ ...d, [key]: event.target.value }))}
      />
    </label>
  );

  return (
    <form onSubmit={submit} className="flex shrink-0 flex-col gap-1 px-2 pb-1.5" data-testid="scanner-filters">
      <label className="flex flex-col gap-0.5">
        <span className="sr-only">Scan</span>
        <select
          id="scan-code"
          className={INPUT}
          value={draft.scan_code}
          disabled={disabled}
          onChange={(event) => setDraft((d) => ({ ...d, scan_code: event.target.value }))}
        >
          {scanCodes.length === 0 && <option value={draft.scan_code}>Top % Gainers</option>}
          {scanCodes.map((code) => (
            <option key={code.code} value={code.code}>
              {code.label}
            </option>
          ))}
        </select>
      </label>
      <div className="grid grid-cols-3 gap-1">
        {field('above_price', 'Min $')}
        {field('below_price', 'Max $')}
        {field('above_volume', 'Vol K')}
        {field('change_perc_above', 'Chg% ≥', 'Minimum percent change — blank for none')}
        {field('market_cap_above', 'MCap≥ M', 'Minimum market cap, $ millions — blank for none')}
        {field('market_cap_below', 'MCap≤ M', 'Maximum market cap, $ millions — blank for none')}
      </div>
      <button
        type="submit"
        disabled={disabled}
        data-testid="scanner-apply"
        className="rounded-sm bg-accent-solid py-0.5 text-[10px] font-semibold text-white disabled:opacity-40"
      >
        Apply
      </button>
    </form>
  );
}

/**
 * How far a name has climbed the list in the last few seconds.
 *
 * The level says what is busiest; the movement says what is *becoming*
 * busy, and it turns first — a name is often several places into a climb
 * before it reaches anywhere worth noticing. Steady rows render nothing at
 * all, so the marks only appear where something is happening.
 */
function RankMove({ delta, entered }: { delta: number | null; entered: boolean }) {
  if (entered) {
    return (
      <span
        title="Not on the list a moment ago"
        className="ml-1 align-middle font-mono text-[8px] font-bold text-accent"
      >
        NEW
      </span>
    );
  }
  if (!delta) return null;

  const up = delta > 0;
  return (
    <span
      title={`${up ? 'Up' : 'Down'} ${Math.abs(delta)} place${Math.abs(delta) === 1 ? '' : 's'} on the trade-rate list`}
      className={`ml-1 align-middle font-mono text-[8px] font-bold tabular-nums ${
        up ? 'text-up' : 'text-down'
      }`}
    >
      {up ? '▲' : '▼'}
      {Math.abs(delta)}
    </span>
  );
}
