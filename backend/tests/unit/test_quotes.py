"""Latest-quote cache and its wire shape."""

from __future__ import annotations

import pytest

from app.domain.protocol import quote_message
from app.domain.quotes import Quote
from app.services.quotes import QuoteService


def quote(bid: float = 5.00, ask: float = 5.05) -> Quote:
    return Quote(bid=bid, ask=ask, bid_size=300, ask_size=1200, time=1_700_000_000.4)


class TestQuoteService:
    async def test_keeps_the_newest_quote(self):
        service = QuoteService()
        await service.handle_quote("RUN", quote(5.00, 5.05))
        await service.handle_quote("RUN", quote(5.10, 5.16))
        assert service.get("RUN").bid == pytest.approx(5.10)
        assert service.revision("RUN") == 2

    async def test_rejects_a_crossed_or_empty_quote(self):
        service = QuoteService()
        await service.handle_quote("RUN", Quote(bid=0, ask=5, bid_size=0, ask_size=0, time=0))
        await service.handle_quote("RUN", Quote(bid=6, ask=5, bid_size=1, ask_size=1, time=0))
        assert service.get("RUN") is None
        assert service.revision("RUN") == 0

    async def test_drop_forgets_the_symbol(self):
        service = QuoteService()
        await service.handle_quote("RUN", quote())
        service.drop("RUN")
        assert service.get("RUN") is None


class TestWireShape:
    def test_message_carries_both_sides_with_sizes(self):
        message = quote_message("RUN", quote(4.9971, 5.0523))
        assert message["type"] == "quote"
        assert message["symbol"] == "RUN"
        assert message["bid"] == pytest.approx(4.9971)
        assert message["ask"] == pytest.approx(5.0523)
        assert message["bs"] == 300
        assert message["as"] == 1200
        assert message["t"] == 1_700_000_000
