"""The info strip numbers: session volumes, rotation, halt bands."""

from __future__ import annotations

import pytest

from app.core.clock import now_epoch
from app.domain.screener import SymbolStats
from app.domain.timeframes import Timeframe
from app.market.store import BarStore
from app.services.symbol_info import SymbolInfoService, _tier2_band_percent
from app.services.tv import TVDataService
from tests.conftest import make_bar, make_minute_series, ny_epoch


def service_with(store: BarStore, stats: SymbolStats | None) -> SymbolInfoService:
    tv = TVDataService(fetch=lambda q: {"totalCount": 0, "data": []})
    if stats is not None:
        stats.fetched_at = now_epoch()
        tv._stats_cache[stats.symbol] = stats
    return SymbolInfoService(store, tv)


def stats_for(symbol: str = "RUN") -> SymbolStats:
    return SymbolStats(
        symbol=symbol,
        float_shares=5_000_000,
        market_cap=40_000_000,
        avg_vol_10d=2_000_000,
        description="Runner Inc",
    )


@pytest.fixture
def store() -> BarStore:
    return BarStore()


class TestBuild:
    def test_nothing_loaded_and_no_stats_is_none(self, store):
        service = service_with(store, None)
        assert service.build("RUN") is None

    def test_day_volume_sums_only_today(self, store):
        yesterday = make_minute_series(ny_epoch(2024, 3, 4, 9, 30), [10.0] * 5)
        today = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [11.0] * 3)
        store.replace("RUN", Timeframe.M1, yesterday + today)

        info = service_with(store, stats_for()).build("RUN")
        assert info is not None
        # make_minute_series bars carry volume=100 each.
        assert info["day_volume"] == pytest.approx(300)

    def test_premarket_volume_and_rotation(self, store):
        premarket = make_minute_series(ny_epoch(2024, 3, 5, 7, 0), [9.0] * 4)
        regular = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0] * 6)
        store.replace("RUN", Timeframe.M1, premarket + regular)

        info = service_with(store, stats_for()).build("RUN")
        assert info["pm_volume"] == pytest.approx(400)
        assert info["day_volume"] == pytest.approx(1000)
        assert info["float_rotation"] == pytest.approx(1000 / 5_000_000)
        assert info["pm_float_rotation"] == pytest.approx(400 / 5_000_000)
        assert info["rel_vol"] == pytest.approx(1000 / 2_000_000)

    def test_prev_close_comes_from_the_last_prior_day(self, store):
        store.replace(
            "RUN",
            Timeframe.D1,
            [
                make_bar(ny_epoch(2024, 3, 1, 0, 0), 4.20),
                make_bar(ny_epoch(2024, 3, 4, 0, 0), 4.80),
            ],
        )
        store.replace("RUN", Timeframe.M1, make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [5.0]))

        # "Today" in this test is the present, so both daily bars are prior days.
        info = service_with(store, stats_for()).build("RUN")
        assert info["prev_close"] == pytest.approx(4.80)

    def test_stats_alone_still_produce_a_message(self, store):
        info = service_with(store, stats_for()).build("RUN")
        assert info is not None
        assert info["float_shares"] == pytest.approx(5_000_000)
        assert info["day_volume"] == 0.0
        assert info["float_rotation"] is None


class TestHaltBands:
    def test_tier_percent_follows_the_prior_close(self):
        assert _tier2_band_percent(5.0) == pytest.approx(0.10)
        assert _tier2_band_percent(1.50) == pytest.approx(0.20)
        assert _tier2_band_percent(0.50) is None

    def test_bands_bracket_the_reference(self, store):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0] * 10)
        store.replace("RUN", Timeframe.M1, bars)
        store.replace("RUN", Timeframe.D1, [make_bar(ny_epoch(2024, 3, 4, 0, 0), 9.0)])

        info = service_with(store, stats_for()).build("RUN")
        assert info["halt_ref"] == pytest.approx(10.0)
        assert info["halt_up"] == pytest.approx(11.0)
        assert info["halt_down"] == pytest.approx(9.0)

    def test_sub_dollar_uses_fifteen_cent_bands(self, store):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [0.60] * 10)
        store.replace("RUN", Timeframe.M1, bars)
        store.replace("RUN", Timeframe.D1, [make_bar(ny_epoch(2024, 3, 4, 0, 0), 0.55)])

        info = service_with(store, stats_for()).build("RUN")
        assert info["halt_up"] == pytest.approx(0.75)
        assert info["halt_down"] == pytest.approx(0.45)

    def test_without_a_prev_close_no_bands(self, store):
        store.replace("RUN", Timeframe.M1, make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [5.0]))
        info = service_with(store, stats_for()).build("RUN")
        assert info["halt_up"] is None
