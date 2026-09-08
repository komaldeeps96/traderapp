/**
 * Order arithmetic for the button previews.
 *
 * A direct mirror of `backend/app/domain/orders.py`, asserted against the same
 * case table in `order-cases.json` so the two cannot drift.
 *
 * WHY IT EXISTS TWICE. The button has to read `$25 · 6 sh` and update as the
 * spread moves, which is a hundred times a minute — asking the server for that
 * number would put a round trip inside a readout. So the client previews
 * locally. But the client never *sends* a quantity: the command carries the
 * dollar amount or the fraction, and the backend recomputes the shares from
 * its own freshest quote at the instant of the order. A tab that has been
 * asleep for a minute therefore cannot put a stale size on the wire, and this
 * file is a display, not a decision.
 *
 * EVERYTHING IS INTEGER ARITHMETIC IN MILLIONTHS OF A DOLLAR — the same choice
 * the backend makes, and the reason the two agree bit for bit. In floats,
 * `0.98 - 0.05` is 0.9299999999999999, and the flooring step that snaps a sell
 * onto its tick turns that into a limit of 0.9299 — a hundredth of a penny
 * below where it was meant to be, arrived at silently. A micro-dollar is exact
 * for every price a US equity can quote, and a million dollars is 1e12, well
 * inside the 2^53 a double represents exactly.
 */

import type { BlockedReason } from "@/types/protocol";

const MICROS = 1_000_000;

/** SEC Rule 612: a penny at or above a dollar, a hundredth of a penny below. */
const TICK_ABOVE_DOLLAR = 10_000;
const TICK_BELOW_DOLLAR = 100;
const BPS = 10_000;

export interface OffsetConfig {
  /** The flat floor, in cents. */
  cents: number;
  /** The proportionate part, in basis points. The larger of the two wins. */
  bps: number;
}

export function toMicros(price: number): number {
  return Math.round(price * MICROS);
}

export function toPrice(micros: number): number {
  return micros / MICROS;
}

/**
 * The minimum increment at that price — read off the *order's own price*, not
 * off the quote it came from. A sell priced down through the dollar mark (bid
 * 1.02, limit 0.97) is an order priced under a dollar, so Rule 612 gives it
 * the finer grid.
 */
export function tickMicros(priceMicros: number): number {
  return priceMicros >= MICROS ? TICK_ABOVE_DOLLAR : TICK_BELOW_DOLLAR;
}

/**
 * How far through the book to price, in micros.
 *
 * Five cents is 12bps on a $40 name and 12.5% on a $0.40 one, so neither part
 * is the right shape alone. At 5c/15bps the two cross at $33.33.
 */
export function offsetMicros(
  priceMicros: number,
  offset: OffsetConfig,
): number {
  const flat = Math.round(offset.cents * (MICROS / 100));
  const proportionate = Math.round((priceMicros * offset.bps) / BPS);
  return Math.max(flat, proportionate);
}

/** Marketable buy limit: through the offer, snapped **up** onto a tick. */
export function buyLimit(ask: number, offset: OffsetConfig): number {
  const askMicros = toMicros(ask);
  const raw = askMicros + offsetMicros(askMicros, offset);
  const tick = tickMicros(raw);
  return toPrice(Math.ceil(raw / tick) * tick);
}

/**
 * Marketable sell limit: through the bid, snapped **down** onto a tick.
 *
 * Clamped at one tick above zero — a wide offset on a two-cent stock would
 * otherwise price the order at or below nothing, which TWS rejects, and an
 * exit that will not leave the building is the one failure this side cannot
 * afford.
 */
export function sellLimit(bid: number, offset: OffsetConfig): number {
  const bidMicros = toMicros(bid);
  const raw = bidMicros - offsetMicros(bidMicros, offset);
  const tick = tickMicros(raw);
  return toPrice(Math.max(tick, Math.floor(raw / tick) * tick));
}

/**
 * How many whole shares `dollars` buys at `ask`.
 *
 * Sized on the ask — the price expected to be paid — so the button's own
 * label is the number a person would compute. Integer division, so an exactly
 * divisible amount cannot come out one share short.
 *
 * Zero is an ordinary answer: a $10 button is dead on anything over $10 a
 * share, and the button disables rather than sending an empty order.
 */
export function sharesForDollars(dollars: number, ask: number): number {
  const askMicros = toMicros(ask);
  const dollarMicros = toMicros(dollars);
  if (askMicros <= 0 || dollarMicros <= 0) return 0;
  return Math.floor(dollarMicros / askMicros);
}

/**
 * How many whole shares `fraction` of a long position comes to.
 *
 * A whole-position exit returns the position exactly rather than a proportion
 * of it, so nothing can leave a share behind on the one order whose entire
 * purpose is to leave nothing behind. Long only: clamped to the position, so
 * no fraction can open a short.
 */
export function sharesForFraction(position: number, fraction: number): number {
  if (position <= 0 || fraction <= 0) return 0;
  if (fraction >= 1) return position;
  return Math.min(
    position,
    Math.floor((position * Math.round(fraction * BPS)) / BPS),
  );
}

export interface ButtonPlan {
  shares: number;
  limit: number;
  notional: number;
  /** Null when the button is live; otherwise why it is dead. */
  blocked: BlockedReason | null;
}

export interface QuoteLike {
  bid: number;
  ask: number;
}

function quoteOk(quote: QuoteLike | null | undefined): quote is QuoteLike {
  return !!quote && quote.bid > 0 && quote.ask > 0 && quote.ask >= quote.bid;
}

/**
 * What a buy button shows.
 *
 * The notional is measured at the limit, matching the backend's cap check, so
 * a button that the server would refuse for the cap is drawn as refused here
 * rather than failing on the click.
 */
export function previewBuy(
  dollars: number,
  quote: QuoteLike | null | undefined,
  offset: OffsetConfig,
  maxOrderDollars: number,
): ButtonPlan {
  if (!quoteOk(quote))
    return { shares: 0, limit: 0, notional: 0, blocked: "no_quote" };

  const limit = buyLimit(quote.ask, offset);
  const shares = sharesForDollars(dollars, quote.ask);
  if (shares <= 0)
    return { shares: 0, limit, notional: 0, blocked: "too_small" };

  const notional = toPrice(shares * toMicros(limit));
  const blocked =
    dollars > maxOrderDollars || toMicros(notional) > toMicros(maxOrderDollars)
      ? "over_cap"
      : null;
  return { shares, limit, notional, blocked };
}

/** What a sell button shows. No cap: the ceiling bounds what may be bought. */
export function previewSell(
  fraction: number,
  position: number,
  quote: QuoteLike | null | undefined,
  offset: OffsetConfig,
): ButtonPlan {
  if (position <= 0)
    return { shares: 0, limit: 0, notional: 0, blocked: "no_position" };
  if (!quoteOk(quote))
    return { shares: 0, limit: 0, notional: 0, blocked: "no_quote" };

  const limit = sellLimit(quote.bid, offset);
  const shares = sharesForFraction(position, fraction);
  if (shares <= 0)
    return { shares: 0, limit, notional: 0, blocked: "too_small" };
  return {
    shares,
    limit,
    notional: toPrice(shares * toMicros(limit)),
    blocked: null,
  };
}

/** The label on a sell button: `ALL`, or the percentage. */
export function sellLabel(fraction: number): string {
  return fraction >= 1 ? "ALL" : `${Math.round(fraction * 100)}%`;
}
