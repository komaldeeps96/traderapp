import { useState, type FormEvent } from 'react';

import { formatCompact, formatMoney, formatPercent, formatPrice } from '@/lib/format';
import { parseFilter } from '@/lib/scannerFilters';
import { useTerminalStore } from '@/store/useTerminalStore';
import { SCANNER_TIER_IDS } from '@/types/protocol';
import type { ClientCommand, ScannerConfig, ScannerTierId } from '@/types/protocol';

type ScannerOverrides = Omit<
  Extract<ClientCommand, { action: 'scanner.configure' }>,
  'action' | 'scanner_id'
>;

interface ScannerPanelProps {
  scannerId: ScannerTierId;
  onSelect: (symbol: string) => void;
  onConfigure: (config: ScannerOverrides) => void;
}

const INPUT =
  'w-full rounded-sm border border-line bg-elevated px-1 py-0.5 text-[10px] text-ink outline-none focus:border-accent';

/**
 * Prints per minute above which a row flashes green.
 *
 * A thousand a minute is about seventeen a second, well clear of the couple of
 * hundred a busy-but-ordinary runner prints. The list is already ordered by
 * this, so the highlight marks crossing from busy into urgent rather than
 * saying where to look. Styling is `.scanner-row-hot` in index.css.
 */
export const HOT_TRADE_RATE = 1000;

/**
 * One IBKR trade-rate scanner, filtered to a single market-cap tier.
 *
 * Trades-per-minute and dollar volume over sliding windows, straight from live
 * prints. IBKR-only with no fallback, so an absent TWS is said plainly. Four
 * run side by side, each with its own filters and persisted state; see App.tsx.
 */
export function ScannerPanel({ scannerId, onSelect, onConfigure }: ScannerPanelProps) {
  const tier = useTerminalStore((state) => state.scanners[scannerId]);
  const { label, rows, config } = tier;
  // Availability tracks the LIVE connection state from status frames, not
  // the REST snapshot taken at page load — a page opened during a backend
  // restart would otherwise cache "unavailable" and disable the filters
  // forever, long after TWS reconnected.
  const available = useTerminalStore((state) => state.ibkrConnected);
  const note = useTerminalStore((state) => state.scannerNote);
  const activeSymbol = useTerminalStore((state) => state.symbol);
  const [showFilters, setShowFilters] = useState(false);

  return (
    // `shrink-0` is what makes a tier's depth mean anything. As a shrinkable
    // flex child every panel got squeezed to roughly the same height whatever
    // it was asked to show, so the deeper small-cap panel simply grew its own
    // scrollbar and still showed five and a half names. Sized to its content
    // instead, the column above it does the scrolling — see App.tsx.
    <section
      className="flex min-h-0 shrink-0 flex-col border-b border-line"
      data-testid={`scanner-${scannerId}`}
    >
      <div className="flex shrink-0 items-center gap-2 px-2 pb-1 pt-1.5">
        <h2 className="text-[10px] font-bold uppercase tracking-wider text-ink-3">{label}</h2>
        <button
          type="button"
          onClick={() => setShowFilters((v) => !v)}
          aria-expanded={showFilters}
          data-testid={`scanner-${scannerId}-filter-toggle`}
          className="ml-auto rounded-sm border border-line px-1 text-[9px] font-bold uppercase text-ink-3 hover:text-ink"
        >
          {showFilters ? 'Hide' : 'Filters'}
        </button>
        <span
          className="tnum text-[9px] font-semibold text-ink-3"
          data-testid={`scanner-${scannerId}-count`}
        >
          {rows.length} rows
        </span>
      </div>

      {showFilters && (
        <ScannerFilters
          scannerId={scannerId}
          config={config}
          onConfigure={onConfigure}
          disabled={!available}
        />
      )}

      {!available ? (
        // One note for the whole Day tab: every tier shares the one cause.
        scannerId === SCANNER_TIER_IDS[0] && (
          <p
            className="px-2 py-2 text-[10px] leading-snug text-ink-3"
            data-testid={`scanner-${scannerId}-note`}
          >
            {note ?? 'Market scanner is unavailable.'}
          </p>
        )
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
              {rows.map((row) => {
                const hot = row.trades_1m > HOT_TRADE_RATE;
                const active = row.symbol === activeSymbol;
                return (
                  <tr
                    key={row.symbol}
                    data-testid={`scanner-${scannerId}-row-${row.symbol}`}
                    data-hot={hot ? 'true' : undefined}
                    className={`cursor-pointer border-t border-line/60 hover:bg-elevated ${
                      hot ? 'scanner-row-hot' : active ? 'bg-accent/10' : ''
                    }`}
                    onClick={() => onSelect(row.symbol)}
                  >
                    {/* The bar, not a tint, is what marks the loaded symbol: a
                        row can be both loaded and flashing, and the green wins
                        the background. Transparent when it is neither, so the
                        column never shifts by the two pixels. */}
                    <th
                      scope="row"
                      className={`border-l-2 py-0.5 pl-1.5 text-left text-[10px] font-bold text-ink ${
                        active ? 'border-l-accent' : 'border-l-transparent'
                      }`}
                    >
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
                    {/* Emphasised on a flashing row so the reason for the
                        flash is in the row, not just in the trader's head. */}
                    <td
                      className={`tnum py-0.5 pr-1 text-right font-mono text-[10px] ${
                        hot ? 'font-bold text-up' : 'text-ink-2'
                      }`}
                    >
                      {formatCompact(row.trades_1m)}
                    </td>
                    <td className="tnum py-0.5 pr-2 text-right font-mono text-[10px] text-ink-2">
                      {formatMoney(row.dollar_vol_1m)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

interface FilterDraft {
  scan_code: string;
  above_price: string;
  below_price: string;
  above_trade_rate: string;
  change_perc_above: string;
  market_cap_above: string;
  market_cap_below: string;
}

const DEFAULT_DRAFT: FilterDraft = {
  scan_code: 'TOP_TRADE_RATE',
  above_price: '',
  below_price: '50',
  above_trade_rate: '200',
  change_perc_above: '',
  market_cap_above: '',
  market_cap_below: '',
};

/** The form's text for a config. Market caps are typed in millions. */
function draftFrom(config: ScannerConfig): FilterDraft {
  return {
    scan_code: config.scan_code,
    above_price: config.above_price?.toString() ?? '',
    below_price: config.below_price?.toString() ?? '',
    above_trade_rate: config.above_trade_rate?.toString() ?? '',
    change_perc_above: config.change_perc_above?.toString() ?? '',
    market_cap_above: config.market_cap_above != null ? String(config.market_cap_above / 1e6) : '',
    market_cap_below: config.market_cap_below != null ? String(config.market_cap_below / 1e6) : '',
  };
}

function ScannerFilters({
  scannerId,
  config,
  onConfigure,
  disabled,
}: {
  scannerId: ScannerTierId;
  config: ScannerConfig | null;
  onConfigure: (config: ScannerOverrides) => void;
  disabled: boolean;
}) {
  const scanCodes = useTerminalStore((state) => state.scanCodes);
  const [edited, setEdited] = useState<FilterDraft | null>(null);
  const [invalid, setInvalid] = useState<ReadonlySet<string>>(new Set());

  // The server's filters until the first keystroke, the user's own after it:
  // following every broadcast past that would wipe edits in progress.
  const base = config ? draftFrom(config) : DEFAULT_DRAFT;
  const draft = edited ?? base;
  const edit = (change: Partial<FilterDraft>) =>
    setEdited((current) => ({ ...(current ?? base), ...change }));

  function submit(event: FormEvent) {
    event.preventDefault();
    const parsed = {
      above_price: parseFilter(draft.above_price),
      below_price: parseFilter(draft.below_price),
      above_trade_rate: parseFilter(draft.above_trade_rate, { integer: true }),
      change_perc_above: parseFilter(draft.change_perc_above),
      market_cap_above: parseFilter(draft.market_cap_above, { scale: 1e6 }),
      market_cap_below: parseFilter(draft.market_cap_below, { scale: 1e6 }),
    };
    const rejected = Object.entries(parsed)
      .filter(([, result]) => 'invalid' in result)
      .map(([key]) => key);
    setInvalid(new Set(rejected));
    if (rejected.length > 0) return;

    const value = (key: keyof typeof parsed) => {
      const result = parsed[key];
      return 'value' in result ? result.value : 'clear';
    };
    onConfigure({
      scan_code: draft.scan_code,
      above_price: value('above_price'),
      below_price: value('below_price'),
      above_trade_rate: value('above_trade_rate'),
      change_perc_above: value('change_perc_above'),
      market_cap_above: value('market_cap_above'),
      market_cap_below: value('market_cap_below'),
    });
  }

  const field = (key: keyof typeof draft, label: string, title?: string) => (
    <label className="flex min-w-0 flex-col gap-0.5" title={title}>
      <span className="text-[8px] font-bold uppercase tracking-wide text-ink-3">{label}</span>
      <input
        className={`${INPUT} ${invalid.has(key) ? 'border-down' : ''}`}
        inputMode="decimal"
        value={draft[key]}
        disabled={disabled}
        aria-invalid={invalid.has(key)}
        data-testid={`scanner-${scannerId}-${key}`}
        onChange={(event) => {
          edit({ [key]: event.target.value });
          setInvalid((current) => {
            if (!current.has(key)) return current;
            const next = new Set(current);
            next.delete(key);
            return next;
          });
        }}
      />
    </label>
  );

  return (
    <form
      onSubmit={submit}
      className="flex shrink-0 flex-col gap-1 px-2 pb-1.5"
      data-testid={`scanner-${scannerId}-filters`}
    >
      <label className="flex flex-col gap-0.5">
        <span className="sr-only">Scan</span>
        <select
          id={`scan-code-${scannerId}`}
          className={INPUT}
          value={draft.scan_code}
          disabled={disabled}
          onChange={(event) => edit({ scan_code: event.target.value })}
        >
          {/* Before the server's list arrives, the code itself: a friendly
              label guessed here would name a different scan. */}
          {scanCodes.length === 0 && <option value={draft.scan_code}>{draft.scan_code}</option>}
          {scanCodes.map((code) => (
            <option key={code.code} value={code.code}>
              {code.label}
            </option>
          ))}
        </select>
      </label>
      <div className="grid grid-cols-3 gap-1">
        {field('above_price', 'Min $', 'Minimum share price — blank for none')}
        {field('below_price', 'Max $', 'Maximum share price — blank for none')}
        {field(
          'above_trade_rate',
          'T/min ≥',
          'Minimum trades per minute — what the tape is doing now, rather than ' +
            'the volume it has already done today. Blank for none.',
        )}
        {field('change_perc_above', 'Chg% ≥', 'Minimum percent change — blank for none')}
        {field('market_cap_above', 'MCap≥ M', 'Minimum market cap, $ millions — blank for none')}
        {field('market_cap_below', 'MCap≤ M', 'Maximum market cap, $ millions — blank for none')}
      </div>
      <button
        type="submit"
        disabled={disabled}
        data-testid={`scanner-${scannerId}-apply`}
        className="rounded-sm bg-accent-solid py-0.5 text-[10px] font-semibold text-white disabled:opacity-40"
      >
        Apply
      </button>
    </form>
  );
}

/**
 * How far a name has climbed the list in the last few seconds. The level says
 * what is busiest, the movement what is *becoming* busy, and it turns first.
 * Steady rows render nothing.
 */
function RankMove({ delta, entered }: { delta: number | null; entered: boolean }) {
  if (entered) {
    return (
      <span
        title="Not on the list a moment ago"
        className="ml-1 align-middle font-mono text-[8px] font-bold text-accent-text"
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
