"""TradingView reference data, via the ``tradingview-screener`` package.

Two things IBKR will not give us without a fundamentals entitlement this
account does not hold: per-symbol float and market cap, and the market-regime
counts. Needs no credentials and no TWS, so it works evenings and weekends.

The underlying package is synchronous ``requests``, so every call is pushed
onto a worker thread; ``fetch`` is injectable so tests never touch the
network.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from tradingview_screener import Query, col
from tradingview_screener.query import And

from ..domain.screener import MarketRegime, SymbolStats
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
]
_INDEX = {name: i for i, name in enumerate(_COLUMNS)}

STATS_TTL_SECONDS = 300.0


def _common_stock_terms() -> list:
    """Listed US common stock only.

    TradingView's ``america`` market includes OTC pink sheets, which are
    never tradeable in this workflow and would otherwise flood both the
    screen and the regime counts.
    """
    return [
        col("is_primary") == True,  # noqa: E712 — builds the API expression
        col("type") == "stock",
        col("typespecs").has(["common"]),
        col("exchange").isin(["NASDAQ", "NYSE", "AMEX"]),
    ]


def _value(row: list, column: str) -> float | None:
    value = row[_INDEX[column]]
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _text(row: list, column: str) -> str:
    value = row[_INDEX[column]]
    return value if isinstance(value, str) else ""


class TVDataService:
    def __init__(self, fetch: Callable[[Query], dict] | None = None):
        # The seam for tests: run the query, return the raw payload.
        self._fetch = fetch or (lambda query: query.get_scanner_data_raw())
        self._stats_cache: dict[str, SymbolStats] = {}
        self._stats_locks: dict[str, asyncio.Lock] = {}

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
                        *_common_stock_terms(),
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
            if stats is not None:
                self._stats_cache[symbol] = stats
            return stats

    def peek_stats(self, symbol: str) -> SymbolStats | None:
        """The cached value, however stale, without touching the network."""
        return self._stats_cache.get(symbol)

    async def _fetch_stats(self, symbol: str) -> SymbolStats | None:
        row = await self._stats_row(symbol)
        if row is None:
            return None
        return SymbolStats(
            symbol=symbol,
            description=_text(row, "description"),
            exchange=_text(row, "exchange"),
            sector=_text(row, "sector"),
            float_shares=_value(row, "float_shares_outstanding"),
            market_cap=_value(row, "market_cap_basic"),
            shares_outstanding=_value(row, "total_shares_outstanding_fundamental"),
            avg_vol_10d=_value(row, "average_volume_10d_calc"),
            premarket_volume=_value(row, "premarket_volume"),
            premarket_change=_value(row, "premarket_change"),
            fetched_at=time.time(),
        )

    async def _stats_row(self, symbol: str) -> list | None:
        """Find one symbol's row, the reliable way and then the other way.

        Matching on ``name`` equality is exact and cheap, and it silently
        misses newly listed symbols: measured on DFSC (DEFSEC Technologies,
        NASDAQ common), equality returned nothing and so did a lookup by its
        own reported ticker ``NASDAQ:DFSC`` — while a substring search
        returned the row with ``name`` exactly ``"DFSC"``. TradingView's
        symbol index lags its scan set, and a fresh listing is precisely the
        kind of name this scanner surfaces.

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
            if _text(row, "name") == symbol:
                return row
        return None

    def drop(self, symbol: str) -> None:
        self._stats_cache.pop(symbol, None)
        self._stats_locks.pop(symbol, None)
