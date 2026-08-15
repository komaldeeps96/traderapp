"""Chooses between IBKR and Alpaca, and fails over between them.

IBKR is preferred for live data because it is real-time and consolidated.
When TWS is not running — which is most of the time during development, and
any time it drops mid-session — the router transparently moves streaming to
Alpaca. Alpaca may be delayed depending on the configured feed; the delay is
reported to the client rather than hidden, so the chart can say so.

History is always assembled from both when both are up: Alpaca supplies the
long window, IBKR overwrites the most recent minutes with its own bars.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from ..core.settings import HistorySettings
from ..domain.bars import Bar, merge_bars
from ..domain.protocol import DataSource
from ..domain.timeframes import Timeframe
from .alpaca import AlpacaProvider
from .base import MarketDataProvider
from .ibkr import IBKRProvider

logger = logging.getLogger(__name__)

# The 10-second history window: twelve hours, IBKR-native. IBKR caps a 10s
# request at four hours, so this is three requests — the recent slice for the
# first paint, and the remaining eight hours chunked in the background pass.
#
# Twelve rather than eight so the window reaches 04:00 from any point in the
# session a trade is taken: at 15:00 New York eight hours stops at 07:00 and
# leaves three hours of pre-market outside the chart. Session-scoped
# indicators are seeded past that edge anyway (see indicators/functions.py,
# SessionPrefix), but a seed is a summary — the bars themselves are what a
# level gets drawn against.
#
# Rebuilding the same window from Alpaca's raw tape costs ten to forty
# sequential pages on a runner — seconds of download for bars IBKR serves in
# one — so the tape walk is only a fallback for when TWS is down, and then
# only for the recent slice.
TENSEC_WINDOW_SECONDS = 12 * 3600
TENSEC_RECENT_SECONDS = 4 * 3600


class FeedRouter(MarketDataProvider):
    name = "router"

    def __init__(
        self,
        alpaca: AlpacaProvider,
        ibkr: IBKRProvider,
        history: HistorySettings,
    ):
        super().__init__()
        self._alpaca = alpaca
        self._ibkr = ibkr
        self._history = history
        self._symbols: set[str] = set()
        self._routed_to: DataSource | None = None
        self._lock = asyncio.Lock()

        # Forward market events from whichever provider is live.
        for provider in (alpaca, ibkr):
            provider.on_trade(self._emit_trade)
            provider.on_quote(self._emit_quote)
            provider.on_bar(self._emit_bar)
            provider.on_status_change(self._on_provider_status)

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        await asyncio.gather(
            self._alpaca.start(), self._ibkr.start(), return_exceptions=True
        )

    async def stop(self) -> None:
        await asyncio.gather(
            self._alpaca.stop(), self._ibkr.stop(), return_exceptions=True
        )

    @property
    def is_available(self) -> bool:
        return self._ibkr.is_available or self._alpaca.is_available

    @property
    def active_source(self) -> DataSource:
        if self._ibkr.is_available:
            return DataSource.IBKR
        if self._alpaca.is_available:
            return DataSource.ALPACA
        return DataSource.NONE

    @property
    def is_delayed(self) -> bool:
        source = self.active_source
        if source is DataSource.IBKR:
            return False
        if source is DataSource.ALPACA:
            return self._alpaca.is_delayed
        return False

    @property
    def ibkr_connected(self) -> bool:
        return self._ibkr.is_available

    @property
    def alpaca_available(self) -> bool:
        return self._alpaca.is_available

    def status_note(self) -> str | None:
        source = self.active_source
        if source is DataSource.NONE:
            return "No market data provider is available. Check credentials and TWS."
        if source is DataSource.ALPACA and not self._ibkr.is_available:
            suffix = " (15-minute delayed)" if self._alpaca.is_delayed else ""
            return f"IBKR unavailable — using Alpaca{suffix}."
        return None

    # ── history ────────────────────────────────────────────────────────

    async def fetch_history(self, symbol: str, timeframe: Timeframe) -> list[Bar]:
        """Load the base timeframe for ``symbol`` from every available source."""
        base = timeframe.base
        now = datetime.now(UTC)

        if base is Timeframe.D1:
            start = now - timedelta(days=365 * self._history.daily_years)
            return await self._fetch_daily(symbol, start, now)

        if base is Timeframe.S10:
            return await self._fetch_tensec(symbol, now)

        start = now - timedelta(days=self._history.intraday_days)
        return await self._fetch_intraday(symbol, start, now)

    async def _fetch_tensec(self, symbol: str, end: datetime) -> list[Bar]:
        """The full twelve-hour 10s window in one go (both slices merged)."""
        recent, earlier = await asyncio.gather(
            self.fetch_recent_tensec(symbol, end),
            self.fetch_earlier_tensec(symbol, end),
        )
        if not recent and not earlier:
            return []
        return merge_bars(recent, earlier)

    async def _settle_ibkr(self) -> None:
        """Give a just-started IBKR connection a beat to come up.

        A server restart races history loads against the TWS handshake;
        loading delayed fallback data in that window tears a 15-minute hole
        between history and the real-time stream. Outside startup this
        returns immediately, so a genuinely absent TWS costs nothing.
        """
        if getattr(self._ibkr, "is_starting_up", False):
            await self._ibkr.wait_available(5.0)

    async def fetch_recent_tensec(self, symbol: str, end: datetime | None = None) -> list[Bar]:
        """The last four hours of 10s bars — the fast first paint.

        One native IBKR request when TWS is up; a page-capped Alpaca tape
        walk only as the fallback.
        """
        await self._settle_ibkr()
        end = end or datetime.now(UTC)
        start = end - timedelta(seconds=TENSEC_RECENT_SECONDS)
        if self._ibkr.is_available:
            bars = await self._safe_fetch(self._ibkr, symbol, Timeframe.S10, start, end)
            if bars:
                return bars
        if self._alpaca.is_available:
            return await self._safe_fetch(self._alpaca, symbol, Timeframe.S10, start, end)
        return []

    async def fetch_earlier_tensec(self, symbol: str, end: datetime | None = None) -> list[Bar]:
        """Hours four to twelve — the background extension of the 10s chart.

        IBKR only, and two native requests rather than one: the provider
        chunks anything longer than four hours itself. When TWS is down the
        extension is simply skipped rather than rebuilt from the tape, because
        a multi-page trade download for off-screen history is exactly the cost
        this window exists to avoid.
        """
        await self._settle_ibkr()
        if not self._ibkr.is_available:
            return []
        end = end or datetime.now(UTC)
        return await self._safe_fetch(
            self._ibkr,
            symbol,
            Timeframe.S10,
            end - timedelta(seconds=TENSEC_WINDOW_SECONDS),
            end - timedelta(seconds=TENSEC_RECENT_SECONDS),
        )

    async def _fetch_daily(self, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        if self._alpaca.is_available:
            bars = await self._safe_fetch(self._alpaca, symbol, Timeframe.D1, start, end)
            if bars:
                return bars
        if self._ibkr.is_available:
            return await self._safe_fetch(self._ibkr, symbol, Timeframe.D1, start, end)
        return []

    async def fetch_intraday_fast(self, symbol: str) -> list[Bar]:
        """The minute base in a single request — the fast path.

        Alpaca's newest page covers days of minutes at once; IBKR's
        consolidated recent hour merges in with the background pass instead
        of holding up the first paint.
        """
        now = datetime.now(UTC)
        start = now - timedelta(days=self._history.intraday_days)
        if self._alpaca.is_available:
            bars = await self._safe_fetch(self._alpaca, symbol, Timeframe.M1, start, now)
            if bars:
                return bars
        return await self.fetch_minute_recent(symbol)

    async def fetch_minute_recent(self, symbol: str) -> list[Bar]:
        """IBKR's freshest consolidated minutes — the delayed-feed gap filler."""
        if not self._ibkr.is_available:
            return []
        now = datetime.now(UTC)
        recent = now - timedelta(seconds=self._history.ibkr_recent_seconds)
        return await self._safe_fetch(self._ibkr, symbol, Timeframe.M1, recent, now)

    async def _fetch_intraday(self, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        tasks = []
        if self._alpaca.is_available:
            tasks.append(self._safe_fetch(self._alpaca, symbol, Timeframe.M1, start, end))
        if self._ibkr.is_available:
            recent = end - timedelta(seconds=self._history.ibkr_recent_seconds)
            tasks.append(self._safe_fetch(self._ibkr, symbol, Timeframe.M1, recent, end))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        collected: list[list[Bar]] = [r for r in results if isinstance(r, list)]
        if not collected:
            return []
        if len(collected) == 1:
            return collected[0]

        # Alpaca first, IBKR second — IBKR wins on overlapping minutes because
        # its bars are consolidated and arrive without the delay Alpaca may
        # carry. merge_bars replaces rather than sums, so volume is not doubled.
        alpaca_bars, ibkr_bars = collected[0], collected[1]
        return merge_bars(ibkr_bars, alpaca_bars)

    @staticmethod
    async def _safe_fetch(
        provider: MarketDataProvider,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        try:
            return await provider.fetch_bars(symbol, timeframe, start, end)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("%s history failed for %s: %s", provider.name, symbol, exc)
            return []

    async def fetch_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        if self._ibkr.is_available:
            bars = await self._safe_fetch(self._ibkr, symbol, timeframe, start, end)
            if bars:
                return bars
        return await self._safe_fetch(self._alpaca, symbol, timeframe, start, end)

    # ── streaming ──────────────────────────────────────────────────────

    async def set_stream_symbols(self, symbols: set[str]) -> None:
        self._symbols = set(symbols)
        await self._route()

    async def _route(self) -> None:
        """Point the stream at the preferred available provider.

        The provider that is not chosen has its symbol set cleared, so a
        failover never leaves two sources emitting trades for one symbol.
        """
        async with self._lock:
            target = self.active_source
            switched = target is not self._routed_to
            self._routed_to = target

            if target is DataSource.IBKR:
                await self._alpaca.set_stream_symbols(set())
                await self._ibkr.set_stream_symbols(self._symbols)
            elif target is DataSource.ALPACA:
                await self._ibkr.set_stream_symbols(set())
                await self._alpaca.set_stream_symbols(self._symbols)
            else:
                await self._ibkr.set_stream_symbols(set())
                await self._alpaca.set_stream_symbols(set())

            if switched and self._symbols:
                logger.info("Market data routed to %s", target.value)

    async def _on_provider_status(self) -> None:
        await self._route()
        await self._emit_status()
