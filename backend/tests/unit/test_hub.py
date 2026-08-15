"""Who is watching what.

A client holds one primary chart plus any number of extra timeframes on the
same symbol — the mini charts. Two things have to stay true as that set moves:
every chart being fed appears in ``pairs()``, so the broadcaster and the
backfill handler reach it; and a departing client's charts vanish from it, so
``_sync`` can release the symbol. Getting the second wrong leaks a symbol's
history and its upstream subscription for the life of the process.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.settings import HistorySettings
from app.domain.timeframes import Timeframe
from app.indicators.engine import IndicatorEngine
from app.market.store import BarStore
from app.providers.router import FeedRouter
from app.services.broadcaster import ChartBroadcaster
from app.services.connection import ClientConnection
from app.services.hub import SubscriptionHub
from app.services.market_data import MarketDataService
from tests.conftest import make_minute_series, ny_epoch
from tests.unit.test_router_tensec import StubProvider


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


def make_hub() -> tuple[SubscriptionHub, MarketDataService]:
    bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0] * 30)
    router = FeedRouter(
        StubProvider("alpaca", True, bars),  # type: ignore[arg-type]
        StubProvider("ibkr", False),  # type: ignore[arg-type]
        HistorySettings(),
    )
    market = MarketDataService(router, BarStore(), IndicatorEngine([]))
    return SubscriptionHub(router, market), market


@pytest.fixture
async def hub():
    hub, market = make_hub()
    yield hub, market
    for connection in list(hub._connections.values()):  # noqa: SLF001 — teardown
        await hub.unregister(connection)


async def connect(hub: SubscriptionHub) -> ClientConnection:
    connection = ClientConnection(FakeWebSocket())
    await hub.register(connection)
    return connection


MINIS = (Timeframe.M1, Timeframe.M5)


class TestPairs:
    async def test_reports_every_chart_a_client_is_fed(self, hub):
        subscriptions, _ = hub
        connection = await connect(subscriptions)

        await subscriptions.subscribe(connection, "RUN", Timeframe.S10, MINIS)

        assert subscriptions.pairs() == {
            ("RUN", Timeframe.S10),
            ("RUN", Timeframe.M1),
            ("RUN", Timeframe.M5),
        }

    async def test_a_primary_that_repeats_an_extra_counts_once(self, hub):
        subscriptions, _ = hub
        connection = await connect(subscriptions)

        # The command layer strips the primary out of the extras; this proves
        # the hub does not double-count even if one slips through.
        await subscriptions.subscribe(connection, "RUN", Timeframe.M1, MINIS)

        assert subscriptions.pairs() == {("RUN", Timeframe.M1), ("RUN", Timeframe.M5)}

    async def test_the_streamed_symbol_set_is_unchanged_by_extras(self, hub):
        """Extras are the same symbol, so they cost nothing upstream."""
        subscriptions, _ = hub
        connection = await connect(subscriptions)

        await subscriptions.subscribe(connection, "RUN", Timeframe.S10, MINIS)

        assert subscriptions.symbols() == {"RUN"}


class TestDelivery:
    async def test_reaches_a_client_on_an_extra_timeframe(self, hub):
        subscriptions, _ = hub
        connection = await connect(subscriptions)
        await subscriptions.subscribe(connection, "RUN", Timeframe.S10, MINIS)
        connection.websocket.sent.clear()

        subscriptions.send_to_pair("RUN", Timeframe.M5, {"type": "bar"})
        await asyncio.sleep(0)

        assert connection.websocket.sent == ['{"type":"bar"}']

    async def test_does_not_reach_a_timeframe_nobody_asked_for(self, hub):
        subscriptions, _ = hub
        connection = await connect(subscriptions)
        await subscriptions.subscribe(connection, "RUN", Timeframe.S10, MINIS)
        connection.websocket.sent.clear()

        subscriptions.send_to_pair("RUN", Timeframe.H1, {"type": "bar"})
        await asyncio.sleep(0)

        assert connection.websocket.sent == []

    async def test_opening_snapshots_lead_with_the_primary(self, hub):
        subscriptions, _ = hub
        connection = await connect(subscriptions)

        snapshots = await subscriptions.subscribe(connection, "RUN", Timeframe.M1, (Timeframe.M5,))

        assert [snapshot["timeframe"] for snapshot in snapshots] == ["1m", "5m"]


class TestBroadcast:
    """The broadcaster reaches every chart, mini charts included.

    Run against the real `ChartBroadcaster` and the real hub, inside the
    test's own event loop — the connection's queue and its writer task are
    only safe to touch from the loop that owns them.
    """

    async def test_sends_one_update_per_timeframe(self, hub):
        subscriptions, market = hub
        connection = await connect(subscriptions)
        await subscriptions.subscribe(connection, "RUN", Timeframe.M1, (Timeframe.M5,))
        await market.wait_for_backfill("RUN")
        connection.websocket.sent.clear()

        broadcaster = ChartBroadcaster(subscriptions, market)
        assert broadcaster.tick() == 2

        # Let the writer task drain the queue it was just handed.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        timeframes = {
            json.loads(payload)["timeframe"]
            for payload in connection.websocket.sent
            if json.loads(payload)["type"] == "bar"
        }
        assert timeframes == {"1m", "5m"}

    async def test_sends_nothing_when_the_data_has_not_moved(self, hub):
        subscriptions, market = hub
        connection = await connect(subscriptions)
        await subscriptions.subscribe(connection, "RUN", Timeframe.M1, (Timeframe.M5,))
        await market.wait_for_backfill("RUN")

        broadcaster = ChartBroadcaster(subscriptions, market)
        broadcaster.tick()
        assert broadcaster.tick() == 0


class TestRelease:
    async def test_unsubscribing_clears_the_extras_too(self, hub):
        subscriptions, _ = hub
        connection = await connect(subscriptions)
        await subscriptions.subscribe(connection, "RUN", Timeframe.S10, MINIS)

        await subscriptions.unsubscribe(connection)

        assert subscriptions.pairs() == set()

    async def test_clearing_the_primary_takes_the_extras_with_it(self):
        """Where the safety actually comes from.

        `subscriptions` hangs off the primary, so a connection can never be
        left advertising mini pairs for a chart nobody is on — clearing the
        symbol is enough on its own. The stored extras are cleared too so a
        later reuse of the object cannot resurrect them.
        """
        connection = ClientConnection(FakeWebSocket())
        connection.symbol = "RUN"
        connection.timeframe = Timeframe.S10
        connection.extra_timeframes = MINIS

        connection.clear_subscription()

        assert connection.subscriptions == set()
        assert connection.extra_timeframes == ()

    async def test_a_departing_client_releases_the_symbol(self, hub):
        """End to end: disconnecting with minis open still frees the memory.

        The mini pairs must not keep the symbol alive — its twelve hours of
        10-second bars, and its upstream stream — after the only viewer goes.
        """
        subscriptions, market = hub
        connection = await connect(subscriptions)
        await subscriptions.subscribe(connection, "RUN", Timeframe.S10, MINIS)
        await market.wait_for_backfill("RUN")

        await subscriptions.unregister(connection)

        assert subscriptions.pairs() == set()
        assert subscriptions.symbols() == set()
        assert not market.is_loaded("RUN")
