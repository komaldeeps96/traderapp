"""Scanner ranking and the reference numbers stamped onto each row."""

from __future__ import annotations

import asyncio

import pytest

from app.core.settings import ScannerSettings
from app.domain.scanner import ScannerRow
from app.domain.screener import SymbolStats
from app.services.scanner import ScannerService


class FakeIBKR:
    is_available = True

    def __init__(self) -> None:
        self.handler = None

    def on_scanner(self, handler) -> None:
        self.handler = handler


class FakeTV:
    """Stands in for TradingView's stats cache."""

    def __init__(self, cached: dict[str, SymbolStats] | None = None):
        self.cache = cached or {}
        self.fetched: list[str] = []

    def peek_stats(self, symbol: str) -> SymbolStats | None:
        return self.cache.get(symbol)

    async def get_stats(self, symbol: str) -> SymbolStats | None:
        self.fetched.append(symbol)
        return self.cache.get(symbol)


def row(symbol: str, rate: int = 50, dollars: float = 0.0) -> ScannerRow:
    return ScannerRow(rank=0, symbol=symbol, price=10.0, trades_1m=rate, dollar_vol_1m=dollars)


def service(tv=None) -> ScannerService:
    return ScannerService(FakeIBKR(), ScannerSettings(), tv)


class TestOrdering:
    def test_orders_by_trade_rate(self):
        ranked = service()._rank([row("AAA", 10), row("BBB", 90)])
        assert [r.symbol for r in ranked] == ["BBB", "AAA"]

    def test_dollar_volume_breaks_a_tie(self):
        """At equal print rates the name moving real money earns the row."""
        ranked = service()._rank([row("AAA", 50, dollars=1_000), row("BBB", 50, dollars=90_000)])
        assert [r.symbol for r in ranked] == ["BBB", "AAA"]

    def test_our_own_print_counts_never_reach_the_sort(self):
        """`trades_5m` is measured off the market-data line and is unreliable
        in both directions — 2-5x high on quiet names, 30% low on hot ones."""
        busy = row("BUSY", 80)
        busy.trades_5m = 1
        quiet = row("QUIET", 20)
        quiet.trades_5m = 10_000
        assert [r.symbol for r in service()._rank([quiet, busy])] == ["BUSY", "QUIET"]


class TestReferenceNumbers:
    def test_stamps_float_and_market_cap_from_the_cache(self):
        tv = FakeTV({"AAA": SymbolStats(symbol="AAA", float_shares=2_650_000, market_cap=3_300_000)})
        (only,) = service(tv)._rank([row("AAA")])
        assert only.float_shares == pytest.approx(2_650_000)
        assert only.market_cap == pytest.approx(3_300_000)

    def test_a_miss_warms_in_the_background_rather_than_blocking(self):
        """Rows emit every few seconds and must never wait on an HTTP call."""

        async def scenario():
            tv = FakeTV()
            (only,) = service(tv)._rank([row("AAA")])
            assert only.float_shares is None  # this emission goes out regardless
            await asyncio.sleep(0)
            return tv

        tv = asyncio.run(scenario())
        assert tv.fetched == ["AAA"]

    def test_runs_without_tradingview_at_all(self):
        (only,) = service(None)._rank([row("AAA")])
        assert only.float_shares is None


class TestRankVelocity:
    def test_measures_movement_against_the_order_actually_emitted(self):
        svc = service()
        svc._rank([row("AAA", 90), row("BBB", 10)])
        svc._ranks._history._snapshots[0] = (0.0, svc._ranks._history._snapshots[0][1])

        ranked = svc._rank([row("AAA", 10), row("BBB", 90)])
        assert [r.symbol for r in ranked] == ["BBB", "AAA"]
        assert ranked[0].rank_delta == 1  # BBB climbed one place
        assert ranked[1].rank_delta == -1
