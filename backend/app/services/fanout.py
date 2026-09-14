"""What the server pushes unasked: service events turned into frames.

The payload builders sit here too, because a window that connects is sent the
same frames the broadcasts carry.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from ..domain.news import to_benzinga_row
from ..domain.protocol import (
    DataSource,
    api_usage_message,
    filing_message,
    news_message,
    order_message,
    regime_message,
    scanner_message,
    status_message,
    trading_message,
    watchlist_message,
)

if TYPE_CHECKING:
    from ..core.api_budget import ApiBudget
    from ..providers.router import FeedRouter
    from .halts import HaltTracker
    from .hub import SubscriptionHub
    from .market_data import MarketDataService
    from .news import NewsService
    from .regime import RegimeService
    from .scanner import ScannerService
    from .trading import TradingService
    from .watchlist import WatchlistService


class FanOut:
    def __init__(
        self,
        *,
        hub: SubscriptionHub,
        router: FeedRouter,
        market_data: MarketDataService,
        news: NewsService,
        watchlist: WatchlistService,
        halts: HaltTracker,
        scanners: Mapping[str, ScannerService],
        regime: RegimeService,
        trading: TradingService,
        api_budget: ApiBudget,
    ):
        self._hub = hub
        self._router = router
        self._market_data = market_data
        self._news = news
        self._watchlist = watchlist
        self._halts = halts
        self._scanners = scanners
        self._regime = regime
        self._trading = trading
        self._api_budget = api_budget

    # ── payloads ───────────────────────────────────────────────────────

    def status_payload(self) -> dict:
        router = self._router
        return status_message(
            source=router.active_source,
            delayed=router.is_delayed,
            ibkr_connected=router.ibkr_connected,
            alpaca_available=router.alpaca_available,
            message=router.status_note(),
        )

    def scanner_payload(self, scanner_id: str) -> dict:
        scanner = self._scanners[scanner_id]
        state = scanner.state
        return scanner_message(
            scanner_id=scanner_id,
            label=scanner.label,
            rows=[row.to_dict() for row in state.rows],
            config=state.config.to_dict(),
            running=state.running,
        )

    async def watchlist_payload(self) -> dict:
        return watchlist_message(
            symbols=self._watchlist.symbols(),
            rows=await self._watchlist.rows(),
            note=self._watchlist.note,
        )

    def trading_payload(self) -> dict:
        return trading_message(
            state=self._trading.state(),
            positions=self._trading.positions(),
            orders=self._trading.working_orders(),
        )

    def api_payload(self) -> dict:
        return api_usage_message(self._api_budget.snapshot())

    def regime_payload(self) -> dict:
        state = self._regime.state
        return regime_message(
            regime=state.regime.to_dict(),
            running=state.running,
            error=state.error,
        )

    # ── events ─────────────────────────────────────────────────────────

    async def scanner_changed(self, scanner_id: str, _state) -> None:
        self._hub.broadcast(self.scanner_payload(scanner_id))

    async def trading_changed(self) -> None:
        """The whole account picture, every time, like the watchlist: an
        account holds a handful of names, so a diff costs more to reason about
        than the list costs to send."""
        self._hub.broadcast(self.trading_payload())

    async def order_changed(self, order: dict) -> None:
        """The order itself, for the strip's acknowledgement, then the whole
        picture: a fill moves a position and empties a working-order slot."""
        self._hub.broadcast(order_message(order))
        self._hub.broadcast(self.trading_payload())

    async def regime_changed(self, _state) -> None:
        self._hub.broadcast(self.regime_payload())

    async def source_changed(self) -> None:
        """A provider connected or dropped: tell clients and re-check scanning."""
        self._hub.broadcast(self.status_payload())
        for scanner in self._scanners.values():
            await scanner.refresh_availability()
        # The real-time source arriving means anything loaded from the delayed
        # fallback ends ~15 minutes short of the live stream. Repair every
        # loaded symbol's recent slice so no chart keeps that seam.
        if self._router.active_source is DataSource.IBKR:
            for symbol in self._market_data.loaded_symbols:
                self._market_data.schedule_recent_repair(symbol)

    async def ibkr_headline(self, symbol: str, row: dict) -> None:
        """``add_live`` answers ``None`` for a headline that collapsed into a
        story already on screen, so the panel does not flash it twice."""
        headline = self._news.add_live(symbol, row)
        if headline is not None:
            self._hub.broadcast(news_message(symbol, headline.to_dict()))

    def _tracked_symbols(self) -> set[str]:
        """Charts open now, plus the watchlist: the stream carries every
        headline published, and these are the ones this terminal follows."""
        return self._hub.symbols() | set(self._watchlist.symbols())

    async def live_headline(self, entry: dict) -> None:
        """One Benzinga headline off the socket. A story names every company it
        mentions, so it can belong to several open charts at once, or to none."""
        row = to_benzinga_row(entry)
        if row is None:
            return
        named = entry.get("symbols")
        if not isinstance(named, list):
            return
        wanted = {str(s).upper() for s in named if isinstance(s, str)} & self._tracked_symbols()
        if not wanted:
            return
        # The body ships with the headline, so an article opened from this is
        # already paid for.
        self._news.remember_article(row["article_id"], entry.get("content") or "")
        for symbol in sorted(wanted):
            headline = self._news.add_live(symbol, row)
            if headline is not None:
                self._hub.broadcast(news_message(symbol, headline.to_dict()))

    async def filing(self, symbol: str, filing) -> None:
        self._hub.broadcast(filing_message(symbol, filing.to_dict()))

    async def halt(self, symbol: str, halted: bool) -> None:
        self._halts.mark(symbol, halted)
        # A halted tape prints no trades, so without this touch the info strip
        # would only learn about the halt at the resume.
        self._market_data.touch(symbol)

    async def backfill(self, symbol: str) -> None:
        """Background history landed: refresh every chart on the symbol. A
        client treats a repeat snapshot as a silent replacement and keeps its
        viewport, so the chart simply grows more history."""
        for pair_symbol, timeframe in self._hub.pairs():
            if pair_symbol != symbol:
                continue
            snapshot = self._market_data.snapshot(pair_symbol, timeframe)
            if snapshot is not None:
                self._hub.send_to_pair(pair_symbol, timeframe, snapshot)
