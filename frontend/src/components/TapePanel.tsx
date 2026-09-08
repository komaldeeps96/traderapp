import { useMemo, useRef, type ReactNode } from 'react';

import { TAPE_FLEX } from '@/chart/mini';
import {
  SIDE_LABELS,
  TAPE_BLOCK_SIZES,
  TAPE_MIN_SIZES,
  balance,
  isIrregular,
  sideClass,
  visiblePrints,
  type TapeFilters,
  type TapeRow,
} from '@/lib/tape';
import { formatCompact, formatInteger, formatPrice, priceDecimals } from '@/lib/format';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { TapePrint } from '@/types/protocol';

/**
 * Time and sales — the print-by-print tape, under the context chart.
 *
 * Every row is one trade that actually happened, tinted by which side of the
 * book took it. Two greens and two reds, exactly as a direct-access platform
 * draws them, because that colour is the whole message: a column of green
 * with rising prices is buyers lifting offers, and the same column in red is
 * a stock being sold into. On a small-cap runner the tape turns before the
 * candle does, which is why this took the second context chart's place.
 *
 * The rules — what the colours mean, what the filters do and in what order —
 * live in `lib/tape.ts` and are unit-tested there. This file is the rendering
 * and the controls.
 *
 * Two rendering decisions worth knowing.
 *
 * The list is capped at `TAPE_RENDERED` rows rather than virtualised. Past a
 * couple of hundred nobody is reading, and React reconciling a keyed list
 * that size once a second is cheaper than a windowing library.
 *
 * Freezing stops the *reading*, not the filling. The store keeps taking
 * prints behind a paused window, so unpausing lands on the live tape rather
 * than replaying a backlog — and the filters still apply while frozen, so a
 * size floor can be dialled in against a burst that has already gone past.
 */
export function TapePanel() {
  const prints = useTerminalStore((state) => state.tape);
  const filters = useTerminalStore((state) => state.tapeFilters);
  const setFilters = useTerminalStore((state) => state.setTapeFilters);
  const symbol = useTerminalStore((state) => state.symbol);

  // The freeze, and the only mutable thing here: a paused window keeps
  // rendering the prints it was frozen on. A ref rather than state because
  // the freeze is the *absence* of a render, so nothing should schedule one.
  //
  // A symbol switch breaks the freeze open. Prints are facts about one
  // instrument and read as live either way, so a frozen window left under a
  // new ticker would be showing the last company's tape — the one thing the
  // store's own clearing exists to prevent. The freeze itself survives; only
  // what it is holding is replaced.
  //
  // Which is why this tracks *what the freeze is holding* rather than what
  // symbol was last seen. The switch clears the store's tape a beat before
  // the new company's buffer arrives, so there is a render in between where
  // the tape is legitimately empty — and a freeze that re-armed on that
  // render would latch the empty list and hold it for as long as the window
  // stayed paused. Null means the freeze has nothing real yet: the window is
  // live, or the new symbol has not printed. Either way the next render is
  // free to take a fresh snapshot.
  const held = useRef<readonly TapePrint[]>(prints);
  const frozenOn = useRef<string | null>(null);
  if (!filters.paused || frozenOn.current !== symbol) {
    held.current = prints;
    frozenOn.current = filters.paused && prints.length > 0 ? symbol : null;
  }
  const source = held.current;

  const rows = useMemo(() => visiblePrints(source, filters), [source, filters]);
  const lean = useMemo(() => balance(rows), [rows]);
  // Decimals follow the price, so a $0.42 runner reads to four places and a
  // $40 one to two — the same rule the rest of the terminal uses.
  const decimals = priceDecimals(rows[0]?.p ?? 1);

  return (
    <section
      className="flex min-h-0 flex-col border-t border-line"
      // The larger share of the tab: a chart survives being short, a tape is
      // read for how many rows are on screen. See TAPE_FLEX.
      style={{ flexGrow: TAPE_FLEX, flexShrink: 1, flexBasis: 0 }}
      aria-label={`${symbol} time and sales`}
      data-testid="tape"
    >
      <TapeControls filters={filters} onChange={setFilters} />

      <div className="grid shrink-0 grid-cols-[52px_1fr_1fr_30px] gap-1 border-b border-line px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-ink-3">
        <span>Time</span>
        <span className="text-right">Price</span>
        <span className="text-right">Size</span>
        <span className="text-right">Ex</span>
      </div>

      {/* `aria-live` off, deliberately: a screen reader announcing every print
          on a runner would be unusable, and the tape is a scanned surface
          rather than a notification. */}
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto" data-testid="tape-rows" aria-live="off">
        {rows.length === 0 ? (
          <p className="px-1.5 py-2 text-[10px] text-ink-3" data-testid="tape-empty">
            {source.length > 0
              ? 'No prints match these filters.'
              : 'Waiting for prints…'}
          </p>
        ) : (
          rows.map((row) => (
            <Row key={row.q} row={row} decimals={decimals} blockSize={filters.blockSize} />
          ))
        )}
      </div>

      <TapeFooter buy={lean.buy} sell={lean.sell} buyShare={lean.buyShare} rows={rows.length} />
    </section>
  );
}

/**
 * One print.
 *
 * The tint carries the side and the text stays at full contrast on top of it.
 * These are 10px numbers: colouring them as well as the row would cost
 * legibility to repeat something the row has already said.
 */
function Row({
  row,
  decimals,
  blockSize,
}: {
  row: TapeRow;
  decimals: number;
  blockSize: number;
}) {
  const block = row.s >= blockSize;
  const irregular = isIrregular(row);
  return (
    <div
      data-testid={`tape-row-${row.q}`}
      data-side={row.a}
      data-block={block ? 'true' : undefined}
      title={
        `${stamp(row.t)} · ${SIDE_LABELS[row.a]}` +
        (row.n > 1 ? ` · ${row.n} prints` : '') +
        (irregular ? ' · not price-forming' : '') +
        (row.c?.length ? ` · conditions ${row.c.join('')}` : '') +
        (row.x ? ` · ${row.x}` : '')
      }
      className={`tnum grid grid-cols-[52px_1fr_1fr_30px] gap-1 px-1.5 font-mono text-[10px] leading-[15px] text-ink ${sideClass(
        row.a,
      )} ${block ? 'font-bold' : ''}`}
    >
      <span className="text-ink-2">{clock(row.t)}</span>
      <span className="text-right">{formatPrice(row.p, decimals)}</span>
      <span className="text-right">
        {/* An aggregated row says how many prints it swallowed: five thousand
            shares in one order and five thousand in fifty are not the same
            event, and the tape is read for exactly that difference. */}
        {row.n > 1 && <span className="mr-1 text-[9px] font-normal text-ink-3">×{row.n}</span>}
        {formatInteger(row.s)}
      </span>
      <span className="truncate text-right text-[9px] text-ink-3">
        {/* A dot beats the venue for an irregular print: a late report or an
            average-price block at a stale price is the one row on this window
            that must not be read as the market. */}
        {irregular ? '•' : (row.x ?? '')}
      </span>
    </div>
  );
}

/** The standard filter row: a size floor, a block threshold, three switches. */
function TapeControls({
  filters,
  onChange,
}: {
  filters: TapeFilters;
  onChange: (patch: Partial<TapeFilters>) => void;
}) {
  return (
    <header className="flex h-[22px] shrink-0 items-center gap-1 px-1.5 text-[10px]">
      <span className="font-bold uppercase tracking-wider text-ink-2">T&amp;S</span>

      <select
        value={filters.minSize}
        onChange={(event) => onChange({ minSize: Number(event.target.value) })}
        aria-label="Minimum print size"
        title="Hide prints smaller than this. With aggregation on it measures the whole group."
        data-testid="tape-min-size"
        className="rounded-sm border border-transparent bg-transparent text-[10px] text-ink-2 outline-none hover:border-line focus:border-accent"
      >
        {TAPE_MIN_SIZES.map((size) => (
          <option key={size} value={size}>
            {size === 0 ? 'All sizes' : `≥ ${shortSize(size)}`}
          </option>
        ))}
      </select>

      <select
        value={filters.blockSize}
        onChange={(event) => onChange({ blockSize: Number(event.target.value) })}
        aria-label="Block size"
        title="Prints this size and up are shown in bold. Nothing is hidden."
        data-testid="tape-block-size"
        className="rounded-sm border border-transparent bg-transparent text-[10px] text-ink-2 outline-none hover:border-line focus:border-accent"
      >
        {TAPE_BLOCK_SIZES.map((size) => (
          <option key={size} value={size}>
            {`Block ${shortSize(size)}`}
          </option>
        ))}
      </select>

      <div className="ml-auto flex shrink-0 items-center gap-0.5">
        <Toggle
          on={filters.aggregate}
          onClick={() => onChange({ aggregate: !filters.aggregate })}
          label="Aggregate prints at the same price"
          testId="tape-aggregate"
        >
          AGG
        </Toggle>
        <Toggle
          on={filters.regularOnly}
          onClick={() => onChange({ regularOnly: !filters.regularOnly })}
          label="Hide late and average-price prints"
          testId="tape-regular-only"
        >
          REG
        </Toggle>
        <Toggle
          on={filters.paused}
          onClick={() => onChange({ paused: !filters.paused })}
          label={filters.paused ? 'Resume the tape' : 'Freeze the tape'}
          testId="tape-pause"
        >
          {filters.paused ? '▶' : '❚❚'}
        </Toggle>
      </div>
    </header>
  );
}

function Toggle({
  on,
  onClick,
  label,
  testId,
  children,
}: {
  on: boolean;
  onClick: () => void;
  label: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={on}
      title={label}
      data-testid={testId}
      className={`rounded-sm border px-1 text-[9px] font-bold leading-[14px] outline-none transition-colors ${
        on
          ? 'border-accent bg-accent/20 text-ink'
          : 'border-line text-ink-3 hover:border-line-strong hover:text-ink-2'
      }`}
    >
      {children}
    </button>
  );
}

/**
 * Which way the visible tape leans.
 *
 * The colours say it row by row; this says it for the whole window at once,
 * which is the read actually taken off a fast tape. Computed over exactly
 * what is on screen, filters included, so the bar and the rows above it can
 * never disagree.
 */
function TapeFooter({
  buy,
  sell,
  buyShare,
  rows,
}: {
  buy: number;
  sell: number;
  buyShare: number | null;
  rows: number;
}) {
  const percent = buyShare === null ? null : Math.round(buyShare * 100);
  return (
    <footer
      className="tnum flex h-[18px] shrink-0 items-center gap-1.5 border-t border-line px-1.5 font-mono text-[9px] text-ink-3"
      data-testid="tape-balance"
      data-buy-share={percent ?? ''}
      title="Shares taken at or through the offer against shares taken at or through the bid, over the rows on screen."
    >
      <span className="text-up">▲ {formatCompact(buy, 1)}</span>
      <span className="text-down">▼ {formatCompact(sell, 1)}</span>
      {percent === null ? (
        <span className="ml-auto">{rows} rows</span>
      ) : (
        <>
          <span className="h-[5px] flex-1 overflow-hidden rounded-full bg-down">
            <span className="block h-full bg-up" style={{ width: `${percent}%` }} />
          </span>
          <span>{percent}% buy</span>
        </>
      )}
    </footer>
  );
}

/** 100, 2.5K, 10K — share counts at the width a filter label has. */
function shortSize(shares: number): string {
  if (shares < 1_000) return String(shares);
  const thousands = shares / 1_000;
  return `${Number.isInteger(thousands) ? thousands : thousands.toFixed(1)}K`;
}

/** HH:MM:SS in the exchange's timezone — the column, at 10px. */
function clock(epochMs: number): string {
  return TIME_FORMAT.format(new Date(epochMs));
}

/**
 * The same instant to the millisecond, for the row's tooltip.
 *
 * The column cannot afford four more characters, and inside a burst the
 * ordering is the whole question — a dozen rows share a second, and which
 * came first is what says whether one order swept five venues.
 */
function stamp(epochMs: number): string {
  return `${clock(epochMs)}.${String(Math.floor(epochMs) % 1000).padStart(3, '0')}`;
}

const TIME_FORMAT = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});
