"""Tracks who is watching what.

Each connection has its own subscription. The union of those subscriptions
decides which symbols are streamed upstream, and a symbol is dropped from
memory as soon as the last client watching it goes away.

This per-connection model is a deliberate change from broadcasting a single
globally-active symbol to everyone: two browser windows — or two parallel
test workers — can watch different symbols without fighting over one slot.
"""

from __future__ import annotations

import asyncio
import logging

from ..domain.protocol import Snapshot
from ..domain.timeframes import Timeframe
from ..providers.router import FeedRouter
from .connection import ClientConnection
from .market_data import MarketDataService

logger = logging.getLogger(__name__)


class SubscriptionHub:
    def __init__(self, router: FeedRouter, market_data: MarketDataService):
        self._router = router
        self._market = market_data
        self._connections: dict[int, ClientConnection] = {}
        self._lock = asyncio.Lock()

    # ── membership ─────────────────────────────────────────────────────

    async def register(self, connection: ClientConnection) -> None:
        self._connections[connection.id] = connection
        await connection.start()
        logger.info("client %s connected (%d total)", connection.id, len(self._connections))

    async def unregister(self, connection: ClientConnection) -> None:
        self._connections.pop(connection.id, None)
        connection.clear_subscription()
        await connection.close()
        await self._sync()
        logger.info("client %s disconnected (%d left)", connection.id, len(self._connections))

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    # ── subscriptions ──────────────────────────────────────────────────

    async def subscribe(
        self,
        connection: ClientConnection,
        symbol: str,
        timeframe: Timeframe,
        extra_timeframes: tuple[Timeframe, ...] = (),
    ) -> list[Snapshot]:
        """Point a client at a symbol and return its opening snapshots.

        The primary chart's snapshot comes first, followed by one per extra
        timeframe — the mini charts. An empty list means the load produced
        nothing, or the client moved on to a different symbol while the
        history was still downloading.

        An extra's snapshot can legitimately carry no bars: a 10-second load
        has no minute base until the background pass lands. The backfill
        handler re-sends every pair when it does, so the mini fills a beat
        later rather than never.
        """
        connection.symbol = symbol
        connection.timeframe = timeframe
        connection.extra_timeframes = extra_timeframes
        await self._sync()

        loaded = await self._market.ensure_loaded(symbol, timeframe)

        if connection.subscription != (symbol, timeframe):
            logger.debug("client %s moved on before %s finished loading", connection.id, symbol)
            return []
        if not loaded:
            return []

        primary = self._market.snapshot(symbol, timeframe)
        if primary is None:
            return []

        snapshots = [primary]
        for extra in extra_timeframes:
            snapshot = self._market.snapshot(symbol, extra)
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots

    async def unsubscribe(self, connection: ClientConnection) -> None:
        connection.clear_subscription()
        await self._sync()

    # ── routing ────────────────────────────────────────────────────────

    def symbols(self) -> set[str]:
        return {c.symbol for c in self._connections.values() if c.symbol}

    def pairs(self) -> set[tuple[str, Timeframe]]:
        """Every chart being fed, across every client — mini charts included."""
        return {pair for c in self._connections.values() for pair in c.subscriptions}

    async def _sync(self) -> None:
        """Reconcile upstream streaming and memory with live subscriptions."""
        async with self._lock:
            wanted = self.symbols()
            await self._router.set_stream_symbols(wanted)
            for symbol in self._market.loaded_symbols - wanted:
                logger.info("no clients left on %s; releasing it", symbol)
                self._market.unload(symbol)

    # ── delivery ───────────────────────────────────────────────────────

    def broadcast(self, message: dict) -> None:
        for connection in list(self._connections.values()):
            connection.send(message)

    def send_to_pair(self, symbol: str, timeframe: Timeframe, message: dict) -> None:
        for connection in list(self._connections.values()):
            if (symbol, timeframe) in connection.subscriptions:
                connection.send(message)

    def send_to_symbol(self, symbol: str, message: dict) -> None:
        """Deliver to every client on ``symbol`` regardless of timeframe.

        Quotes and symbol info are per-symbol facts; a client watching the
        daily chart still needs the live spread.
        """
        for connection in list(self._connections.values()):
            if connection.symbol == symbol:
                connection.send(message)
