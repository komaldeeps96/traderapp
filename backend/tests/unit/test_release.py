"""What letting go of a symbol lets go of.

A quote kept after its chart closed would size an order off a book hours old;
a load finished for a chart nobody has open marks the symbol loaded and starts
a backfill that spends IBKR history requests on it.
"""

from __future__ import annotations

import asyncio

import pytest

from app.domain.quotes import Quote
from app.domain.timeframes import Timeframe
from app.services.quotes import QuoteService
from tests.unit.test_hub import connect, make_hub


async def test_a_symbol_nobody_watches_drops_its_quote():
    hub, _ = make_hub()
    quotes = QuoteService()
    hub.on_release(quotes.drop)
    connection = await connect(hub)
    await hub.subscribe(connection, "RUN", Timeframe.M1)
    await quotes.handle_quote("RUN", Quote(bid=1.0, ask=1.01, bid_size=1, ask_size=1, time=0))

    await hub.unsubscribe(connection)
    assert quotes.get("RUN") is None
    await hub.unregister(connection)


async def test_a_symbol_still_watched_keeps_its_quote():
    hub, _ = make_hub()
    quotes = QuoteService()
    hub.on_release(quotes.drop)
    first, second = await connect(hub), await connect(hub)
    await hub.subscribe(first, "RUN", Timeframe.M1)
    await hub.subscribe(second, "RUN", Timeframe.M1)
    await quotes.handle_quote("RUN", Quote(bid=1.0, ask=1.01, bid_size=1, ask_size=1, time=0))

    await hub.unsubscribe(first)
    assert quotes.get("RUN") is not None
    for connection in (first, second):
        await hub.unregister(connection)


async def test_a_load_nobody_waits_for_is_cancelled_not_finished(monkeypatch):
    hub, market = make_hub()
    started, gate = asyncio.Event(), asyncio.Event()
    fetch = market._router.fetch_history

    async def slow(*args, **kwargs):
        started.set()
        await gate.wait()
        return await fetch(*args, **kwargs)

    monkeypatch.setattr(market._router, "fetch_history", slow)
    connection = await connect(hub)
    subscribing = asyncio.create_task(hub.subscribe(connection, "RUN", Timeframe.M1))
    await asyncio.wait_for(started.wait(), timeout=5)

    await hub.unsubscribe(connection)
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await subscribing

    assert "RUN" not in market.loaded_symbols
    assert "RUN" not in market._backfills
    await hub.unregister(connection)
