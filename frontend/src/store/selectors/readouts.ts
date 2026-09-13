/** What a trader acts on: the bar under the crosshair, the quote, the info strip. */

import { computeChange, daysUntil, type Change } from '@/lib/format';
import { sessionView } from '@/lib/session';
import type { InfoMessage, QuoteMessage, WireBar } from '@/types/protocol';

import type { Readout } from '../useTerminalStore';

export interface OhlcvView {
  bar: WireBar;
  /** This one candle's move: close against the previous bar's close. */
  barChange: Change | null;
  /** Change against the previous session's close — the gap, intraday. */
  sessionChange: Change | null;
  extendedHours: boolean;
  /** Cumulative session volume as of this bar. */
  sessionVolume: number | null;
  /** The day's pace at this bar: session volume so far over the 10-day avg. */
  rvolAtBar: number | null;
  /** Time-matched RVOL: this window against the same window on prior days. */
  windowRvol: number | null;
  /** Float turns as of this bar: session volume so far over the float. */
  rotationAtBar: number | null;
  /** Distance from VWAP at this bar, % — the polarity read, at that moment. */
  vwapDeltaPercent: number | null;
  /** Market cap at this bar's close: shares outstanding × close. */
  marketCapAtBar: number | null;
}

export function buildOhlcv(readout: Readout | null, info?: InfoMessage | null): OhlcvView | null {
  if (!readout) return null;
  const { bar, previousClose, values, sessionVolume } = readout;
  const prevDayClose = values['prev_day_close'];
  const vwap = values['vwap'];
  const avgVol = info?.avg_vol_10d;
  const floatShares = info?.float_shares;

  return {
    bar,
    barChange: previousClose != null ? computeChange(bar.c, previousClose) : null,
    sessionChange: prevDayClose != null ? computeChange(bar.c, prevDayClose) : null,
    extendedHours: bar.x === 1,
    sessionVolume: sessionVolume ?? null,
    rvolAtBar:
      sessionVolume != null && avgVol != null && avgVol > 0 ? sessionVolume / avgVol : null,
    // Server-computed off the 20-day minute base and stamped per bar, so it
    // exists on the 10-second chart too (stepping once a minute there).
    windowRvol: values['wrvol'] ?? null,
    rotationAtBar:
      sessionVolume != null && floatShares != null && floatShares > 0
        ? sessionVolume / floatShares
        : null,
    vwapDeltaPercent: vwap != null && vwap > 0 ? ((bar.c - vwap) / vwap) * 100 : null,
    marketCapAtBar:
      info?.shares_outstanding != null && info.shares_outstanding > 0
        ? info.shares_outstanding * bar.c
        : null,
  };
}

// ── level 1 quote ──────────────────────────────────────────────────────

/**
 * Spread tiers, in the units the decision is made in: ten cents starts to bite
 * on a single-digit stock, twenty is where trades are declined, fifty is the
 * hard ceiling.
 */
export type SpreadTone = 'tight' | 'ok' | 'wide' | 'untradeable';

export interface QuoteView {
  bid: number;
  ask: number;
  bidSize: number;
  askSize: number;
  mid: number;
  /** Absolute spread in dollars. */
  spread: number;
  /** Spread as a percentage of the mid. */
  spreadPercent: number;
  tone: SpreadTone;
  ageSeconds: number | null;
}

const MICROS = 1_000_000;

export function buildQuoteView(quote: QuoteMessage | null, now?: number): QuoteView | null {
  if (!quote || quote.bid <= 0 || quote.ask <= 0 || quote.ask < quote.bid) return null;
  // In whole millionths: 3.20 - 3.00 in floats is 0.20000000000000018, a
  // tier wider than the 1.20 - 1.00 that sits beside it.
  const spread = (Math.round(quote.ask * MICROS) - Math.round(quote.bid * MICROS)) / MICROS;
  const mid = (quote.ask + quote.bid) / 2;
  return {
    bid: quote.bid,
    ask: quote.ask,
    bidSize: quote.bs,
    askSize: quote.as,
    mid,
    spread,
    spreadPercent: mid > 0 ? (spread / mid) * 100 : 0,
    tone: spreadTone(spread),
    ageSeconds: now !== undefined && quote.t > 0 ? Math.max(0, now - quote.t) : null,
  };
}

export function spreadTone(spread: number): SpreadTone {
  const micros = Math.round(spread * MICROS);
  if (micros > 500_000) return 'untradeable';
  if (micros > 200_000) return 'wide';
  if (micros > 100_000) return 'ok';
  return 'tight';
}

// ── request budgets ────────────────────────────────────────────────────

/**
 * How much headroom a request window has left: `ok` above half, `warn` down to
 * a fifth, `hot` below — the next burst of switches will queue behind the
 * limiter.
 */
export type BudgetTone = 'ok' | 'warn' | 'hot';

export function budgetTone(used: number, limit: number): BudgetTone {
  if (limit <= 0) return 'hot';
  // Compare on the used fraction: `1 - 160/200` misses 0.2 by an ulp.
  const usedFraction = used / limit;
  if (usedFraction <= 0.5) return 'ok';
  if (usedFraction <= 0.8) return 'warn';
  return 'hot';
}

// ── info strip ─────────────────────────────────────────────────────────

export interface InfoView {
  floatShares: number | null;
  /**
   * Market cap on the previous close: shares outstanding × yesterday's close.
   *
   * Fixed for the whole session — what the name was worth before the move, so
   * "a $12M company up 50%" means the same at 09:31 and 15:59. The current cap
   * in the panel beside it is the moving twin.
   */
  marketCap: number | null;
  /** TradingView's own snapshot, the fallback with no share count. */
  reportedMarketCap: number | null;
  dayVolume: number;
  pmVolume: number;
  avgVol10d: number | null;
  relVol: number | null;
  /** Times the float has turned over today. */
  floatRotation: number | null;
  /** Fraction of the float traded before the open — ≥10% flags a runner. */
  pmFloatRotation: number | null;
  prevClose: number | null;
  /** Gap/day change versus the previous close, from the latest price. */
  sessionChange: Change | null;
  haltUp: number | null;
  haltDown: number | null;
  haltActive: boolean;
  /**
   * The session's LULD band width — 10 or 20 percent, or the fixed cents
   * below $0.75. Fixed by last night's close, so it is a property of the
   * name for the whole day rather than of the moment.
   */
  haltBandPercent: number | null;
  haltBandCents: number | null;
  /** Distance from the last price to each band, in dollars. */
  haltUpDistance: number | null;
  haltDownDistance: number | null;
  /** Headroom to each band as a percentage of the last price. */
  haltUpPercent: number | null;
  haltDownPercent: number | null;
  /** Days since listing, when young enough to matter. */
  listedDays: number | null;
  /** Days until the next scheduled report; negative once it has passed. */
  earningsInDays: number | null;
  borrow: BorrowStatus | null;
  shortableShares: number | null;
  /** Halted right now. */
  halted: boolean;
  haltsToday: number;
  /** Live only inside the fifteen minutes the reopen study covers. */
  reopen: ReopenView | null;
  /** The latest reverse split: 10 means 1-for-10, `daysAgo` its recency. */
  reverseSplit: { ratio: number; daysAgo: number } | null;
  yahooFloat: number | null;
  /** Divergence between the two float sources; null unless both answered. */
  floatDisagreePercent: number | null;
  pullback: PullbackView | null;
  /** Float exceeding shares outstanding — stale or broken reference data. */
  floatSuspect: boolean;
  description: string;
  exchange: string;
  sector: string;
}

/**
 * IBKR's shortable magnitude, bucketed the way TWS colours it: above 2.5
 * there is stock to borrow, 1.5–2.5 needs a locate, below 1.5 there is none.
 */
export type BorrowStatus = 'easy' | 'locate' | 'none';

export function borrowStatus(shortable: number | null): BorrowStatus | null {
  if (shortable == null) return null;
  if (shortable > 2.5) return 'easy';
  if (shortable >= 1.5) return 'locate';
  return 'none';
}

/** Show the IPO badge for listings younger than this. */
export const RECENT_IPO_DAYS = 90;

/** Show the reverse-split badge inside this window — the diluter's year. */
export const RECENT_SPLIT_DAYS = 365;

/** Sources disagreeing on the float by at least this much get the badge. */
export const FLOAT_DISAGREE_PERCENT = 25;

/**
 * How far the two float sources diverge, as a percentage of the smaller.
 * Null unless both actually answered — one source is silence, not agreement.
 */
export function floatDisagreement(
  tv: number | null,
  yahoo: number | null,
): number | null {
  if (tv == null || yahoo == null || tv <= 0 || yahoo <= 0) return null;
  return (Math.abs(tv - yahoo) / Math.min(tv, yahoo)) * 100;
}

// ── pullback quality ───────────────────────────────────────────────────

export interface PullbackView {
  depthPercent: number;
  volumeRatio: number | null;
  bars: number;
  legPercent: number;
  tone: PullbackTone;
}

/**
 * The playbook's first-pullback judgment: `failed` past the 78.6% fib, `stale`
 * at ten minutes off the high, `healthy` when the top half of the leg holds and
 * volume has dried to half the rally's pace, `ok` in between.
 */
export type PullbackTone = 'healthy' | 'ok' | 'failed' | 'stale';

export function pullbackTone(
  depthPercent: number,
  volumeRatio: number | null,
  bars: number,
): PullbackTone {
  if (depthPercent >= 78.6) return 'failed';
  if (bars >= 10) return 'stale';
  if (depthPercent <= 50 && volumeRatio != null && volumeRatio <= 0.5) return 'healthy';
  return 'ok';
}

// ── the reopen window ──────────────────────────────────────────────────

/**
 * The fifteen minutes after a halt lifts — the one condition in the playbook
 * with a large measured effect behind it.
 *
 * Across 66,785 reopens the following fifteen minutes averaged +0.33%; the
 * 2,805 reopening before 10:00 ET averaged +3.10% (t = 9.2, 61% up). The sign
 * flips on a name that has already run: 3,121 reopens on stocks extended
 * 30–100% averaged −1.09% (t = −4.6).
 *
 * The read states which conditions hold now and says nothing about trading.
 * `extended` is the only bucket that measured negative.
 */
export const REOPEN_WINDOW_SECONDS = 15 * 60;

/** Reopens after this New York minute fall outside the measured cohort. */
export const REOPEN_LATE_MINUTE = 10 * 60;

/** Day change at or above this put the reopen in the negative bucket. */
export const REOPEN_EXTENDED_PERCENT = 30;

/** The wide LULD tier, which the study mildly preferred. */
const WIDE_BAND_PERCENT = 20;

export type ReopenTone = 'aligned' | 'late' | 'extended';

export interface ReopenView {
  /** Seconds since the tape came back. */
  secondsSince: number;
  tone: ReopenTone;
  /** On the 20% band rather than the 10% one. */
  wideBand: boolean;
}

/**
 * Both clocks are the server's — `generated_at` and the resume stamp come from
 * one process — so a client whose clock is out still reads the right elapsed
 * time.
 *
 * The time-of-day test runs against the *resume*, not now: the cohort is
 * defined by when the stock came back, so a 09:58 reopen stays in it past ten.
 */
export function reopenRead(info: InfoMessage, changePercent: number | null): ReopenView | null {
  if (info.halted || info.halt_resumed_at == null) return null;
  const secondsSince = info.generated_at - info.halt_resumed_at;
  if (secondsSince < 0 || secondsSince > REOPEN_WINDOW_SECONDS) return null;

  const resumedMinute = sessionView(new Date(info.halt_resumed_at * 1000)).minutes;
  const extended = changePercent != null && changePercent >= REOPEN_EXTENDED_PERCENT;
  return {
    secondsSince,
    tone: extended ? 'extended' : resumedMinute >= REOPEN_LATE_MINUTE ? 'late' : 'aligned',
    wideBand: info.halt_band_pct === WIDE_BAND_PERCENT,
  };
}

export function buildInfoView(info: InfoMessage | null, lastPrice: number | null): InfoView | null {
  if (!info) return null;
  const sessionChange =
    lastPrice != null && info.prev_close != null && info.prev_close !== 0
      ? computeChange(lastPrice, info.prev_close)
      : null;
  return {
    floatShares: info.float_shares,
    // Derived from the previous close rather than taken from TradingView,
    // because TradingView's snapshot is priced at whenever it last refreshed
    // — which on a runner is neither yesterday nor now. The reported figure
    // stays as the fallback for names with no share count.
    marketCap:
      info.shares_outstanding != null && info.shares_outstanding > 0 && info.prev_close != null
        ? info.shares_outstanding * info.prev_close
        : info.market_cap,
    reportedMarketCap: info.market_cap,
    dayVolume: info.day_volume,
    pmVolume: info.pm_volume,
    avgVol10d: info.avg_vol_10d,
    relVol: info.rel_vol,
    floatRotation: info.float_rotation,
    pmFloatRotation: info.pm_float_rotation,
    prevClose: info.prev_close,
    sessionChange,
    haltUp: info.halt_up,
    haltDown: info.halt_down,
    haltActive: info.halt_active,
    haltBandPercent: info.halt_band_pct,
    haltBandCents: info.halt_band_cents,
    haltUpDistance:
      info.halt_up != null && lastPrice != null ? info.halt_up - lastPrice : null,
    haltDownDistance:
      info.halt_down != null && lastPrice != null ? lastPrice - info.halt_down : null,
    haltUpPercent:
      info.halt_up != null && lastPrice != null && lastPrice > 0
        ? ((info.halt_up - lastPrice) / lastPrice) * 100
        : null,
    haltDownPercent:
      info.halt_down != null && lastPrice != null && lastPrice > 0
        ? ((lastPrice - info.halt_down) / lastPrice) * 100
        : null,
    listedDays: info.listed_days,
    earningsInDays: daysUntil(info.earnings_next, info.generated_at),
    borrow: borrowStatus(info.shortable),
    shortableShares: info.shortable_shares,
    halted: info.halted,
    haltsToday: info.halts_today,
    reopen: reopenRead(info, sessionChange?.percent ?? null),
    reverseSplit:
      info.reverse_split_ratio != null && info.reverse_split_days != null
        ? { ratio: info.reverse_split_ratio, daysAgo: info.reverse_split_days }
        : null,
    yahooFloat: info.yahoo_float,
    floatDisagreePercent: floatDisagreement(info.float_shares, info.yahoo_float),
    pullback:
      info.pullback_depth_pct != null && info.pullback_bars != null && info.pullback_leg_pct != null
        ? {
            depthPercent: info.pullback_depth_pct,
            volumeRatio: info.pullback_vol_ratio,
            bars: info.pullback_bars,
            legPercent: info.pullback_leg_pct,
            tone: pullbackTone(info.pullback_depth_pct, info.pullback_vol_ratio, info.pullback_bars),
          }
        : null,
    floatSuspect:
      info.float_shares != null &&
      info.shares_outstanding != null &&
      info.float_shares > info.shares_outstanding,
    description: info.description,
    exchange: info.exchange,
    sector: info.sector,
  };
}
