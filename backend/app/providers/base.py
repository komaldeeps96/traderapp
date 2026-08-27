"""The provider interface.

Both upstreams reduce to the same two capabilities — fetch history, and stream
a set of symbols — so the services above them never branch on which one is
live. Streaming is expressed declaratively: callers hand over the full set of
symbols they want, and the provider works out the diff.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime

from ..domain.bars import Bar
from ..domain.quotes import Quote
from ..domain.timeframes import Timeframe
from ..market.bar_builder import Trade

logger = logging.getLogger(__name__)

TradeHandler = Callable[[str, Trade], Awaitable[None]]
QuoteHandler = Callable[[str, Quote], Awaitable[None]]
BarHandler = Callable[[str, Timeframe, Bar], Awaitable[None]]
StatusHandler = Callable[[], Awaitable[None]]
HaltHandler = Callable[[str, bool], Awaitable[None]]


class ProviderError(RuntimeError):
    """Upstream failed in a way the caller may want to report or fall back on."""


class MarketDataProvider(ABC):
    """Base class for a market data source."""

    name: str = "provider"

    def __init__(self) -> None:
        self._trade_handlers: list[TradeHandler] = []
        self._quote_handlers: list[QuoteHandler] = []
        self._bar_handlers: list[BarHandler] = []
        self._status_handlers: list[StatusHandler] = []
        self._halt_handlers: list[HaltHandler] = []

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Begin connecting. Must not raise if the upstream is unreachable."""

    async def stop(self) -> None:
        """Release connections and background tasks."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """True when this provider can serve requests right now."""

    @property
    def is_delayed(self) -> bool:
        """True when the data carries a regulatory delay."""
        return False

    # ── history ────────────────────────────────────────────────────────

    @abstractmethod
    async def fetch_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        """Historical bars in ascending time order. Empty list when none."""

    # ── streaming ──────────────────────────────────────────────────────

    async def set_stream_symbols(self, symbols: set[str]) -> None:
        """Declare the complete set of symbols to stream."""

    # ── events ─────────────────────────────────────────────────────────

    def on_trade(self, handler: TradeHandler) -> None:
        self._trade_handlers.append(handler)

    def on_quote(self, handler: QuoteHandler) -> None:
        self._quote_handlers.append(handler)

    def on_bar(self, handler: BarHandler) -> None:
        self._bar_handlers.append(handler)

    def on_status_change(self, handler: StatusHandler) -> None:
        self._status_handlers.append(handler)

    def on_halt(self, handler: HaltHandler) -> None:
        self._halt_handlers.append(handler)

    async def _emit_trade(self, symbol: str, trade: Trade) -> None:
        for handler in self._trade_handlers:
            try:
                await handler(symbol, trade)
            except Exception:
                logger.exception("%s: trade handler failed", self.name)

    async def _emit_quote(self, symbol: str, quote: Quote) -> None:
        for handler in self._quote_handlers:
            try:
                await handler(symbol, quote)
            except Exception:
                logger.exception("%s: quote handler failed", self.name)

    async def _emit_bar(self, symbol: str, timeframe: Timeframe, bar: Bar) -> None:
        for handler in self._bar_handlers:
            try:
                await handler(symbol, timeframe, bar)
            except Exception:
                logger.exception("%s: bar handler failed", self.name)

    async def _emit_halt(self, symbol: str, halted: bool) -> None:
        for handler in self._halt_handlers:
            try:
                await handler(symbol, halted)
            except Exception:
                logger.exception("%s: halt handler failed", self.name)

    async def _emit_status(self) -> None:
        for handler in self._status_handlers:
            try:
                await handler()
            except Exception:
                logger.exception("%s: status handler failed", self.name)
