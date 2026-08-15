"""Builds and wires the application's services.

Constructing everything in one place — and letting a caller pass in their own
``Settings`` — is what lets the integration tests spin up a complete, real
application against stubbed HTTP instead of reaching for module-level globals.
"""

from __future__ import annotations

import logging

from ..core.settings import Settings, get_settings
from ..domain.protocol import (
    DataSource,
    api_usage_message,
    regime_message,
    scanner_message,
    status_message,
)
from ..indicators.engine import IndicatorEngine
from ..indicators.spec import load_indicator_specs
from ..market.store import BarStore
from ..providers.alpaca import AlpacaProvider
from ..providers.ibkr import IBKRProvider
from ..providers.router import FeedRouter
from ..services.api_budget import ApiBudget
from ..services.broadcaster import ChartBroadcaster
from ..services.hub import SubscriptionHub
from ..services.market_data import MarketDataService
from ..services.quotes import QuoteService
from ..services.regime import RegimeService
from ..services.scanner import ScannerService
from ..services.state import StateStore
from ..services.symbol_info import SymbolInfoService
from ..services.tv import TVDataService

logger = logging.getLogger(__name__)


class AppContainer:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

        self.specs = load_indicator_specs(self.settings.indicators_file)
        self.engine = IndicatorEngine(self.specs)
        self.store = BarStore(max_bars=self.settings.history.max_bars_in_memory)

        self.api_budget = ApiBudget()
        self.alpaca = AlpacaProvider(self.settings.alpaca, self.api_budget.alpaca)
        self.ibkr = IBKRProvider(self.settings.ibkr, self.settings.scanner, self.api_budget.ibkr)
        self.router = FeedRouter(self.alpaca, self.ibkr, self.settings.history)

        self.market_data = MarketDataService(self.router, self.store, self.engine)
        self.quotes = QuoteService()
        self.router.on_quote(self.quotes.handle_quote)
        self.tv = TVDataService()
        self.symbol_info = SymbolInfoService(self.store, self.tv)
        self.hub = SubscriptionHub(self.router, self.market_data)
        self.broadcaster = ChartBroadcaster(
            self.hub, self.market_data, self.quotes, self.symbol_info, self.api_budget
        )
        self.scanner = ScannerService(self.ibkr, self.settings.scanner, self.tv)
        self.regime = RegimeService(self.tv, self.settings.regime)
        self.state = StateStore(
            self.settings.state_file,
            self.settings.default_symbol,
            self.settings.default_timeframe,
        )

        self.scanner.on_update(self._broadcast_scanner)
        self.regime.on_update(self._broadcast_regime)
        self.router.on_status_change(self._on_source_change)
        self.market_data.on_backfill(self._on_backfill)

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        await self.market_data.start()
        await self.router.start()
        await self.broadcaster.start()
        await self.scanner.start()
        await self.regime.start()
        logger.info(
            "Ready — data source: %s%s",
            self.router.active_source.value,
            " (delayed)" if self.router.is_delayed else "",
        )

    async def stop(self) -> None:
        await self.broadcaster.stop()
        await self.scanner.stop()
        await self.regime.stop()
        await self.router.stop()
        # Last: the router is quiet by now, so nothing can schedule a new load
        # while this is collecting the outstanding ones.
        await self.market_data.stop()

    # ── status fan-out ─────────────────────────────────────────────────

    def status_payload(self) -> dict:
        return status_message(
            source=self.router.active_source,
            delayed=self.router.is_delayed,
            ibkr_connected=self.router.ibkr_connected,
            alpaca_available=self.router.alpaca_available,
            message=self.router.status_note(),
        )

    def scanner_payload(self) -> dict:
        state = self.scanner.state
        return scanner_message(
            rows=[row.to_dict() for row in state.rows],
            config=state.config.to_dict(),
            running=state.running,
        )

    def api_payload(self) -> dict:
        return api_usage_message(self.api_budget.snapshot())

    def regime_payload(self) -> dict:
        state = self.regime.state
        return regime_message(
            regime=state.regime.to_dict(),
            running=state.running,
            error=state.error,
        )

    async def _broadcast_scanner(self, _state) -> None:
        self.hub.broadcast(self.scanner_payload())

    async def _broadcast_regime(self, _state) -> None:
        self.hub.broadcast(self.regime_payload())

    async def _on_source_change(self) -> None:
        """A provider connected or dropped: tell clients and re-check scanning."""
        self.hub.broadcast(self.status_payload())
        await self.scanner.refresh_availability()
        # The real-time source arriving means anything loaded from the
        # delayed fallback ends ~15 minutes short of the live stream. Repair
        # every loaded symbol's recent slice so no chart keeps that seam.
        if self.router.active_source is DataSource.IBKR:
            for symbol in self.market_data.loaded_symbols:
                self.market_data.schedule_recent_repair(symbol)

    async def _on_backfill(self, symbol: str) -> None:
        """Background history landed: refresh every chart on the symbol.

        Clients treat a repeat snapshot as a silent data replacement — the
        viewport stays put — so the chart simply grows more history.
        """
        for pair_symbol, timeframe in self.hub.pairs():
            if pair_symbol != symbol:
                continue
            snapshot = self.market_data.snapshot(pair_symbol, timeframe)
            if snapshot is not None:
                self.hub.send_to_pair(pair_symbol, timeframe, snapshot)


_container: AppContainer | None = None


def get_container() -> AppContainer:
    global _container
    if _container is None:
        _container = AppContainer()
    return _container


def set_container(container: AppContainer | None) -> None:
    """Install a container built for a test, or clear it."""
    global _container
    _container = container
