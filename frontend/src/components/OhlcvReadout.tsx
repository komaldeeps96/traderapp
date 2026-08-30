import { formatBarTime, formatChange, formatCompact, formatPercent, formatPrice } from '@/lib/format';
import { sessionAt } from '@/lib/session';
import { buildOhlcv } from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';

import { Divider, Field } from './PanelField';

/**
 * The bar row: the hovered candle, or the live one with the crosshair off.
 *
 * The bar's own clock leads the row, which is where it belongs — it labels
 * the numbers beside it. It used to sit at the right-hand end of the row
 * above, close enough to the wall clock in the toolbar to read as a broken
 * copy of it: a 10-second bar opens up to ten seconds before the time it is
 * read at, so the two were never going to agree. Here it is labelled BAR,
 * carries no date while the bar is from the session on screen, and the
 * numbers it stamps are next to it.
 *
 * DAY appears only under the crosshair. Live it is the same figure as the
 * change beside the price two rows up.
 */
export function OhlcvReadout() {
  const hovered = useTerminalStore((state) => state.hovered);
  const live = useTerminalStore((state) => state.live);
  const timeframe = useTerminalStore((state) => state.timeframe);
  const view = buildOhlcv(hovered ?? live);
  const hovering = hovered != null;

  if (!view) {
    return (
      <div className="pt-0.5 text-[11px] text-ink-3" data-testid="ohlcv">
        No data
      </div>
    );
  }

  const { bar, barChange, sessionChange, extendedHours } = view;
  const session = sessionAt(bar.t);

  return (
    <div
      className="tnum flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 pt-0.5 font-mono text-[11px]"
      data-testid="ohlcv"
      data-hovering={hovering ? 'true' : 'false'}
    >
      <span
        className="whitespace-nowrap text-ink-3"
        title="When this bar opened, New York time. A live bar opens up to one interval before the clock in the toolbar reads."
      >
        BAR{' '}
        <span className="font-semibold text-ink-2" data-testid="ohlcv-time">
          {formatBarTime(bar.t, timeframe)}
        </span>
        {hovering && session !== 'CLOSED' && (
          <span className="pl-1 text-[9px] font-bold text-ink-3">{session}</span>
        )}
      </span>

      <Divider />

      <Field label="O" value={formatPrice(bar.o)} testId="ohlcv-open" title="Open" />
      <Field label="H" value={formatPrice(bar.h)} testId="ohlcv-high" title="High" />
      <Field label="L" value={formatPrice(bar.l)} testId="ohlcv-low" title="Low" />
      <Field label="C" value={formatPrice(bar.c)} testId="ohlcv-close" title="Close" />

      {barChange && (
        <span
          className={`whitespace-nowrap ${barChange.direction === 'down' ? 'text-down' : 'text-up'}`}
          data-testid="ohlcv-change"
          title="This one candle: close against the previous bar's close"
        >
          Δ {formatPercent(barChange.percent)}
        </span>
      )}

      <Divider />

      <Field label="V" value={formatCompact(bar.v)} testId="ohlcv-volume" title="Volume of this bar" />
      <Field label="T" value={formatCompact(bar.n)} testId="ohlcv-trades" title="Trades in this bar" />

      {hovering && sessionChange && (
        <span
          className={`whitespace-nowrap ${sessionChange.direction === 'down' ? 'text-down' : 'text-up'}`}
          data-testid="ohlcv-session-change"
          title="The day at this bar: close against the previous session's close"
        >
          DAY {formatChange(sessionChange, bar.c)}
        </span>
      )}

      {extendedHours && (
        <span
          className="rounded bg-elevated px-1.5 text-[9px] font-semibold uppercase tracking-wide text-ink-3"
          data-testid="ohlcv-extended"
          title="Printed outside regular trading hours"
        >
          Ext hours
        </span>
      )}
    </div>
  );
}
