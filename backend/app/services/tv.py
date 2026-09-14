"""TradingView reference data, via the ``tradingview-screener`` package.

Two things IBKR will not give us without a fundamentals entitlement: per-symbol
float and market cap, and the market-regime counts. Needs no credentials and no
TWS.

The underlying package is synchronous ``requests``, so every call is pushed onto
a worker thread; ``fetch`` is injectable so tests never touch the network.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence

from tradingview_screener import Query, col
from tradingview_screener.query import And

from ..domain.screener import MarketRegime, RowReader, SymbolStats
from ..domain.sessions import Session, session_of

logger = logging.getLogger(__name__)

# The row shape the stats lookup reads.
_COLUMNS = [
    "name",
    "description",
    "exchange",
    "close",
    "change",
    "volume",
    "relative_volume_10d_calc",
    "float_shares_outstanding",
    "market_cap_basic",
    "average_volume_10d_calc",
    "total_shares_outstanding_fundamental",
    "premarket_change",
    "premarket_close",
    "premarket_volume",
    "sector",
    # Split-adjusted all-time high since listing — unreachable from our own
    # bars, which only go back three years.
    "High.All",
    "industry",
    "earnings_release_next_date",
]
_ROW = RowReader(_COLUMNS)

STATS_TTL_SECONDS = 300.0
# A symbol TradingView cannot find is asked about again after this, not on every
# scanner update: a fresh listing sits in the scan before it is in the index.
MISS_TTL_SECONDS = 120.0
# Symbols held at once. A day of charting touches a few hundred names.
MAX_CACHED_SYMBOLS = 1_000


def common_stock_terms() -> list:
    """Listed US common stock only.

    TradingView's ``america`` market includes OTC pink sheets, which would
    otherwise flood both the screen and the regime counts.
    """
    return [
        col("is_primary") == True,  # noqa: E712 — builds the API expression
        col("type") == "stock",
        col("typespecs").has(["common"]),
        col("exchange").isin(["NASDAQ", "NYSE", "AMEX"]),
    ]


def scan_rows(query: Query, columns: Sequence[str]) -> list[list]:
    """A screener query's rows, in ``columns`` order. Blocking: run it on a thread."""
    _, frame = query.get_scanner_data()
    return frame[list(columns)].values.tolist() if not frame.empty else []


class TVDataService:
    def __init__(self, fetch: Callable[[Query], dict] | None = None):
        # The seam for tests: run the query, return the raw payload.
        self._fetch = fetch or (lambda query: query.get_scanner_data_raw())
        self._stats_cache: dict[str, SymbolStats] = {}
        self._stats_locks: dict[str, asyncio.Lock] = {}
        self._misses: dict[str, float] = {}

    async def _run(self, query: Query) -> dict:
        return await asyncio.to_thread(self._fetch, query)

    async def market_regime(self) -> MarketRegime:
        """Counts of stocks up more than 50% and 100% on the day.

        A volume floor keeps the count honest: a microcap up 80% on ten
        thousand shares is the illusion of momentum, not the market running.
        """
        premarket = session_of(time.time()) is Session.PREMARKET
        change_col = "premarket_change" if premarket else "change"
        volume_col = "premarket_volume" if premarket else "volume"
        volume_floor = 100_000 if premarket else 500_000

        async def count(threshold: float) -> int:
            query = (
                Query()
                .set_markets("america")
                .select("name")
                .where2(
                    And(
                        *common_stock_terms(),
                        col(change_col) >= threshold,
                        col(volume_col) >= volume_floor,
                    )
                )
                .limit(1)
            )
            payload = await self._run(query)
            return int(payload.get("totalCount", 0))

        up_50, up_100 = await asyncio.gather(count(50.0), count(100.0))
        return MarketRegime(up_50_count=up_50, up_100_count=up_100)

    # ── per-symbol stats ───────────────────────────────────────────────

    async def get_stats(self, symbol: str) -> SymbolStats | None:
        """Reference stats, cached briefly — float does not move by the tick."""
        cached = self._stats_cache.get(symbol)
        if cached and time.time() - cached.fetched_at < STATS_TTL_SECONDS:
            return cached
        if time.time() - self._misses.get(symbol, 0.0) < MISS_TTL_SECONDS:
            return cached

        lock = self._stats_locks.setdefault(symbol, asyncio.Lock())
        async with lock:
            cached = self._stats_cache.get(symbol)
            if cached and time.time() - cached.fetched_at < STATS_TTL_SECONDS:
                return cached
            try:
                stats = await self._fetch_stats(symbol)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("TradingView stats failed for %s: %s", symbol, exc)
                return cached
            if stats is None:
                self._misses[symbol] = time.time()
            else:
                self._stats_cache[symbol] = stats
                self._misses.pop(symbol, None)
            self._trim()
            return stats

    def _trim(self) -> None:
        """Oldest out once the caches pass their bound."""
        if len(self._stats_cache) > MAX_CACHED_SYMBOLS:
            by_age = sorted(self._stats_cache, key=lambda name: self._stats_cache[name].fetched_at)
            for name in by_age[: len(self._stats_cache) - MAX_CACHED_SYMBOLS]:
                del self._stats_cache[name]
                lock = self._stats_locks.get(name)
                if lock is not None and not lock.locked():
                    del self._stats_locks[name]
        if len(self._misses) > MAX_CACHED_SYMBOLS:
            by_age = sorted(self._misses, key=self._misses.__getitem__)
            for name in by_age[: len(self._misses) - MAX_CACHED_SYMBOLS]:
                del self._misses[name]

    def peek_stats(self, symbol: str) -> SymbolStats | None:
        """The cached value, however stale, without touching the network."""
        return self._stats_cache.get(symbol)

    async def _fetch_stats(self, symbol: str) -> SymbolStats | None:
        row = await self._stats_row(symbol)
        if row is None:
            return None
        return SymbolStats(
            symbol=symbol,
            description=_ROW.text(row, "description"),
            exchange=_ROW.text(row, "exchange"),
            sector=_ROW.text(row, "sector"),
            float_shares=_ROW.number(row, "float_shares_outstanding"),
            market_cap=_ROW.number(row, "market_cap_basic"),
            shares_outstanding=_ROW.number(row, "total_shares_outstanding_fundamental"),
            avg_vol_10d=_ROW.number(row, "average_volume_10d_calc"),
            premarket_volume=_ROW.number(row, "premarket_volume"),
            premarket_change=_ROW.number(row, "premarket_change"),
            all_time_high=_ROW.number(row, "High.All"),
            industry=_ROW.text(row, "industry"),
            earnings_next=_ROW.number(row, "earnings_release_next_date"),
            fetched_at=time.time(),
        )

    async def _stats_row(self, symbol: str) -> list | None:
        """Find one symbol's row, the reliable way and then the other way.

        Matching on ``name`` equality is exact and cheap, and silently misses
        newly listed symbols: TradingView's symbol index lags its scan set, and
        a fresh listing is exactly what this scanner surfaces.

        ``like`` is a substring match — searching "FGI" also returns MFGI and
        FGII — so the exact name has to be picked back out here.
        """
        base = Query().set_markets("america").select(*_COLUMNS)

        payload = await self._run(
            base.where2(And(col("name") == symbol, col("is_primary") == True)).limit(1)  # noqa: E712
        )
        data = payload.get("data") or []
        if data:
            return data[0]["d"]

        payload = await self._run(
            Query()
            .set_markets("america")
            .select(*_COLUMNS)
            .where(col("name").like(symbol))
            .limit(20)
        )
        for entry in payload.get("data") or []:
            row = entry["d"]
            if _ROW.text(row, "name") == symbol:
                return row
        return None

    def drop(self, symbol: str) -> None:
        self._stats_cache.pop(symbol, None)
        self._stats_locks.pop(symbol, None)
