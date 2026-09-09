import type { ReactNode } from 'react';

import {
  formatChange,
  formatCompact,
  formatElapsed,
  formatMoney,
  formatPercent,
  formatPrice,
  formatRotation,
  formatSpread,
  formatUnsignedPercent,
} from '@/lib/format';
import {
  buildDilutionView,
  buildInfoView,
  buildOhlcv,
  buildQuoteView,
  FLOAT_DISAGREE_PERCENT,
  RECENT_IPO_DAYS,
  RECENT_SPLIT_DAYS,
  type BorrowStatus,
  type HeadroomTone,
  type InfoView,
  type OhlcvView,
  type PullbackTone,
  type ReopenTone,
  type SpreadTone,
} from '@/store/selectors';
import { useKeyLevels } from '@/hooks/useKeyLevels';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { DilutionTone } from '@/types/protocol';

import { OhlcvReadout } from './OhlcvReadout';
import { Divider, Field } from './PanelField';

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

/**
 * The reopen chip's tones.
 *
 * `aligned` is the up colour, the condition that measured strongly positive.
 * `extended` takes the failed leg's red, being the only bucket that measured
 * negative. `late` is neither — outside the cohort is not evidence.
 */
const REOPEN_CLASS: Record<ReopenTone, string> = {
  aligned: 'text-up',
  late: 'text-ink-3',
  extended: 'bg-down/20 text-down',
};

/** The band tier, as a suffix on the LULD label: " 20%", " 15¢", or "". */
function formatBandTier(info: InfoView): string {
  if (info.haltBandPercent != null) return ` ${info.haltBandPercent.toFixed(0)}%`;
  if (info.haltBandCents != null) return ` ${info.haltBandCents.toFixed(0)}¢`;
  return '';
}

function bandTierTitle(info: InfoView): string {
  if (info.haltBandPercent != null) {
    return `Tier 2 band is ±${info.haltBandPercent.toFixed(0)}%, set by the previous close and fixed for the session.`;
  }
  if (info.haltBandCents != null) {
    return `Below $0.75 the band is a fixed ±${info.haltBandCents.toFixed(0)}¢, set by the previous close.`;
  }
  return '';
}

/**
 * How close a scheduled report is, and how loudly to say so: red inside a week,
 * amber inside a fortnight, quiet beyond.
 *
 * Past dates are dropped — TradingView keeps serving the last scheduled date
 * after the event, and "ERN -3d" reads as a date to avoid.
 */
const EARNINGS_URGENT_DAYS = 7;
const EARNINGS_NEAR_DAYS = 14;
const EARNINGS_HORIZON_DAYS = 60;

function earningsClass(days: number): string {
  if (days <= EARNINGS_URGENT_DAYS) return 'bg-down/20 text-down';
  if (days <= EARNINGS_NEAR_DAYS) return 'bg-elevated text-accent-text';
  return 'bg-elevated text-ink-3';
}

function earningsLabel(days: number): string {
  if (days === 0) return 'ERN TODAY';
  return `ERN ${days}d`;
}

/**
 * The headroom chip's tones.
 *
 * `blue-sky` is the up colour: no overhead means no level the crowd has
 * pre-committed to stop at, which licenses holding rather than scalping.
 * `capped` is red — a target closer than its own execution cost is not a trade.
 */
const HEADROOM_CLASS: Record<HeadroomTone, string> = {
  'blue-sky': 'bg-up/15 text-up',
  clear: 'text-ink-2',
  capped: 'bg-down/20 text-down',
};

/**
 * Distance to a halt band.
 *
 * The arrow carries the direction, so a positive distance needs no sign. A
 * *negative* one is not a distance — it is price already through the band,
 * which the five-minute reference makes routine on a fast mover, and rendering
 * it as "−6.8%" would read as room rather than as one side being gone.
 */
function formatBandDistance(percent: number | null): string {
  if (percent == null) return '—';
  return percent < 0 ? 'PAST' : formatUnsignedPercent(percent, 1);
}

const REOPEN_TITLE: Record<ReopenTone, string> = {
  aligned:
    'Reopened before 10:00 and not extended — the measured cohort: +3.10% mean over the next 15 minutes across 2,805 reopens (median +2.44%, 61% up)',
  late: 'Reopened after 10:00 — outside the measured cohort, which found no comparable edge later in the day',
  extended:
    'Reopened already up 30%+ on the day — the one bucket that measured negative: −1.09% mean over the next 15 minutes across 3,121 reopens',
};

/**
 * The dilution chip's tones. `clean` never renders, so it has no entry; the
 * other three escalate to the red the untradeable spread and failed leg use.
 */
const DILUTION_CLASS: Record<Exclude<DilutionTone, 'clean'>, string> = {
  watch: 'text-ink-3',
  heavy: 'text-warn',
  serial: 'bg-down/20 text-down',
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
 * Three rows, in the order a candidate is disqualified in:
 *
 *   TAPE      can I trade it now — price, quote, spread, and the conditions
 *             that stop a trade dead (halt, borrow, failed leg)
 *   SESSION   what the day has done — volume, rotation, supply to chew through
 *   BAR       what is under the crosshair — the OHLCV readout
 *
 * Two rules hold the layout still: nothing is right-aligned with `ml-auto`, so
 * a long value cannot shunt the readout onto its own line, and every value goes
 * through a formatter with a bounded width.
 *
 * The session row follows the crosshair — hovering a candle rewinds volume,
 * rotation and market cap to that moment — so the day is stated once, not twice.
 */
export function TopPanel() {
  const symbol = useTerminalStore((state) => state.symbol);
  const live = useTerminalStore((state) => state.live);
  const hovered = useTerminalStore((state) => state.hovered);
  const quoteMessage = useTerminalStore((state) => state.quote);
  const infoMessage = useTerminalStore((state) => state.info);

  const lastPrice = live?.bar.c ?? null;
  const quote = buildQuoteView(quoteMessage);
  const info = buildInfoView(infoMessage, lastPrice);
  const atBar = buildOhlcv(hovered ?? live, infoMessage);
  const dilution = buildDilutionView(infoMessage?.dilution, lastPrice);
  // Shared with the sidebar ladder, so both name the same level as the next
  // thing in the way.
  const { headroom } = useKeyLevels();

  if (!symbol) return null;

  const change = info?.sessionChange ?? null;

  return (
    <section
      className="shrink-0 border-b border-line bg-panel px-2 py-1"
      data-testid="top-panel"
      aria-label="Symbol information"
    >
      <Row>
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

        {atBar?.vwapDeltaPercent != null && (
          <span
            className={`text-[11px] ${atBar.vwapDeltaPercent >= 0 ? 'text-up' : 'text-down'}`}
            data-testid="tp-vwap"
            title="Distance from VWAP — the polarity read; it follows the crosshair"
          >
            VWAP {formatPercent(atBar.vwapDeltaPercent, 1)}
          </span>
        )}

        <Divider />

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
            {formatSpread(quote.spread)} · {formatUnsignedPercent(quote.spreadPercent, 1)}
          </span>
        )}

        <Divider />

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

        {/* The minutes after a resume. Only condition in the playbook with a
            large measured effect behind it, and it expires on its own. */}
        {info?.reopen && (
          <span
            className={`rounded-sm px-1 text-[10px] font-semibold ${REOPEN_CLASS[info.reopen.tone]}`}
            data-testid="tp-reopen"
            data-tone={info.reopen.tone}
            title={`${REOPEN_TITLE[info.reopen.tone]}${
              info.reopen.wideBand ? ' · on the wide 20% band, which measured better than 10%' : ''
            }`}
          >
            REOPEN {formatElapsed(info.reopen.secondsSince)}
          </span>
        )}

        {/* Headroom to the LULD bands, in the unit the decision is made in.
            The dollar distances the percentages come from ride the hover —
            two prices and two percentages was four numbers to answer one
            question. The tier leads, because it is what decides whether a
            break has room to run and it is fixed for the whole session. */}
        {info?.haltActive && info.haltUpPercent != null && (
          <span
            className="text-[10px] text-ink-3"
            data-testid="tp-halt"
            data-band={info.haltBandPercent ?? undefined}
            title={`LULD halt bands (5-minute reference): ${formatPrice(info.haltUp)} up, ${formatPrice(info.haltDown)} down — ${formatPrice(info.haltUpDistance)} and ${formatPrice(info.haltDownDistance)} away. ${bandTierTitle(info)}`}
          >
            LULD{formatBandTier(info)}{' '}
            <span className="font-semibold text-ink-2">
              ↑{formatBandDistance(info.haltUpPercent)}
            </span>{' '}
            <span className="font-semibold text-ink-2">
              ↓{formatBandDistance(info.haltDownPercent)}
            </span>
          </span>
        )}

        {info?.earningsInDays != null &&
          info.earningsInDays >= 0 &&
          info.earningsInDays <= EARNINGS_HORIZON_DAYS && (
            <span
              className={`rounded-sm px-1 text-[10px] font-semibold ${earningsClass(
                info.earningsInDays,
              )}`}
              data-testid="tp-earnings"
              data-days={info.earningsInDays}
              title="Next scheduled earnings report. A position held through one is a different trade from the one that was opened."
            >
              {earningsLabel(info.earningsInDays)}
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

        {headroom && (
          <span
            className={`rounded-sm px-1 text-[10px] font-semibold ${HEADROOM_CLASS[headroom.tone]}`}
            data-testid="tp-headroom"
            data-tone={headroom.tone}
            title={
              headroom.level
                ? `${formatUnsignedPercent(headroom.percent, 1)} to ${headroom.level.label} at ${formatPrice(headroom.level.value)} — the next level the crowd has agreed to look at.${
                    headroom.tone === 'capped'
                      ? ' Closer than a base hit costs to execute.'
                      : ''
                  }`
                : 'Nothing overhead in the ladder — no level to stop at, and no target either'
            }
          >
            {headroom.level ? `ROOM ${formatUnsignedPercent(headroom.percent, 1)}` : 'BLUE SKY'}
          </span>
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

        {info?.listedDays != null && info.listedDays <= RECENT_IPO_DAYS && (
          <span
            className="rounded-sm bg-accent/15 px-1 text-[10px] font-semibold text-accent"
            data-testid="tp-ipo"
            title="Days since listing — recent IPOs have no overhead resistance and dilute freely"
          >
            IPO {info.listedDays}d
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

        {/* Supply that can arrive without warning belongs beside the other
            disqualifiers — a warrant overhang in the money stops a long the
            way no borrow stops a short. Only the worst fact fits here; the
            rest are in the tooltip and in full in the dock's fundamentals
            tab. Nothing renders for a company with a clean read. */}
        {dilution && (
          <span
            className={`rounded-sm px-1 text-[10px] font-semibold ${DILUTION_CLASS[dilution.tone]}`}
            data-testid="tp-dilution"
            data-tone={dilution.tone}
            title={`Dilution risk: ${dilution.tone} — ${dilution.detail}`}
          >
            {dilution.label}
          </span>
        )}
      </Row>

      <SessionRow info={info} atBar={atBar} hovering={hovered != null} />

      <OhlcvReadout />
    </section>
  );
}

/**
 * The day, as of whatever bar is being read: the provider's own figure while
 * the crosshair is off, the chart's cumulative sum once it rewinds the day.
 */
function SessionRow({
  info,
  atBar,
  hovering,
}: {
  info: InfoView | null;
  atBar: OhlcvView | null;
  hovering: boolean;
}) {
  const volume = asOf(hovering, atBar?.sessionVolume, info?.dayVolume);
  const relVol = asOf(hovering, atBar?.rvolAtBar, info?.relVol);
  const rotation = asOf(hovering, atBar?.rotationAtBar, info?.floatRotation);
  const currentCap = atBar?.marketCapAtBar ?? null;

  return (
    <Row className="pt-0.5" testId="session-row" hovering={hovering}>
      <Field
        label="VOL"
        value={formatCompact(volume)}
        testId="tp-vol"
        title="Shares traded today, pre-market included — cumulative to the hovered bar"
      />
      <Field
        label="RVOL"
        value={formatRotation(relVol)}
        testId="tp-rvol"
        highlight={relVol != null && relVol >= 5}
        title="The day's pace over the 10-day average — 5x is the line"
      />
      {atBar?.windowRvol != null && (
        <Field
          label="WRVOL"
          value={formatRotation(atBar.windowRvol)}
          testId="tp-wrvol"
          title="Time-matched relative volume — this 4am→bar window against a typical session's volume by the same time of day, over the last 50 sessions"
        />
      )}

      <Divider />

      <FloatField info={info} />
      <Field
        label="ROT"
        value={formatRotation(rotation)}
        testId="tp-rot"
        highlight={rotation != null && rotation >= 1}
        title="Times the float has traded today — supply exhaustion read"
      />
      {info?.pmFloatRotation != null && info.pmVolume > 0 && (
        <Field
          label="PM ROT"
          value={formatUnsignedPercent(info.pmFloatRotation * 100, 0)}
          testId="tp-pm-rotation"
          highlight={info.pmFloatRotation >= 0.1}
          title="Premarket volume as a share of the float — 10%+ flags a runner"
        />
      )}

      <Divider />

      {/* Two caps, because the pair is the read: what the company was worth
          before the move, and what the tape is asking for it now. One number
          alone cannot say "a $9M shell being bid at $12M". */}
      <Field
        label="MCAP"
        value={formatMoney(info?.marketCap)}
        testId="tp-mcap"
        title={`Market cap on the previous close — shares outstanding × ${formatPrice(info?.prevClose)}. Fixed for the session, so it says what the company was worth before today. Under $500M is the small-cap lane`}
      />
      <Field
        label="C_MCAP"
        value={formatMoney(currentCap)}
        testId="tp-cmcap"
        title="Market cap right now — shares outstanding × the last trade; it follows the crosshair back to the hovered bar"
      />
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
      {/* The all-time high used to sit here. It is a price, so it belongs in
          the key levels ladder with the 52-week high, sorted by where it
          actually is — not as a field whose distance percentage ran to eleven
          digits on a reverse-split name. */}
    </Row>
  );
}

/**
 * The figure for the bar being read: the snapshot while live, the chart's
 * own reconstruction once the crosshair rewinds it — and either one as a
 * fallback when the other has nothing to say.
 */
function asOf(
  hovering: boolean,
  atBar: number | null | undefined,
  snapshot: number | null | undefined,
): number | null {
  const primary = hovering ? atBar : snapshot;
  return primary ?? atBar ?? snapshot ?? null;
}

function FloatField({ info }: { info: InfoView | null }) {
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

/**
 * One line of the panel. Wrapping is allowed but nothing inside is
 * right-aligned, so an overlong value pushes the tail of its own row down
 * rather than rearranging the panel.
 */
function Row({
  children,
  className = '',
  testId,
  hovering,
}: {
  children: ReactNode;
  className?: string;
  testId?: string;
  hovering?: boolean;
}) {
  return (
    <div
      className={`tnum flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 font-mono ${className}`}
      data-testid={testId}
      data-hovering={hovering === undefined ? undefined : hovering ? 'true' : 'false'}
    >
      {children}
    </div>
  );
}

