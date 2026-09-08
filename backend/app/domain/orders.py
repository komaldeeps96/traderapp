"""Order arithmetic: dollars to shares, quote to limit price.

Pure functions, no IO, because this is the layer where a mistake spends real
money and the only way to be sure of it is to be able to test every case
cheaply. The same arithmetic exists in ``frontend/src/lib/orders.ts`` for the
button previews, and both are asserted against the one case table in
``frontend/src/lib/order-cases.json`` so they cannot drift.

**EVERYTHING HERE IS INTEGER ARITHMETIC IN MILLIONTHS OF A DOLLAR.**

Not a style choice, and not premature. Written in floats, ``0.98 - 0.05``
is 0.9299999999999999, and the flooring step that snaps a sell onto its tick
turned that into a limit of **0.9299** — an order priced a hundredth of a
penny below where it was meant to be, arrived at silently. Rounding the
intermediate away does not fix it either: the error sits at the twelfth
significant figure, so an absolute tolerance that covers it at $0.93 does not
cover it at $93.

A micro-dollar is exact for every price a US equity can quote (Rule 612's
finest grid is a hundredth of a penny, which is 100 of them), and a million
dollars is 1e12 — comfortably inside the 2^53 both Python ints and JavaScript
doubles represent exactly. So the same integer expressions run in both
languages and give bit-identical answers, which is what makes one shared case
table meaningful.

Three rules run through all of it:

**Whole shares, always floored.** Never rounded, in either direction. Three
and a half shares is three, on the way in and on the way out. Rounding up a
buy overspends the button; rounding up a sell would sell stock that is not
there.

**The offset is a cap, not a price.** A limit order fills at the best
available price, so a buy priced five cents through the offer still fills at
the offer when there is size there. The slack is only spent when the book
moves between the click and the arrival — which is the case this exists for.

**Tick rounding goes in the marketable direction.** A limit price has to land
on a valid tick or TWS rejects it, and rounding to *nearest* could push a
marketable order back inside the spread — turning an order meant to fill now
into one that rests. Buys round up, sells round down, always.
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

    Read off the *order's own price*, not off the quote it came from. A sell
    priced down through the dollar mark — bid 1.02, limit 0.97 — is an order
    priced under a dollar, so Rule 612 gives it the finer grid; snapping it
    onto the penny the bid happened to sit on would throw that away.
    """
    return TICK_ABOVE_DOLLAR if price_micros >= SUB_DOLLAR_THRESHOLD else TICK_BELOW_DOLLAR


def offset_micros(price_micros: int, *, offset_cents: float, offset_bps: float) -> int:
    """How far through the book to price, in micros.

    The larger of a flat cent figure and a proportionate one. Five cents is
    12 bps on a $40 name and 12.5% on a $0.40 name, so neither part is the
    right shape on its own: the cents are a floor that keeps a cheap name's
    slack usable, and the basis points keep an expensive one's proportionate.
    At 5c and 15bps the two cross at $33.33.
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

    Clamped at one tick above zero. A wide offset on a two-cent stock would
    otherwise price the order at or below nothing, which TWS rejects — and an
    exit that will not leave the building is the one failure this side cannot
    afford.
    """
    bid_micros = to_micros(bid)
    raw = bid_micros - offset_micros(bid_micros, offset_cents=offset_cents, offset_bps=offset_bps)
    tick = tick_micros(raw)
    return to_price(max(tick, (raw // tick) * tick))


def shares_for_dollars(dollars: float, ask: float) -> int:
    """How many whole shares ``dollars`` buys at ``ask``.

    Sized on the ask — the price expected to be paid — rather than on the
    last trade or on the limit price. It is what makes the button's own label
    the number a person would compute, and the offset above it is protection
    that usually goes unused.

    Integer division, so an exactly-divisible amount cannot come out one
    share short: ``0.3 / 0.1`` is 2.9999999999999996 in floating point, and
    that floors to two.

    Zero is an ordinary answer, not an error: a $10 button is dead on
    anything over $10 a share. The caller disables the button rather than
    sending an empty order.
    """
    ask_micros = to_micros(ask)
    dollar_micros = to_micros(dollars)
    if ask_micros <= 0 or dollar_micros <= 0:
        return 0
    return dollar_micros // ask_micros


def shares_for_fraction(position: int, fraction: float) -> int:
    """How many whole shares ``fraction`` of a long position comes to.

    A whole-position exit returns the position exactly rather than a
    proportion of it, so no arithmetic can leave a share behind on the one
    order whose entire purpose is to leave nothing behind.

    Long only: a position of zero or less sells nothing, and the result is
    clamped to the position, so no fraction can ever open a short.
    """
    if position <= 0 or fraction <= 0:
        return 0
    if fraction >= 1.0:
        return position
    return min(position, position * round(fraction * BPS) // BPS)


@dataclass(frozen=True, slots=True)
class OrderPlan:
    """What an order would be, before anything is sent.

    ``blocked`` is a short machine-readable reason, or None when the plan is
    sendable — the panel shows it on the disabled button, and the service
    refuses to place a plan that carries one.
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

    The notional is measured at the *limit*, not at the ask, because the limit
    is the most this order can possibly spend and the cap exists to bound the
    worst case rather than the expected one.
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

    Long only, and enforced here rather than by a disabled button: the
    quantity is clamped to the position by ``shares_for_fraction``, so a sell
    can never exceed what is held and therefore can never open a short.

    No cap check. The cap bounds what may be *bought*; refusing to let a
    position out because it has grown past the cap would be the wrong kind of
    safety.
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
