"""Latest top-of-book quote per symbol.

Quotes arrive far faster than a readout can usefully change — hundreds per
second on a runner — so nothing is pushed per quote. The newest one is kept
here and the broadcaster sends it on its own cadence, exactly like bars.
"""

from __future__ import annotations

from ..domain.quotes import Quote


class QuoteService:
    def __init__(self) -> None:
        self._latest: dict[str, Quote] = {}
        self._revisions: dict[str, int] = {}

    async def handle_quote(self, symbol: str, quote: Quote) -> None:
        if not quote.is_valid:
            return
        self._latest[symbol] = quote
        self._revisions[symbol] = self._revisions.get(symbol, 0) + 1

    def get(self, symbol: str) -> Quote | None:
        return self._latest.get(symbol)

    def revision(self, symbol: str) -> int:
        return self._revisions.get(symbol, 0)

    def drop(self, symbol: str) -> None:
        self._latest.pop(symbol, None)
        self._revisions.pop(symbol, None)
