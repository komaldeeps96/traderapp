import { formatChange, formatCompact, formatPrice } from '@/lib/format';
import { buildOhlcv } from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';

/**
 * The OHLCV line.
 *
 * Shows the hovered bar when the crosshair is on the chart and the live bar
 * otherwise, which is what makes the crosshair useful for reading history.
 */
export function OhlcvReadout() {
  const hovered = useTerminalStore((state) => state.hovered);
  const live = useTerminalStore((state) => state.live);
  const view = buildOhlcv(hovered ?? live);

  if (!view) {
    return (
      <div className="text-[11px] text-ink-3" data-testid="ohlcv">
        No data
      </div>
    );
  }

  const { bar, barChange, sessionChange, extendedHours } = view;

  return (
    <div
      className="tnum flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[11px]"
      data-testid="ohlcv"
      data-hovering={hovered ? 'true' : 'false'}
    >
      <Field label="O" value={formatPrice(bar.o)} testId="ohlcv-open" />
      <Field label="H" value={formatPrice(bar.h)} testId="ohlcv-high" />
      <Field label="L" value={formatPrice(bar.l)} testId="ohlcv-low" />
      <Field label="C" value={formatPrice(bar.c)} testId="ohlcv-close" />

      {barChange && (
        <span
          className={barChange.direction === 'down' ? 'text-down' : 'text-up'}
          data-testid="ohlcv-change"
        >
          {formatChange(barChange)}
        </span>
      )}

      {sessionChange && (
        <span
          className={sessionChange.direction === 'down' ? 'text-down' : 'text-up'}
          data-testid="ohlcv-session-change"
          title="Change from the previous session's close"
        >
          D {formatChange(sessionChange)}
        </span>
      )}

      <Field label="V" value={formatCompact(bar.v)} testId="ohlcv-volume" />
      <Field label="T" value={formatCompact(bar.n)} testId="ohlcv-trades" />

      {extendedHours && (
        <span
          className="rounded bg-elevated px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-ink-3"
          data-testid="ohlcv-extended"
        >
          Ext hours
        </span>
      )}
    </div>
  );
}

function Field({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <span className="text-ink-3">
      {label} <span className="font-semibold text-ink" data-testid={testId}>{value}</span>
    </span>
  );
}
