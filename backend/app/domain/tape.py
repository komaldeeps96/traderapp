"""Time and sales: one row per print, and which side of the book took it.

A chart is a summary; the tape is the thing itself. On a small-cap runner the
question that decides an entry — is somebody lifting offers, or is this a
stack of prints hitting the bid on the way down — is answered here a beat
before it shows up as a candle.

**Nobody publishes the aggressor.** Neither the SIP feeds nor IBKR's
tick-by-tick stream say whether a print was a buy or a sell; the tape carries
price, size, venue and sale conditions and nothing else. Every terminal that
shows green and red rows is doing what this module does — comparing the print
against the top of book that was standing when it arrived:

    above the ask   a sweep: somebody paid through the offer
    at the ask      a buyer lifted the offer
    inside          neither side gave way — dark pool, midpoint, price improved
    at the bid      a seller hit the bid
    below the bid   a sweep the other way

That comparison inherits one honest weakness. Our quote is the newest one to
have *arrived*, not the one that was standing at the print's own timestamp, so
a print that overtakes its own quote update is classified against the book a
few milliseconds late. It is the same weakness every platform has, it moves a
row by one shade rather than from green to red, and the alternative — holding
a quote history and binding each print to it — costs more than the answer is
worth on a window nobody reads a single row of.

Sizes and conditions are carried through untouched so the window can filter on
them. What *is* missing is stated in ``docs/time-and-sales.md``: odd lots never
reach here, because IBKR's ``Last`` stream does not carry them and the app's
bars are built to match that.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .quotes import Quote

# Prices arrive as decimals that round-trip exactly through a double, so this
# only has to absorb representation error — it is not a "near the ask" band.
# A print one cent through the offer is a sweep and has to read as one.
_EPSILON = 1e-9


class Aggressor(str, Enum):
    """Which side crossed the spread, inferred from the standing quote."""

    ABOVE_ASK = "above"
    ASK = "ask"
    MID = "mid"
    BID = "bid"
    BELOW_BID = "below"
    #: No quote had arrived yet, or the book was crossed/empty when it did.
    UNKNOWN = "unk"


def classify(price: float, quote: Quote | None) -> Aggressor:
    """Place a print against the top of book that was standing for it."""
    if quote is None or not quote.is_valid:
        return Aggressor.UNKNOWN
    if price > quote.ask + _EPSILON:
        return Aggressor.ABOVE_ASK
    if price >= quote.ask - _EPSILON:
        return Aggressor.ASK
    if price < quote.bid - _EPSILON:
        return Aggressor.BELOW_BID
    if price <= quote.bid + _EPSILON:
        return Aggressor.BID
    return Aggressor.MID


@dataclass(slots=True)
class Print:
    """One row of the tape.

    ``seq`` is per symbol and strictly increasing, which is what lets the
    client drop the overlap between its opening backlog and the first
    incremental batch without comparing timestamps — two prints in the same
    millisecond are ordinary.
    """

    seq: int
    #: UTC epoch seconds, fractional. The wire carries milliseconds.
    time: float
    price: float
    size: float
    side: Aggressor
    #: Whatever the source calls the venue: a single CTA/UTP character from
    #: Alpaca, a name like "NASDAQ" from IBKR. Passed through, never mapped —
    #: inventing a lookup table would be inventing data.
    exchange: str = ""
    conditions: tuple[str, ...] = ()
    #: False for late reports, average-price blocks and the rest: real volume
    #: at a price that is not a market price now. They stay on the tape, and
    #: the window can filter them out — see market/conditions.py.
    price_forming: bool = True

    def to_wire(self) -> dict:
        wire: dict = {
            "q": self.seq,
            # Milliseconds, unlike every other time on this wire. A tape at
            # second resolution loses the ordering inside a burst, which is
            # the part being read.
            "t": int(self.time * 1000),
            "p": round(self.price, 6),
            "s": self.size,
            "a": self.side.value,
        }
        # Omitted rather than sent empty: on a busy name this message is the
        # chattiest on the socket, and most prints carry no conditions.
        if self.exchange:
            wire["x"] = self.exchange
        if self.conditions:
            wire["c"] = list(self.conditions)
        if not self.price_forming:
            wire["f"] = 0
        return wire
