"""Building live bars from trade prints."""

from __future__ import annotations

import pytest

from app.domain.bars import Bar
from app.domain.timeframes import Timeframe
from app.market.bar_builder import BarBuilder, Trade
from tests.conftest import ny_epoch


@pytest.fixture
def builder() -> BarBuilder:
    return BarBuilder(Timeframe.M1)


@pytest.fixture
def open_time() -> int:
    return ny_epoch(2024, 3, 5, 9, 30)


class TestFirstTrade:
    def test_opens_a_bar_at_the_period_start(self, builder, open_time):
        builder.add_trade(Trade(time=open_time + 12, price=10.0, size=100))
        assert builder.current.time == open_time

    def test_sets_every_price_to_the_first_print(self, builder, open_time):
        builder.add_trade(Trade(time=open_time, price=10.0, size=100))
        bar = builder.current
        assert (bar.open, bar.high, bar.low, bar.close) == (10.0, 10.0, 10.0, 10.0)

    def test_returns_nothing_to_emit(self, builder, open_time):
        assert builder.add_trade(Trade(time=open_time, price=10.0, size=100)) is None


class TestWithinAPeriod:
    def test_tracks_the_running_extremes(self, builder, open_time):
        for price in (10.0, 12.0, 8.0, 11.0):
            builder.add_trade(Trade(time=open_time + 1, price=price, size=10))
        bar = builder.current
        assert (bar.open, bar.high, bar.low, bar.close) == (10.0, 12.0, 8.0, 11.0)

    def test_accumulates_volume_and_counts_trades(self, builder, open_time):
        for _ in range(3):
            builder.add_trade(Trade(time=open_time, price=10.0, size=50))
        assert builder.current.volume == pytest.approx(150)
        assert builder.current.trades == 3

    def test_stays_in_the_same_period_for_the_whole_minute(self, builder, open_time):
        builder.add_trade(Trade(time=open_time, price=10.0, size=1))
        assert builder.add_trade(Trade(time=open_time + 59, price=11.0, size=1)) is None


class TestRollover:
    def test_emits_the_completed_bar(self, builder, open_time):
        builder.add_trade(Trade(time=open_time, price=10.0, size=100))
        completed = builder.add_trade(Trade(time=open_time + 60, price=11.0, size=50))
        assert completed is not None and completed.time == open_time

    def test_completed_bar_keeps_its_own_totals(self, builder, open_time):
        builder.add_trade(Trade(time=open_time, price=10.0, size=100))
        completed = builder.add_trade(Trade(time=open_time + 60, price=11.0, size=50))
        assert completed.close == pytest.approx(10.0)
        assert completed.volume == pytest.approx(100)

    def test_opens_the_next_period_from_the_new_trade(self, builder, open_time):
        builder.add_trade(Trade(time=open_time, price=10.0, size=100))
        builder.add_trade(Trade(time=open_time + 60, price=11.0, size=50))
        assert builder.current.time == open_time + 60
        assert builder.current.open == pytest.approx(11.0)
        assert builder.current.volume == pytest.approx(50)

    def test_skipping_quiet_minutes_does_not_invent_bars(self, builder, open_time):
        builder.add_trade(Trade(time=open_time, price=10.0, size=1))
        completed = builder.add_trade(Trade(time=open_time + 600, price=11.0, size=1))
        assert completed.time == open_time
        assert builder.current.time == open_time + 600


class TestBadInput:
    def test_ignores_a_late_print_for_a_closed_period(self, builder, open_time):
        builder.add_trade(Trade(time=open_time + 60, price=11.0, size=10))
        assert builder.add_trade(Trade(time=open_time, price=99.0, size=10)) is None

    def test_a_late_print_does_not_corrupt_the_open_bar(self, builder, open_time):
        builder.add_trade(Trade(time=open_time + 60, price=11.0, size=10))
        builder.add_trade(Trade(time=open_time, price=99.0, size=10))
        assert builder.current.high == pytest.approx(11.0)

    @pytest.mark.parametrize("price", [0.0, -1.0])
    def test_ignores_a_non_positive_price(self, builder, open_time, price):
        builder.add_trade(Trade(time=open_time, price=price, size=10))
        assert builder.current is None

    def test_ignores_a_negative_size(self, builder, open_time):
        builder.add_trade(Trade(time=open_time, price=10.0, size=-5))
        assert builder.current is None

    def test_accepts_a_zero_size_print(self, builder, open_time):
        builder.add_trade(Trade(time=open_time, price=10.0, size=0))
        assert builder.current is not None


class TestAdopt:
    def test_replaces_rather_than_adds(self, builder, open_time):
        """Provider volume is authoritative; ours must not be added to it."""
        builder.add_trade(Trade(time=open_time, price=10.0, size=100))
        builder.adopt(Bar(time=open_time, open=9, high=13, low=8, close=12, volume=5000, trades=90))
        assert builder.current.volume == pytest.approx(5000)

    def test_takes_the_provider_prices(self, builder, open_time):
        builder.add_trade(Trade(time=open_time, price=10.0, size=100))
        builder.adopt(Bar(time=open_time, open=9, high=13, low=8, close=12, volume=5000, trades=90))
        bar = builder.current
        assert (bar.open, bar.high, bar.low, bar.close) == (9, 13, 8, 12)

    def test_later_trades_continue_from_the_adopted_bar(self, builder, open_time):
        builder.adopt(Bar(time=open_time, open=9, high=13, low=8, close=12, volume=5000, trades=90))
        builder.add_trade(Trade(time=open_time + 30, price=14.0, size=10))
        assert builder.current.high == pytest.approx(14.0)
        assert builder.current.volume == pytest.approx(5010)

    def test_snaps_a_stray_timestamp_to_the_period(self, builder, open_time):
        builder.adopt(Bar(time=open_time + 42, open=9, high=13, low=8, close=12, volume=1))
        assert builder.current.time == open_time


class TestReset:
    def test_clears_the_in_progress_bar(self, builder, open_time):
        builder.add_trade(Trade(time=open_time, price=10.0, size=1))
        builder.reset()
        assert builder.current is None


class TestBuildBars:
    """Batch aggregation of a raw trade tape into bars."""

    def test_builds_ten_second_bars_from_a_tape(self, open_time):
        from app.market.bar_builder import build_bars

        trades = [
            Trade(time=open_time + 1, price=10.0, size=100),
            Trade(time=open_time + 4, price=10.5, size=50),
            Trade(time=open_time + 12, price=10.2, size=200),
            Trade(time=open_time + 25, price=9.8, size=75),
        ]
        bars = build_bars(trades, Timeframe.S10)

        assert [bar.time for bar in bars] == [open_time, open_time + 10, open_time + 20]
        assert bars[0].high == pytest.approx(10.5)
        assert bars[0].volume == pytest.approx(150)
        assert bars[2].close == pytest.approx(9.8)

    def test_sorts_a_newest_first_tape(self, open_time):
        """Paginated fetches arrive descending; aggregation must not care."""
        from app.market.bar_builder import build_bars

        trades = [
            Trade(time=open_time + 25, price=9.8, size=75),
            Trade(time=open_time + 1, price=10.0, size=100),
            Trade(time=open_time + 12, price=10.2, size=200),
        ]
        bars = build_bars(trades, Timeframe.S10)
        assert [bar.time for bar in bars] == [open_time, open_time + 10, open_time + 20]
        assert bars[0].open == pytest.approx(10.0)

    def test_includes_the_unfinished_final_bar(self, open_time):
        from app.market.bar_builder import build_bars

        bars = build_bars([Trade(time=open_time + 3, price=5.0, size=10)], Timeframe.S10)
        assert len(bars) == 1
        assert bars[0].time == open_time

    def test_empty_tape_builds_nothing(self):
        from app.market.bar_builder import build_bars

        assert build_bars([], Timeframe.S10) == []
