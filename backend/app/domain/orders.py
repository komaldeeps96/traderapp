"""Order arithmetic: dollars to shares, quote to limit price.

Pure functions, mirrored in ``frontend/src/lib/orders.ts``; both are asserted
against ``frontend/src/lib/order-cases.json`` so they cannot drift.

**Integer arithmetic in millionths of a dollar throughout.** In floats
``0.98 - 0.05`` is 0.9299999999999999 and the tick snap turns that into a limit
of 0.9299. A micro-dollar is exact for every price Rule 612 allows, and $1M is
1e12 — inside the 2^53 both Python ints and JS doubles hold exactly, so the two
languages agree bit for bit.

Three rules run through all of it: whole shares are always floored, never
rounded; the offset is a cap, not a price; and tick rounding goes in the
marketable direction (buys up, sells down) so a marketable order is never
pushed back inside the spread.
"""

from __future__ import annotations

from dataclasses import dataclass

MICROS = 1_000_000
"""Millionths of a dollar per dollar."""

# SEC Rule 612: the minimum pricing increment is a penny at or above a
# dollar, and a hundredth of a penny below it. A limit price off-tick is
# rejected, so every price this module returns is snapped to one of these.
TICK_ABOVE_DOLLAR = 10_000  # $0.01
TICK_BELOW_DOLLAR = 100  # $0.0001
SUB_DOLLAR_THRESHOLD = MICROS  # $1.00

BPS = 10_000
"""Basis points in one whole."""


def to_micros(price: float) -> int:
    """A price as an exact integer count of millionths of a dollar."""
    return round(price * MICROS)


def to_price(micros: int) -> float:
    """Back to a float, for the wire. Exact for anything on a valid tick."""
    return micros / MICROS


def tick_micros(price_micros: int) -> int:
    """The minimum price increment at that price, in micros.

    Read off the *order's own price*, not the quote it came from. A sell priced
    down through the dollar mark — bid 1.02, limit 0.97 — is an order under a
    dollar, so Rule 612 gives it the finer grid.
    """
    return TICK_ABOVE_DOLLAR if price_micros >= SUB_DOLLAR_THRESHOLD else TICK_BELOW_DOLLAR


def offset_micros(price_micros: int, *, offset_cents: float, offset_bps: float) -> int:
    """How far through the book to price, in micros.

    The larger of a flat cent figure and a proportionate one: five cents is
    12 bps on a $40 name and 12.5% on a $0.40 one, so neither is the right shape
    alone. At 5c and 15bps they cross at $33.33.
    """
    flat = round(offset_cents * (MICROS // 100))
    proportionate = round(price_micros * offset_bps / BPS)
    return max(flat, proportionate)


def buy_limit(ask: float, *, offset_cents: float, offset_bps: float) -> float:
    """Marketable buy limit: through the offer, snapped up onto a tick."""
    ask_micros = to_micros(ask)
    raw = ask_micros + offset_micros(ask_micros, offset_cents=offset_cents, offset_bps=offset_bps)
    tick = tick_micros(raw)
    return to_price(-(-raw // tick) * tick)


def sell_limit(bid: float, *, offset_cents: float, offset_bps: float) -> float:
    """Marketable sell limit: through the bid, snapped down onto a tick.

    Clamped at one tick above zero — a wide offset on a two-cent stock would
    otherwise price the order at or below nothing, which TWS rejects.
    """
    bid_micros = to_micros(bid)
    raw = bid_micros - offset_micros(bid_micros, offset_cents=offset_cents, offset_bps=offset_bps)
    tick = tick_micros(raw)
    return to_price(max(tick, (raw // tick) * tick))


def shares_for_dollars(dollars: float, ask: float) -> int:
    """How many whole shares ``dollars`` buys at ``ask``.

    Sized on the ask, the price expected to be paid. Integer division, so an
    exactly-divisible amount cannot come out a share short (``0.3 / 0.1`` is
    2.9999999999999996 in floating point). Zero is an ordinary answer; the
    caller disables the button rather than sending an empty order.
    """
    ask_micros = to_micros(ask)
    dollar_micros = to_micros(dollars)
    if ask_micros <= 0 or dollar_micros <= 0:
        return 0
    return dollar_micros // ask_micros


def shares_for_fraction(position: int, fraction: float) -> int:
    """How many whole shares ``fraction`` of a long position comes to.

    A whole-position exit returns the position exactly rather than a proportion
    of it, so no arithmetic can leave a share behind. Long only: a position of
    zero or less sells nothing, and the result is clamped to the position, so no
    fraction can open a short.
    """
    if position <= 0 or fraction <= 0:
        return 0
    if fraction >= 1.0:
        return position
    return min(position, position * round(fraction * BPS) // BPS)


@dataclass(frozen=True, slots=True)
class OrderPlan:
    """What an order would be, before anything is sent.

    ``blocked`` is a short machine-readable reason, or None when sendable — the
    panel shows it on the disabled button, and the service refuses a plan that
    carries one.
    """

    side: str  # "BUY" | "SELL"
    symbol: str
    shares: int
    limit: float
    notional: float
    blocked: str | None = None

    @property
    def ok(self) -> bool:
        return self.blocked is None and self.shares > 0

    def to_wire(self) -> dict:
        return {
            "side": self.side,
            "symbol": self.symbol,
            "shares": self.shares,
            "limit": self.limit,
            "notional": round(self.notional, 2),
            "blocked": self.blocked,
        }


def _quote_ok(bid: float, ask: float) -> bool:
    return bid > 0 and ask > 0 and ask >= bid


def plan_buy(
    *,
    symbol: str,
    dollars: float,
    bid: float,
    ask: float,
    offset_cents: float,
    offset_bps: float,
    max_order_dollars: float,
) -> OrderPlan:
    """Everything a buy would be, or the reason it cannot happen.

    The notional is measured at the *limit*, not the ask: the limit is the most
    this order can spend, and the cap bounds the worst case.
    """
    if not _quote_ok(bid, ask):
        return OrderPlan("BUY", symbol, 0, 0.0, 0.0, blocked="no_quote")

    limit = buy_limit(ask, offset_cents=offset_cents, offset_bps=offset_bps)
    shares = shares_for_dollars(dollars, ask)
    if shares <= 0:
        return OrderPlan("BUY", symbol, 0, limit, 0.0, blocked="too_small")

    notional = to_price(shares * to_micros(limit))
    if to_micros(notional) > to_micros(max_order_dollars):
        return OrderPlan("BUY", symbol, shares, limit, notional, blocked="over_cap")
    return OrderPlan("BUY", symbol, shares, limit, notional)


def plan_sell(
    *,
    symbol: str,
    fraction: float,
    position: int,
    bid: float,
    ask: float,
    offset_cents: float,
    offset_bps: float,
) -> OrderPlan:
    """Everything a sell would be, or the reason it cannot happen.

    Long only, enforced here rather than by a disabled button: the quantity is
    clamped to the position by ``shares_for_fraction``, so a sell can never open
    a short.

    No cap check — the cap bounds what may be *bought*.
    """
    if position <= 0:
        return OrderPlan("SELL", symbol, 0, 0.0, 0.0, blocked="no_position")
    if not _quote_ok(bid, ask):
        return OrderPlan("SELL", symbol, 0, 0.0, 0.0, blocked="no_quote")

    limit = sell_limit(bid, offset_cents=offset_cents, offset_bps=offset_bps)
    shares = shares_for_fraction(position, fraction)
    if shares <= 0:
        return OrderPlan("SELL", symbol, 0, limit, 0.0, blocked="too_small")
    return OrderPlan("SELL", symbol, shares, limit, to_price(shares * to_micros(limit)))
