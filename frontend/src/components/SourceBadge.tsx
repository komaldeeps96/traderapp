import { useTerminalStore } from '@/store/useTerminalStore';

/**
 * Where the data is coming from, and whether it is delayed.
 *
 * Worth its own badge: the app silently fails over from IBKR to Alpaca, and a
 * trader has to know whether the price they are looking at is live or fifteen
 * minutes old.
 */
export function SourceBadge() {
  const connected = useTerminalStore((state) => state.connected);
  const source = useTerminalStore((state) => state.source);
  const delayed = useTerminalStore((state) => state.delayed);
  const note = useTerminalStore((state) => state.sourceNote);

  const label = !connected ? 'Disconnected' : source === 'none' ? 'No data source' : source.toUpperCase();
  const tone = !connected || source === 'none' ? 'bg-down' : delayed ? 'bg-ink-3' : 'bg-up';

  return (
    <div
      className="flex items-center gap-1.5"
      data-testid="source-badge"
      data-source={source}
      data-connected={connected ? 'true' : 'false'}
      data-delayed={delayed ? 'true' : 'false'}
      title={note ?? undefined}
    >
      <span className={`h-2 w-2 shrink-0 rounded-full ${tone}`} aria-hidden />
      <span className="text-[11px] font-semibold text-ink-2">{label}</span>
      {delayed && (
        <span
          className="rounded bg-elevated px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-ink-3"
          data-testid="delayed-badge"
        >
          15-min delayed
        </span>
      )}
      {/* Announced to screen readers as the connection changes. */}
      <span className="sr-only" role="status" aria-live="polite">
        {connected ? `Connected via ${source}` : 'Disconnected'}
        {delayed ? ', data is delayed by 15 minutes' : ''}
      </span>
    </div>
  );
}
