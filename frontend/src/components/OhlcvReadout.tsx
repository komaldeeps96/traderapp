import { formatBarTime, formatChange, formatCompact, formatMoney, formatPercent, formatPrice, formatRotation } from '@/lib/format';
import { sessionAt } from '@/lib/session';
import { buildOhlcv } from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';

/**
 * The OHLCV line.
 *
 * Shows the hovered bar when the crosshair is on the chart and the live bar
 * otherwise, which is what makes the crosshair useful for reading history.
 * The two percentages are labelled because they answer different questions:
 * BAR is what this one candle did, DAY is where the day stood at that candle.
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
      <Field label="O" value={formatPrice(bar.o)} testId="ohlcv-open" title="Open" />
      <Field label="H" value={formatPrice(bar.h)} testId="ohlcv-high" title="High" />
      <Field label="L" value={formatPrice(bar.l)} testId="ohlcv-low" title="Low" />
      <Field label="C" value={formatPrice(bar.c)} testId="ohlcv-close" title="Close" />

      {barChange && (
        <span
          className={barChange.direction === 'down' ? 'text-down' : 'text-up'}
          data-testid="ohlcv-change"
          title="This one candle: close against the previous bar's close"
        >
          BAR {formatPercent(barChange.percent)}
        </span>
      )}

      {sessionChange && (
        <span
          className={sessionChange.direction === 'down' ? 'text-down' : 'text-up'}
          data-testid="ohlcv-session-change"
          title="The day at this bar: close against the previous session's close"
        >
          DAY {formatChange(sessionChange, bar.c)}
        </span>
      )}

      <Field label="V" value={formatCompact(bar.v)} testId="ohlcv-volume" title="Volume of this bar" />
      <Field label="T" value={formatCompact(bar.n)} testId="ohlcv-trades" title="Trades in this bar" />

      {extendedHours && (
        <span
          className="rounded bg-elevated px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-ink-3"
          data-testid="ohlcv-extended"
          title="Printed outside regular trading hours"
        >
          Ext hours
        </span>
      )}
    </div>
  );
}

/**
 * The session as it stood at the hovered bar — or right now, off the chart.
 *
 * Cumulative figures with hindsight removed: hover a breakout candle and read
 * whether the day's pace and float turnover already justified it *at that
 * moment*, not at the close. Values are derived from the chart's own bars, so
 * they exist for any bar the chart holds.
 */
export function BarSessionStrip() {
  const hovered = useTerminalStore((state) => state.hovered);
  const live = useTerminalStore((state) => state.live);
  const info = useTerminalStore((state) => state.info);
  const timeframe = useTerminalStore((state) => state.timeframe);
  const view = buildOhlcv(hovered ?? live, info);

  if (!view) return null;

  const session = sessionAt(view.bar.t);

  return (
    <div
      className="tnum flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[11px]"
      data-testid="bar-strip"
      data-hovering={hovered ? 'true' : 'false'}
    >
      <span
        className="text-ink-3"
        data-testid="bs-clock"
        title="The bar under the crosshair — its time and trading session"
      >
        ⏱ <span className="font-semibold text-ink-2">{formatBarTime(view.bar.t, timeframe)}</span>
        {session !== 'CLOSED' && <span className="pl-1 text-[9px] font-bold">{session}</span>}
      </span>

      {view.sessionVolume != null && (
        <Field
          label="ΣVOL"
          value={formatCompact(view.sessionVolume)}
          testId="bs-cumvol"
          title="Cumulative session volume through this bar"
        />
      )}
      {view.rvolAtBar != null && (
        <Field
          label="RVOL"
          value={formatRotation(view.rvolAtBar)}
          testId="bs-rvol"
          title="The day's pace at this bar — session volume so far over the 10-day average"
        />
      )}
      {view.windowRvol != null && (
        <Field
          label="WRVOL"
          value={formatRotation(view.windowRvol)}
          testId="bs-wrvol"
          title="Time-matched relative volume — this 4am→bar window against the same window on the prior days the chart holds"
        />
      )}
      {view.rotationAtBar != null && (
        <Field
          label="ROT"
          value={formatRotation(view.rotationAtBar)}
          testId="bs-rotation"
          title="Float turns at this bar — session volume so far over the float"
        />
      )}
      {view.marketCapAtBar != null && (
        <Field
          label="MCAP"
          value={formatMoney(view.marketCapAtBar)}
          testId="bs-mcap"
          title="Market cap at this bar — shares outstanding × its close; the static snapshot sits in the row below"
        />
      )}
      {view.vwapDeltaPercent != null && (
        <span
          className={view.vwapDeltaPercent >= 0 ? 'text-up' : 'text-down'}
          data-testid="bs-vwap"
          title="Distance from VWAP at this bar — the polarity read, at that moment"
        >
          VWAP {formatPercent(view.vwapDeltaPercent, 1)}
        </span>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  testId,
  title,
}: {
  label: string;
  value: string;
  testId: string;
  title?: string;
}) {
  return (
    <span className="text-ink-3" title={title}>
      {label} <span className="font-semibold text-ink" data-testid={testId}>{value}</span>
    </span>
  );
}
