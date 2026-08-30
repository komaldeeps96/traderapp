"""Builds and wires the application's services.

Constructing everything in one place — and letting a caller pass in their own
``Settings`` — is what lets the integration tests spin up a complete, real
application against stubbed HTTP instead of reaching for module-level globals.
"""

from __future__ import annotations

import functools
import logging

from ..core.settings import Settings, get_settings
from ..domain.protocol import (
    DataSource,
    api_usage_message,
    filing_message,
    news_message,
    regime_message,
    scanner_message,
    status_message,
)
from ..domain.scanner import SCANNER_TIERS
from ..indicators.engine import IndicatorEngine
from ..indicators.spec import load_indicator_specs
from ..market.store import BarStore
from ..providers.alpaca import AlpacaProvider
from ..providers.edgar import EdgarProvider
from ..providers.ibkr import IBKRProvider
from ..providers.router import FeedRouter
from ..providers.yahoo import YahooFloatProvider
from ..services.api_budget import ApiBudget
from ..services.broadcaster import ChartBroadcaster
from ..services.corporate_actions import ReverseSplitService
from ..services.filing_watch import FilingWatchService
from ..services.fx import FxService
from ..services.halts import HaltTracker
from ..services.hub import SubscriptionHub
from ..services.market_data import MarketDataService
from ..services.news import NewsService
from ..services.ownership import OwnershipService
from ..services.peers import PeerService
from ..services.quotes import QuoteService
from ..services.regime import RegimeService
from ..services.scanner import ScannerService
from ..services.state import StateStore
from ..services.swing import SwingService
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
        self.halts = HaltTracker()
        self.router.on_halt(self._on_halt)
        self.splits = ReverseSplitService(self.alpaca.fetch_reverse_splits)
        self.yahoo = YahooFloatProvider()
        # EDGAR is the fundamentals source, because IBKR is not one on this
        # account — every reqFundamentalData report answers error 10358.
        self.edgar = (
            EdgarProvider(self.api_budget.edgar, user_agent=self.settings.edgar.user_agent)
            if self.settings.edgar.enabled
            else None
        )
        self.symbol_info = SymbolInfoService(
            self.store,
            self.tv,
            borrow=self.router.borrow_status,
            halts=self.halts.status,
            splits=self.splits,
            yahoo=self.yahoo,
            edgar=self.edgar,
        )
        # IBKR is the news provider — the one research feed this account is
        # entitled to, while every fundamentals request answers error 10358.
        self.news = NewsService(self.ibkr if self.settings.ibkr.enabled else None)
        self.ibkr.on_news(self._on_news)

        # A 424B5 landing while a runner is open is the surprise this whole
        # feature exists to remove. One request a minute against SEC's
        # ten-a-second allowance.
        self.filing_watch = FilingWatchService(
            self.edgar, self.settings.edgar.filing_poll_seconds
        )
        self.filing_watch.on_alert(self._on_filing)

        self.hub = SubscriptionHub(self.router, self.market_data)
        self.broadcaster = ChartBroadcaster(
            self.hub, self.market_data, self.quotes, self.symbol_info, self.api_budget
        )
        # One ScannerService per market-cap tier, sharing this one IBKR
        # connection. Each carries its own IBKR subscription, filters and
        # persisted state — see ScannerService's docstring.
        self.scanners: dict[str, ScannerService] = {
            str(tier["id"]): ScannerService(self.ibkr, str(tier["id"]), self.settings.scanner, self.tv)
            for tier in SCANNER_TIERS
        }
        self.regime = RegimeService(self.tv, self.settings.regime)
        # Answers from TradingView alone, so the swing screens still work
        # with no TWS running — which is most of the time outside a session.
        self.swing = SwingService()
        self.ownership = OwnershipService(self.edgar)
        self.peers = PeerService(self.tv)
        # Shared so a rate is fetched once per period, not once per tab.
        self.fx = FxService(cache_path=self.settings.fx_cache_file)
        self.state = StateStore(
            self.settings.state_file,
            self.settings.default_symbol,
            self.settings.default_timeframe,
        )
        # Filters dialled in last session beat the YAML defaults: the state
        # file is only ever written by the terminal itself, and adopt_config
        # validates it, so this cannot make a scanner unstartable.
        for scanner_id, scanner in self.scanners.items():
            saved_scanner = self.state.scanner_config(scanner_id)
            if saved_scanner is not None:
                scanner.adopt_config(saved_scanner)
            scanner.on_update(functools.partial(self._broadcast_scanner, scanner_id))

        self.swing.adopt_config(self.state.swing_config())

        self.regime.on_update(self._broadcast_regime)
        self.router.on_status_change(self._on_source_change)
        self.market_data.on_backfill(self._on_backfill)

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        await self.market_data.start()
        await self.router.start()
        await self.broadcaster.start()
        for scanner in self.scanners.values():
            await scanner.start()
        await self.regime.start()
        await self.filing_watch.start()
        logger.info(
            "Ready — data source: %s%s",
            self.router.active_source.value,
            " (delayed)" if self.router.is_delayed else "",
        )

    async def stop(self) -> None:
        await self.broadcaster.stop()
        for scanner in self.scanners.values():
            await scanner.stop()
        await self.regime.stop()
        await self.filing_watch.stop()
        await self.router.stop()
        await self.yahoo.close()
        if self.edgar is not None:
            await self.edgar.close()
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

    def scanner_payload(self, scanner_id: str) -> dict:
        scanner = self.scanners[scanner_id]
        state = scanner.state
        return scanner_message(
            scanner_id=scanner_id,
            label=scanner.label,
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

    async def _broadcast_scanner(self, scanner_id: str, _state) -> None:
        self.hub.broadcast(self.scanner_payload(scanner_id))

    async def _broadcast_regime(self, _state) -> None:
        self.hub.broadcast(self.regime_payload())

    async def _on_source_change(self) -> None:
        """A provider connected or dropped: tell clients and re-check scanning."""
        self.hub.broadcast(self.status_payload())
        for scanner in self.scanners.values():
            await scanner.refresh_availability()
        # The real-time source arriving means anything loaded from the
        # delayed fallback ends ~15 minutes short of the live stream. Repair
        # every loaded symbol's recent slice so no chart keeps that seam.
        if self.router.active_source is DataSource.IBKR:
            for symbol in self.market_data.loaded_symbols:
                self.market_data.schedule_recent_repair(symbol)

    async def _on_news(self, symbol: str, row: dict) -> None:
        """A live headline: fold it in and push it, if it is genuinely new.

        ``add_live`` returns ``None`` when the headline collapsed into a story
        already on screen — the starred bulletin that precedes a press release
        by seconds — so the panel does not flash the same story twice.
        """
        headline = self.news.add_live(symbol, row)
        if headline is not None:
            self.hub.broadcast(news_message(symbol, headline.to_dict()))

    async def _on_filing(self, symbol: str, filing) -> None:
        self.hub.broadcast(filing_message(symbol, filing.to_dict()))

    async def _on_halt(self, symbol: str, halted: bool) -> None:
        self.halts.mark(symbol, halted)
        # A halt changes the info strip now, not at the next trade — and a
        # halted tape prints no trades, so without this touch the strip
        # would only learn about the halt at the resume.
        self.market_data.touch(symbol)

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
