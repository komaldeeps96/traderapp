"""The last N prints per symbol, classified against the book.

Sits beside ``MarketDataService`` on the same trade stream and does none of
its work: no bars, no indicators, no history. A print is stamped with a
sequence number, placed against the newest quote and pushed onto a ring
buffer, and the broadcaster ships whatever is new on its own cadence — the
same coalescing every other stream on this socket gets, for the same reason.
A runner printing three hundred times a minute would otherwise be three
hundred WebSocket frames a minute, per client.

Two bounds, both deliberate:

- **The buffer is a deque with a maxlen.** A tape is read from the top; a
  print that has scrolled a thousand rows off the bottom is not going to be
  read, and holding it costs memory during exactly the session where memory
  matters.
- **Symbols are evicted least-recently-printed.** Nothing tells this service
  that a chart was closed — the hub releases *bars* when the last client
  leaves, and wiring a second unload path through it to save a few hundred
  kilobytes is not worth the coupling. Flipping between a dozen runners is
  the whole workflow, so the cap is set above that and the thirteenth name
  evicts the oldest.

Unlike the chart, this fills from the very first print: there is no history to
load, so a symbol switch has a live tape before it has candles.
"""

from __future__ import annotations

from collections import deque

from ..domain.tape import Print, classify
from ..market.bar_builder import Trade
from .quotes import QuoteService

#: Rows kept per symbol. Deep enough to scroll back through a halt-resume
#: burst, which is where a trader actually goes looking backwards.
DEFAULT_BUFFER = 600

#: How many symbols keep a tape at once. Above a day's worth of flipping.
DEFAULT_MAX_SYMBOLS = 16


class TapeService:
    def __init__(
        self,
        quotes: QuoteService,
        *,
        buffer: int = DEFAULT_BUFFER,
        max_symbols: int = DEFAULT_MAX_SYMBOLS,
    ):
        self._quotes = quotes
        self._buffer = buffer
        self._max_symbols = max_symbols
        # Insertion-ordered, and re-inserted on every print, so the first key
        # is always the least recently active symbol.
        self._prints: dict[str, deque[Print]] = {}
        self._seq: dict[str, int] = {}

    async def handle_trade(self, symbol: str, trade: Trade) -> None:
        """Record one print. Registered on the router, like the bar builders."""
        if not symbol or trade.price <= 0 or trade.size <= 0:
            return

        rows = self._prints.get(symbol)
        if rows is None:
            rows = deque(maxlen=self._buffer)
            self._evict()
        else:
            # Touch: move to the back of the eviction order.
            del self._prints[symbol]
        self._prints[symbol] = rows

        seq = self._seq.get(symbol, 0) + 1
        self._seq[symbol] = seq
        rows.append(
            Print(
                seq=seq,
                time=trade.time,
                price=trade.price,
                size=trade.size,
                side=classify(trade.price, self._quotes.get(symbol)),
                exchange=trade.exchange,
                conditions=trade.conditions,
                price_forming=trade.price_forming,
            )
        )

    def _evict(self) -> None:
        while len(self._prints) >= self._max_symbols:
            oldest = next(iter(self._prints))
            self._prints.pop(oldest, None)
            # The counter goes with the buffer: a symbol coming back has no
            # rows on any client either, and both sides restart from zero on
            # the ``reset`` frame its next subscribe sends.
            self._seq.pop(oldest, None)

    def recent(self, symbol: str) -> list[Print]:
        """The whole buffer, oldest first — a newly subscribed client's backlog."""
        return list(self._prints.get(symbol, ()))

    def since(self, symbol: str, seq: int) -> list[Print]:
        """Prints newer than ``seq``, oldest first.

        Walked from the back and stopped early: on a fast tape this runs every
        broadcast tick against a buffer of hundreds, and all but the last
        handful are already sent.
        """
        rows = self._prints.get(symbol)
        if not rows:
            return []
        fresh: list[Print] = []
        for row in reversed(rows):
            if row.seq <= seq:
                break
            fresh.append(row)
        fresh.reverse()
        return fresh

    def revision(self, symbol: str) -> int:
        """The newest sequence number, or 0 when nothing has printed."""
        return self._seq.get(symbol, 0)

    def drop(self, symbol: str) -> None:
        self._prints.pop(symbol, None)
        self._seq.pop(symbol, None)
