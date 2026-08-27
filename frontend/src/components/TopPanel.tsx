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
import {
  buildInfoView,
  buildQuoteView,
  FLOAT_DISAGREE_PERCENT,
  RECENT_IPO_DAYS,
  RECENT_SPLIT_DAYS,
  type BorrowStatus,
  type PullbackTone,
  type SpreadTone,
} from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';

import { BarSessionStrip, OhlcvReadout } from './OhlcvReadout';

const SPREAD_TONE_CLASS: Record<SpreadTone, string> = {
  tight: 'text-up',
  ok: 'text-ink',
  wide: 'text-down',
  untradeable: 'bg-down/20 text-down',
};

const BORROW_CLASS: Record<BorrowStatus, string> = {
  easy: 'text-ink-3',
  locate: 'text-down',
  none: 'bg-down/20 text-down',
};

const BORROW_LABEL: Record<BorrowStatus, string> = {
  easy: 'ETB',
  locate: 'HTB',
  none: 'NO BORROW',
};

const PULLBACK_CLASS: Record<PullbackTone, string> = {
  healthy: 'text-up',
  ok: 'text-ink-2',
  failed: 'bg-down/20 text-down',
  stale: 'text-ink-3',
};

const PULLBACK_TITLE: Record<PullbackTone, string> = {
  healthy: 'Orderly: holding the top half of the leg on drying volume',
  ok: 'Pullback forming — depth, volume and freshness not all in range yet',
  failed: 'Retraced past 78.6% — the leg failed',
  stale: 'Ten minutes off the high — a downtrend, not a pullback',
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
          <span
            className="text-[15px] font-bold tracking-tight text-ink"
            data-testid="tp-symbol"
            title="Active symbol"
          >
            {symbol}
          </span>
          {infoMessage?.description && (
            <span className="max-w-[180px] truncate text-[10px] text-ink-3" title={infoMessage.description}>
              {infoMessage.description}
            </span>
          )}
          {infoMessage?.exchange && (
            <span className="text-[9px] font-semibold uppercase text-ink-3" title="Listing exchange">
              {infoMessage.exchange}
            </span>
          )}
        </span>

        <span
          className={`text-[15px] font-bold ${
            change ? (change.direction === 'down' ? 'text-down' : 'text-up') : 'text-ink'
          }`}
          data-testid="tp-last"
          title="Last trade price"
        >
          {formatPrice(lastPrice)}
        </span>

        {change && (
          <span
            className={`text-[12px] font-semibold ${change.direction === 'down' ? 'text-down' : 'text-up'}`}
            data-testid="tp-change"
            title="Change from the previous close"
          >
            {formatChange(change, lastPrice)}
          </span>
        )}

        <Field
          label="B"
          value={quote ? `${formatPrice(quote.bid)}×${formatCompact(quote.bidSize, 1)}` : '—'}
          testId="tp-bid"
          tone="text-up"
          title="Best bid × size in shares"
        />
        <Field
          label="A"
          value={quote ? `${formatPrice(quote.ask)}×${formatCompact(quote.askSize, 1)}` : '—'}
          testId="tp-ask"
          tone="text-down"
          title="Best ask × size in shares"
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

        {info && (info.halted || info.haltsToday > 0) && (
          <span
            className={`rounded-sm px-1 text-[10px] font-bold ${
              info.halted ? 'bg-down/20 text-down' : 'text-down'
            }`}
            data-testid="tp-halted"
            title={
              info.halted
                ? `Trading is halted — halt #${info.haltsToday} today`
                : `${info.haltsToday} halt${info.haltsToday === 1 ? '' : 's'} today`
            }
          >
            {info.halted ? `HALTED · ${info.haltsToday}` : `HALTS ${info.haltsToday}`}
          </span>
        )}

        {info?.haltActive && info.haltUp != null && (
          <span
            className="text-[10px] text-ink-3"
            data-testid="tp-halt"
            title="Distance to the LULD halt bands (5-minute reference)"
          >
            HALT ↑{formatPrice(info.haltUpDistance)}
            {info.haltUpPercent != null && ` (${formatPercent(info.haltUpPercent, 1)})`} ↓
            {formatPrice(info.haltDownDistance)}
            {info.haltDownPercent != null && ` (${formatPercent(info.haltDownPercent, 1)})`}
          </span>
        )}

        {info?.borrow && (
          <span
            className={`rounded-sm px-1 text-[10px] font-semibold ${BORROW_CLASS[info.borrow]}`}
            data-testid="tp-borrow"
            data-status={info.borrow}
            title={
              info.shortableShares != null
                ? `Borrow: ${formatCompact(info.shortableShares)} shares available (IBKR)`
                : 'Borrow availability (IBKR)'
            }
          >
            {BORROW_LABEL[info.borrow]}
          </span>
        )}

        {info?.listedDays != null && info.listedDays <= RECENT_IPO_DAYS && (
          <span
            className="rounded-sm bg-accent/15 px-1 text-[10px] font-semibold text-accent"
            data-testid="tp-ipo"
            title="Days since listing — recent IPOs have no overhead resistance and dilute freely"
          >
            IPO {info.listedDays}d
          </span>
        )}

        <span className="ml-auto">
          <BarSessionStrip />
        </span>
      </div>

      <div className="tnum flex flex-wrap items-baseline gap-x-3 gap-y-0.5 pt-0.5 font-mono">
        <Field
          label="VOL"
          value={formatCompact(info?.dayVolume)}
          testId="tp-dayvol"
          title="Shares traded today, pre-market included"
        />
        <Field
          label="RVOL"
          value={info?.relVol != null ? formatRotation(info.relVol) : '—'}
          testId="tp-relvol"
          highlight={info?.relVol != null && info.relVol >= 5}
          title="Today's volume over the 10-day average — 5x is the line"
        />
        <FloatField info={info} />
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
        {info?.pullback && (
          <span
            className={`rounded-sm px-1 text-[10px] font-semibold ${PULLBACK_CLASS[info.pullback.tone]}`}
            data-testid="tp-pullback"
            data-tone={info.pullback.tone}
            title={`${PULLBACK_TITLE[info.pullback.tone]} — leg ${info.pullback.legPercent.toFixed(0)}%`}
          >
            PB {info.pullback.depthPercent.toFixed(0)}%
            {info.pullback.volumeRatio != null && ` · ${info.pullback.volumeRatio.toFixed(1)}×`}
            {` · ${info.pullback.bars}b`}
          </span>
        )}
        {info?.reverseSplit && info.reverseSplit.daysAgo <= RECENT_SPLIT_DAYS && (
          <span
            className="rounded-sm px-1 text-[10px] font-semibold text-down"
            data-testid="tp-reverse-split"
            title="Reverse split — a serial diluter's move; recent ones flag offering risk"
          >
            R/S 1:{Math.round(info.reverseSplit.ratio)} · {info.reverseSplit.daysAgo}d
          </span>
        )}
        <Field
          label="MCAP"
          value={formatMoney(info?.marketCap)}
          testId="tp-mktcap"
          title="Market capitalisation — TradingView's snapshot; the per-bar live figure sits in the strip above. Under $500M is the small-cap lane"
        />
        {info?.allTimeHigh != null && (
          <Field
            label="ATH"
            value={`${formatPrice(info.allTimeHigh)}${
              info.athDistancePercent != null ? ` ${formatPercent(info.athDistancePercent, 0)}` : ''
            }`}
            testId="tp-ath"
            tone={
              info.athDistancePercent != null && info.athDistancePercent <= 0
                ? 'text-up'
                : undefined
            }
            highlight={
              info.athDistancePercent != null &&
              info.athDistancePercent > 0 &&
              info.athDistancePercent <= 10
            }
            title={
              info.athDistancePercent != null && info.athDistancePercent <= 0
                ? 'BLUE SKY — above every price this stock has ever traded; no overhead supply'
                : 'All-time high (TradingView, split-adjusted) and the headroom to it — within 10% the breakout has no bagholders left above'
            }
          />
        )}
        <Field
          label="AVG10D"
          value={formatCompact(info?.avgVol10d)}
          testId="tp-avgvol"
          title="Average daily volume over the last ten sessions — the RVOL denominator"
        />
        <Field
          label="PREV"
          value={formatPrice(info?.prevClose)}
          testId="tp-prevclose"
          title="Previous session's close — the gap and halt-band reference"
        />
        {live?.bar.n != null && live.bar.n > 0 && (
          <Field
            label="T/BAR"
            value={formatInteger(live.bar.n)}
            testId="tp-trades"
            title="Trades in the current bar — tape speed at a glance"
          />
        )}

        <span className="ml-auto">
          <OhlcvReadout />
        </span>
      </div>
    </section>
  );
}

function FloatField({ info }: { info: ReturnType<typeof buildInfoView> }) {
  const variation = info?.floatDisagreePercent ?? null;
  // The badge earns ink only past the threshold; the hover carries the
  // two-source comparison at ANY variation, because "the sources agree" is
  // itself information and invisible agreement is indistinguishable from
  // Yahoo never having answered.
  const disagree = variation != null && variation >= FLOAT_DISAGREE_PERCENT ? variation : null;
  const value = `${formatCompact(info?.floatShares)}${info?.floatSuspect ? ' ⚠' : ''}${
    disagree != null ? ` ±${Math.round(disagree)}%` : ''
  }`;
  const compared =
    variation != null
      ? `TradingView ${formatCompact(info?.floatShares)} vs Yahoo ${formatCompact(info?.yahooFloat)} · ±${Math.round(variation)}%`
      : 'Yahoo has not answered, so this is TradingView alone';
  // Two ways this number can be lying, in order of severity: impossible
  // against shares outstanding, or contradicted by the second source.
  const title = info?.floatSuspect
    ? `Float exceeds shares outstanding — reference data is stale or broken. ${compared}`
    : disagree != null
      ? `Sources disagree — an offering may have repriced the float. ${compared}`
      : `Float under 20M is the screen; under 10M preferred. ${compared}`;
  return (
    <Field
      label="FLOAT"
      value={value}
      testId="tp-float"
      tone={info?.floatSuspect || disagree != null ? 'text-down' : undefined}
      highlight={
        !info?.floatSuspect &&
        disagree == null &&
        info?.floatShares != null &&
        info.floatShares <= 20_000_000
      }
      title={title}
    />
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
