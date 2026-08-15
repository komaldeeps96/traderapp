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
      <TimeframeTabs value={timeframe} onChange={onTimeframe} />

      {/* Centred between the chart controls and the status cluster: the
          "can I switch tickers right now" read lives where the eye rests. */}
      <div className="mx-auto">
        <ApiMeters />
      </div>

      <div className="flex items-center gap-2.5">
        {status === 'loading' && (
          <span className="text-[11px] text-ink-3" data-testid="loading">
            Loading…
          </span>
        )}
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
