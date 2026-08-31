"""Scanner ranking and the reference numbers stamped onto each row."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.core.settings import ScannerSettings
from app.domain.scanner import ScannerConfig, ScannerRow
from app.domain.screener import SymbolStats
from app.services.scanner import ScannerService

TIER_ID = "small_cap"


class FakeIBKR:
    is_available = True

    def __init__(self) -> None:
        self.handler = None

    def on_scanner(self, scanner_id, handler) -> None:
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


def fresh(**fields) -> SymbolStats:
    """Stats stamped just now, so the sync tests trigger no background warm."""
    return SymbolStats(symbol="AAA", fetched_at=time.time(), **fields)


def row(symbol: str, rate: int = 50, dollars: float = 0.0) -> ScannerRow:
    return ScannerRow(rank=0, symbol=symbol, price=10.0, trades_1m=rate, dollar_vol_1m=dollars)


def service(tv=None) -> ScannerService:
    return ScannerService(FakeIBKR(), TIER_ID, ScannerSettings(), tv)


class TestAdoptConfig:
    def test_saved_filters_replace_the_defaults(self):
        svc = service()
        svc.adopt_config(
            {"scan_code": "TOP_PERC_GAIN", "above_price": 2.0, "below_price": 25.0}
        )
        config = svc.state.config
        assert config.scan_code == "TOP_PERC_GAIN"
        assert config.above_price == pytest.approx(2.0)
        assert config.below_price == pytest.approx(25.0)

    def test_null_clears_a_filter(self):
        svc = service()
        assert svc.state.config.below_price is not None  # the default ceiling
        svc.adopt_config({"below_price": None})
        assert svc.state.config.below_price is None

    def test_unknown_keys_and_wrong_types_are_dropped(self):
        svc = service()
        before = svc.state.config.to_dict()
        svc.adopt_config(
            {"stray": 1, "above_price": "not a number", "scan_code": 42, "above_volume": True}
        )
        assert svc.state.config.to_dict() == before

    def test_an_unknown_scan_code_rejects_the_lot(self):
        svc = service()
        before = svc.state.config.to_dict()
        svc.adopt_config({"scan_code": "NOT_A_SCAN", "above_price": 2.0})
        assert svc.state.config.to_dict() == before

    def test_a_saved_row_count_never_overrides_the_tier(self):
        """The depth is the tier's. A state file written before it changed
        carries the old number, and adopting that would pin the panel back to
        it silently and permanently."""
        svc = service()
        # Ten is what small cap used to run at, so this is the exact state
        # file that exists on disk from before the depth changed.
        svc.adopt_config({"number_of_rows": 10})
        assert svc.state.config.number_of_rows == 5

        svc.adopt_config({"number_of_rows": 9999})
        assert svc.state.config.number_of_rows == 5


class TestTierDepth:
    def test_every_tier_shows_five(self):
        """Four panels share one column with the key levels underneath."""
        for tier_id in ("small_cap", "mid_cap", "large_cap", "mega_cap"):
            svc = ScannerService(FakeIBKR(), tier_id, ScannerSettings())
            assert svc.state.config.number_of_rows == 5


class TestMergedClearSentinel:
    """``ScannerConfig.merged`` is what ``ScannerService.configure`` calls on
    every ``scanner.configure`` command — the "clear" sentinel here is what
    lets a client actually switch a bound off, not just leave it alone.
    """

    def test_clear_relaxes_a_price_bound(self):
        config = ScannerConfig(scan_code="TOP_TRADE_RATE", below_price=50.0)
        cleared = config.merged(below_price="clear")
        assert cleared.below_price is None

    def test_clear_relaxes_above_price_too(self):
        config = ScannerConfig(scan_code="TOP_TRADE_RATE", above_price=2.0)
        cleared = config.merged(above_price="clear")
        assert cleared.above_price is None

    def test_omitting_a_price_bound_leaves_it_alone(self):
        config = ScannerConfig(scan_code="TOP_TRADE_RATE", below_price=50.0)
        unchanged = config.merged(above_price=5.0)
        assert unchanged.below_price == pytest.approx(50.0)


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
        tv = FakeTV({"AAA": fresh(float_shares=2_650_000, market_cap=3_300_000)})
        (only,) = service(tv)._rank([row("AAA")])
        assert only.float_shares == pytest.approx(2_650_000)
        # No share count in the cache: the static TV figure is the fallback.
        assert only.market_cap == pytest.approx(3_300_000)

    def test_market_cap_follows_the_live_price(self):
        """Shares outstanding times the row's price, not TV's stale snapshot."""
        tv = FakeTV(
            {
                "AAA": fresh(
                    shares_outstanding=1_000_000,
                    market_cap=3_300_000,  # TV's snapshot, taken at $3.30
                )
            }
        )
        (only,) = service(tv)._rank([row("AAA")])  # rows trade at 10.0
        assert only.market_cap == pytest.approx(10_000_000)

    def test_stale_stats_are_rewarmed_but_still_stamped(self):
        """The share count behind the live market cap moves on offerings;
        a stale cache refreshes in the background while its last value keeps
        the columns filled."""

        async def scenario():
            stale = fresh(shares_outstanding=1_000_000)
            stale.fetched_at = time.time() - 3600
            tv = FakeTV({"AAA": stale})
            (only,) = service(tv)._rank([row("AAA")])
            assert only.market_cap == pytest.approx(10_000_000)  # stale beats blank
            await asyncio.sleep(0)
            return tv

        tv = asyncio.run(scenario())
        assert tv.fetched == ["AAA"]

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
