import {
  formatChange,
  formatCompact,
  formatInteger,
  formatMoney,
  formatPercent,
  formatPrice,
  formatRotation,
  formatSpread,
} from '@/lib/format';
import { buildInfoView, buildQuoteView, type SpreadTone } from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';

import { OhlcvReadout } from './OhlcvReadout';

const SPREAD_TONE_CLASS: Record<SpreadTone, string> = {
  tight: 'text-up',
  ok: 'text-ink',
  wide: 'text-down',
  untradeable: 'bg-down/20 text-down',
};

/**
 * The strip above the chart: everything about the symbol that is not a bar.
 *
 * Layout follows how a candidate row is read — price and spread first
 * (they disqualify fastest), then the supply side (float, rotation), then
 * the demand side (volume, relative volume), then the session context.
 */
export function TopPanel() {
  const symbol = useTerminalStore((state) => state.symbol);
  const live = useTerminalStore((state) => state.live);
  const quoteMessage = useTerminalStore((state) => state.quote);
  const infoMessage = useTerminalStore((state) => state.info);

  const lastPrice = live?.bar.c ?? null;
  const quote = buildQuoteView(quoteMessage);
  const info = buildInfoView(infoMessage, lastPrice);

  if (!symbol) return null;

  const change = info?.sessionChange ?? null;

  return (
    <section
      className="shrink-0 border-b border-line bg-panel px-2 py-1"
      data-testid="top-panel"
      aria-label="Symbol information"
    >
      <div className="tnum flex flex-wrap items-baseline gap-x-3 gap-y-0.5 font-mono">
        <span className="flex items-baseline gap-1.5">
          <span className="text-[15px] font-bold tracking-tight text-ink" data-testid="tp-symbol">
            {symbol}
          </span>
          {infoMessage?.description && (
            <span className="max-w-[180px] truncate text-[10px] text-ink-3" title={infoMessage.description}>
              {infoMessage.description}
            </span>
          )}
          {infoMessage?.exchange && (
            <span className="text-[9px] font-semibold uppercase text-ink-3">{infoMessage.exchange}</span>
          )}
        </span>

        <span
          className={`text-[15px] font-bold ${
            change ? (change.direction === 'down' ? 'text-down' : 'text-up') : 'text-ink'
          }`}
          data-testid="tp-last"
        >
          {formatPrice(lastPrice)}
        </span>

        {change && (
          <span
            className={`text-[12px] font-semibold ${change.direction === 'down' ? 'text-down' : 'text-up'}`}
            data-testid="tp-change"
            title="Change from the previous close"
          >
            {formatChange(change)}
          </span>
        )}

        <Field
          label="B"
          value={quote ? `${formatPrice(quote.bid)}×${formatCompact(quote.bidSize, 1)}` : '—'}
          testId="tp-bid"
          tone="text-up"
        />
        <Field
          label="A"
          value={quote ? `${formatPrice(quote.ask)}×${formatCompact(quote.askSize, 1)}` : '—'}
          testId="tp-ask"
          tone="text-down"
        />
        {quote && (
          <span
            className={`rounded-sm px-1 text-[11px] font-semibold ${SPREAD_TONE_CLASS[quote.tone]}`}
            data-testid="tp-spread"
            data-tone={quote.tone}
            title="Bid/ask spread — past 50¢ is untradeable"
          >
            {formatSpread(quote.spread)} · {formatPercent(quote.spreadPercent, 1)}
          </span>
        )}

        {info?.haltActive && info.haltUp != null && (
          <span
            className="text-[10px] text-ink-3"
            data-testid="tp-halt"
            title="Distance to the LULD halt bands (5-minute reference)"
          >
            HALT ↑{formatPrice(info.haltUpDistance)} ↓{formatPrice(info.haltDownDistance)}
          </span>
        )}
      </div>

      <div className="tnum flex flex-wrap items-baseline gap-x-3 gap-y-0.5 pt-0.5 font-mono">
        <Field label="VOL" value={formatCompact(info?.dayVolume)} testId="tp-dayvol" />
        <Field
          label="RVOL"
          value={info?.relVol != null ? formatRotation(info.relVol) : '—'}
          testId="tp-relvol"
          highlight={info?.relVol != null && info.relVol >= 5}
          title="Today's volume over the 10-day average — 5x is the line"
        />
        <Field
          label="FLOAT"
          value={formatCompact(info?.floatShares)}
          testId="tp-float"
          highlight={info?.floatShares != null && info.floatShares <= 20_000_000}
          title="Float under 20M is the screen; under 10M preferred"
        />
        <Field
          label="ROT"
          value={formatRotation(info?.floatRotation)}
          testId="tp-rotation"
          highlight={info?.floatRotation != null && info.floatRotation >= 1}
          title="Times the float has traded today — supply exhaustion read"
        />
        {info?.pmFloatRotation != null && info.pmVolume > 0 && (
          <Field
            label="PM ROT"
            value={formatPercent(info.pmFloatRotation * 100, 0)}
            testId="tp-pm-rotation"
            highlight={info.pmFloatRotation >= 0.1}
            title="Premarket volume as a share of the float — 10%+ flags a runner"
          />
        )}
        <Field label="MCAP" value={formatMoney(info?.marketCap)} testId="tp-mktcap" />
        <Field label="AVG10D" value={formatCompact(info?.avgVol10d)} testId="tp-avgvol" />
        <Field label="PREV" value={formatPrice(info?.prevClose)} testId="tp-prevclose" />
        {live?.bar.n != null && live.bar.n > 0 && (
          <Field label="T/BAR" value={formatInteger(live.bar.n)} testId="tp-trades" />
        )}

        <span className="ml-auto">
          <OhlcvReadout />
        </span>
      </div>
    </section>
  );
}

function Field({
  label,
  value,
  testId,
  tone,
  highlight,
  title,
}: {
  label: string;
  value: string;
  testId: string;
  tone?: string;
  highlight?: boolean;
  title?: string;
}) {
  return (
    <span className="text-[11px] text-ink-3" title={title}>
      {label}{' '}
      <span
        className={`font-semibold ${highlight ? 'text-accent-text' : (tone ?? 'text-ink')}`}
        data-testid={testId}
      >
        {value}
      </span>
    </span>
  );
}
