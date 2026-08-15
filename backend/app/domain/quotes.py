"""The top-of-book quote.

Spread is the first thing read on a candidate — a wide spread disqualifies a
trade before the chart is even considered — so the raw bid/ask is streamed to
the client and the derived numbers (spread, spread %) are computed there,
where they can be unit-tested against the display.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Quote:
    """Best bid and offer. ``time`` is the UTC epoch second of the update."""

    bid: float
    ask: float
    bid_size: float
    ask_size: float
    time: float

    @property
    def is_valid(self) -> bool:
        return self.bid > 0 and self.ask > 0 and self.ask >= self.bid

    def to_wire(self) -> dict:
        return {
            "bid": round(self.bid, 6),
            "ask": round(self.ask, 6),
            "bs": self.bid_size,
            "as": self.ask_size,
            "t": int(self.time),
        }
