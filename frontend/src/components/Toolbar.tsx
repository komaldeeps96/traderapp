import { useEffect, useState, type FormEvent } from 'react';

import { TIMEFRAMES, type Timeframe } from '@/types/protocol';
import { useTerminalStore } from '@/store/useTerminalStore';

import { ApiMeters } from './ApiMeters';
import { SessionClock } from './SessionClock';
import { SourceBadge } from './SourceBadge';

interface ToolbarProps {
  onSubscribe: (symbol: string, timeframe: Timeframe) => void;
  onTimeframe: (timeframe: Timeframe) => void;
  onToggleTheme: () => void;
}

export function Toolbar({ onSubscribe, onTimeframe, onToggleTheme }: ToolbarProps) {
  const symbol = useTerminalStore((state) => state.symbol);
  const timeframe = useTerminalStore((state) => state.timeframe);
  const status = useTerminalStore((state) => state.status);
  const theme = useTerminalStore((state) => state.theme);

  return (
    <header
      data-testid="toolbar"
      aria-label="Chart controls"
      className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line bg-panel px-2 py-1"
    >
      <SymbolInput symbol={symbol} timeframe={timeframe} onSubscribe={onSubscribe} />
      <WatchStar symbol={symbol} />
      <TimeframeTabs value={timeframe} onChange={onTimeframe} />

      {/* The slack in this row is where the instrument's name goes. It used
          to sit in the panel below, beside a second copy of the ticker that
          the input already shows; here it costs no height at all and the
          panel below is left to carry nothing but numbers. */}
      <Instrument />

      <div className="flex items-center gap-2.5">
        {status === 'loading' && (
          <span className="text-[11px] text-ink-3" data-testid="loading">
            Loading…
          </span>
        )}
        <ApiMeters />
        <Regime />
        <SessionClock />
        <SourceBadge />
        <button
          type="button"
          onClick={onToggleTheme}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          data-testid="theme-toggle"
          className="rounded-sm border border-line px-1.5 py-0.5 text-[10px] text-ink-2 hover:text-ink"
        >
          {theme === 'dark' ? 'Light' : 'Dark'}
        </button>
      </div>
    </header>
  );
}

/**
 * Who the ticker in the box actually is.
 *
 * Truncating rather than wrapping is deliberate: this is the one field on the
 * header whose length is set by a data provider rather than by a format
 * function, so it is the one field that must not be allowed to move anything
 * else. It takes the leftover width and gives it back the moment the status
 * cluster needs it.
 */
function Instrument() {
  const info = useTerminalStore((state) => state.info);
  if (!info?.description) return null;

  return (
    <div
      className="flex min-w-0 flex-1 items-baseline gap-1.5 overflow-hidden"
      data-testid="tb-instrument"
    >
      <span
        className="truncate text-[11px] text-ink-2"
        data-testid="tb-company"
        title={info.description}
      >
        {info.description}
      </span>
      {info.exchange && (
        <span
          className="shrink-0 text-[9px] font-semibold uppercase tracking-wide text-ink-3"
          title="Listing exchange"
        >
          {info.exchange}
        </span>
      )}
      {info.sector && (
        <span
          className="hidden shrink-0 truncate text-[9px] uppercase tracking-wide text-ink-3 2xl:inline"
          title="Sector"
        >
          {info.sector}
        </span>
      )}
    </div>
  );
}

/**
 * Put the chart's symbol on the watchlist, or take it off.
 *
 * The panel's own input is the deliberate way in; this is the other one, for
 * the far more common case — the name is already on screen because something
 * about it was interesting, and reaching for a text box to retype it is how a
 * watchlist ends up empty.
 */
function WatchStar({ symbol }: { symbol: string }) {
  const watched = useTerminalStore((state) => state.watchlist.includes(symbol));
  const add = useTerminalStore((state) => state.addToWatchlist);
  const remove = useTerminalStore((state) => state.removeFromWatchlist);
  if (!symbol) return null;

  return (
    <button
      type="button"
      onClick={() => (watched ? remove(symbol) : add(symbol))}
      aria-pressed={watched}
      aria-label={watched ? `Remove ${symbol} from the watchlist` : `Add ${symbol} to the watchlist`}
      title={watched ? 'On the watchlist' : 'Add to the watchlist'}
      data-testid="watch-star"
      className={`-ml-1 rounded-sm px-1 text-[13px] leading-none transition-colors ${
        watched ? 'text-accent-text' : 'text-ink-3 hover:text-ink-2'
      }`}
    >
      {watched ? '\u2605' : '\u2606'}
    </button>
  );
}

function SymbolInput({
  symbol,
  timeframe,
  onSubscribe,
}: {
  symbol: string;
  timeframe: Timeframe;
  onSubscribe: (symbol: string, timeframe: Timeframe) => void;
}) {
  const [draft, setDraft] = useState(symbol);

  // Follow the store when the symbol changes elsewhere — a scanner click, or a
  // session restored on load — without fighting the user mid-type.
  useEffect(() => {
    setDraft(symbol);
  }, [symbol]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = draft.trim().toUpperCase();
    if (value) onSubscribe(value, timeframe);
  }

  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <label htmlFor="symbol-input" className="sr-only">
        Ticker symbol
      </label>
      <input
        id="symbol-input"
        data-testid="symbol-input"
        value={draft}
        onChange={(event) => setDraft(event.target.value.toUpperCase())}
        // Select the whole ticker on focus so typing replaces it. The mouseup
        // handler stops the browser collapsing that selection to a caret when
        // the focus came from a click.
        onFocus={(event) => event.currentTarget.select()}
        onMouseUp={(event) => event.preventDefault()}
        placeholder="Symbol"
        autoComplete="off"
        spellCheck={false}
        maxLength={10}
        className="w-20 rounded-sm border border-line bg-elevated px-1.5 py-0.5 font-mono text-[12px] font-semibold uppercase text-ink outline-none focus:border-accent"
      />
      <button type="submit" className="sr-only">
        Load symbol
      </button>
    </form>
  );
}

function TimeframeTabs({
  value,
  onChange,
}: {
  value: Timeframe;
  onChange: (timeframe: Timeframe) => void;
}) {
  return (
    <div
      className="flex items-center gap-0.5 rounded-sm border border-line p-0.5"
      role="group"
      aria-label="Timeframe"
      data-testid="timeframe-tabs"
    >
      {TIMEFRAMES.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          aria-pressed={option === value}
          data-testid={`timeframe-${option}`}
          className={`rounded-sm px-1.5 py-0.5 text-[10px] font-semibold uppercase transition-colors ${
            option === value ? 'bg-accent-solid text-white' : 'text-ink-3 hover:text-ink'
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

/**
 * How many names are running today.
 *
 * The count of stocks up 50% and 100% is the market-regime read: setup
 * quality holds in a hot tape and degrades badly in a cold one, so the same
 * chart is worth trading on one day and not the next. It used to live on the
 * screener panel; that panel is gone but the number is not tied to it.
 */
function Regime() {
  const regime = useTerminalStore((state) => state.regime);
  if (!regime) return null;

  return (
    <span
      title="Stocks up 50% / 100% today — the market-regime read"
      data-testid="regime"
      className="tnum font-mono text-[10px] text-ink-3"
    >
      ↑50%:<span className="font-semibold text-ink-2">{regime.up_50_count}</span>
      {' '}↑100%:<span className="font-semibold text-ink-2">{regime.up_100_count}</span>
    </span>
  );
}
