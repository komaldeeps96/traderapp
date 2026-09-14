"""Builds and wires the application's services.

Constructing everything in one place, and letting a caller pass its own
``Settings``, is what lets the integration tests spin up a complete real
application against stubbed HTTP rather than module-level globals.
"""

from __future__ import annotations

import functools
import logging

from ..core.settings import Settings, get_settings
from ..domain.protocol import DataSource
from ..domain.scanner import SCANNER_TIERS
from ..indicators.engine import IndicatorEngine
from ..indicators.spec import load_indicator_specs
from ..market.store import BarStore
from ..providers.alpaca import AlpacaProvider
from ..providers.alpaca_news import AlpacaNewsStream
from ..providers.edgar import EdgarProvider
from ..providers.ibkr import IBKRProvider
from ..providers.ibkr_broker import IBKRBroker
from ..providers.router import FeedRouter
from ..providers.yahoo import YahooFloatProvider
from ..services.api_budget import ApiBudget
from ..services.broadcaster import ChartBroadcaster
from ..services.corporate_actions import ReverseSplitService
from ..services.fanout import FanOut
from ..services.filing_watch import FilingWatchService
from ..services.fx import FxService
from ..services.halts import HaltTracker
from ..services.hub import SubscriptionHub
from ..services.market_data import MarketDataService
from ..services.news import NewsService
from ..services.news_ai import NewsAIService
from ..services.ownership import OwnershipService
from ..services.peers import PeerService
from ..services.quotes import QuoteService
from ..services.regime import RegimeService
from ..services.scanner import ScannerService
from ..services.state import StateStore
from ..services.swing import SwingService
from ..services.symbol_info import SymbolInfoService
from ..services.trading import TradingService
from ..services.tv import TVDataService
from ..services.watchlist import WatchlistService

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
        # Order entry, on its own TWS connection and its own client id — see
        # providers/ibkr_broker.py for why it is not the data client. Off
        # unless settings.trading.enabled says otherwise, which it does not by
        # default and does not in any test.
        self.broker = IBKRBroker(self.settings.trading)
        self.trading = TradingService(
            self.broker,
            self.quotes,
            self.settings.trading,
            feed_delayed=lambda: self.router.is_delayed,
            feed_live=lambda: self.router.active_source is not DataSource.NONE,
            halted=lambda symbol: self.halts.status(symbol).halted,
        )

        self.tv = TVDataService()
        self.halts = HaltTracker()
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
        # Two news sources, each optional. IBKR carries the entitled feeds;
        # Alpaca carries Benzinga, which answers with no TWS running and covers
        # the micro caps IBKR's feeds miss.
        self.news = NewsService(
            self.ibkr if self.settings.ibkr.enabled else None,
            self.alpaca if self.settings.alpaca.enabled else None,
        )
        # The whole market's headlines, live. IBKR's ride generic tick 292 and
        # follow only the open chart; this reaches a watchlist name while it is
        # nowhere on screen, and it answers with no TWS running.
        self.alpaca_news = AlpacaNewsStream(self.settings.alpaca)
        # A 424B5 landing while a runner is open is the surprise this whole
        # feature exists to remove. One request a minute against SEC's
        # ten-a-second allowance.
        self.filing_watch = FilingWatchService(
            self.edgar, self.settings.edgar.filing_poll_seconds
        )

        self.hub = SubscriptionHub(self.router, self.market_data)
        # A quote outliving its chart would size an order off a book hours old.
        self.hub.on_release(self.quotes.drop)
        self.broadcaster = ChartBroadcaster(
            self.hub,
            self.market_data,
            self.quotes,
            self.symbol_info,
            self.api_budget,
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

        self.swing.adopt_config(self.state.swing_config())
        self.watchlist = WatchlistService(
            self.state, quotes_enabled=self.settings.regime.enabled
        )

        self.fanout = FanOut(
            hub=self.hub,
            router=self.router,
            market_data=self.market_data,
            news=self.news,
            watchlist=self.watchlist,
            halts=self.halts,
            scanners=self.scanners,
            regime=self.regime,
            trading=self.trading,
            api_budget=self.api_budget,
        )
        self._wire_events()
        self._wire_readers()

    def _wire_events(self) -> None:
        """Every service event, to the frames it becomes. See ``fanout.py``."""
        fanout = self.fanout
        self.broker.on_position(fanout.trading_changed)
        self.broker.on_status_change(fanout.trading_changed)
        self.broker.on_order(fanout.order_changed)
        self.router.on_halt(fanout.halt)
        self.router.on_status_change(fanout.source_changed)
        self.ibkr.on_news(fanout.ibkr_headline)
        self.alpaca_news.on_headline(fanout.live_headline)
        self.filing_watch.on_alert(fanout.filing)
        for scanner_id, scanner in self.scanners.items():
            scanner.on_update(functools.partial(fanout.scanner_changed, scanner_id))
        self.regime.on_update(fanout.regime_changed)
        self.market_data.on_backfill(fanout.backfill)

    def _wire_readers(self) -> None:
        """The panel that asks Claude to read something.

        It consumes a service built above rather than a source of its own: the
        reader sees the news cache and nothing else, which keeps its answer a
        read of the headlines rather than of the screen.
        """
        self.news_ai = NewsAIService(self.settings.news_ai, self.news)

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        await self.market_data.start()
        await self.router.start()
        await self.broadcaster.start()
        for scanner in self.scanners.values():
            await scanner.start()
        await self.regime.start()
        await self.filing_watch.start()
        await self.alpaca_news.start()
        await self.broker.start()
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
        await self.alpaca_news.stop()
        await self.news_ai.stop()
        await self.broker.stop()
        await self.router.stop()
        await self.yahoo.close()
        await self.fx.close()
        if self.edgar is not None:
            await self.edgar.close()
        # Last: the router is quiet by now, so nothing can schedule a new load
        # while this is collecting the outstanding ones.
        await self.market_data.stop()


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
