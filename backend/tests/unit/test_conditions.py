"""Sale-condition classification and its effect on bar building."""

from __future__ import annotations

import pytest

from app.domain.timeframes import Timeframe
from app.market.bar_builder import BarBuilder, Trade, build_bars
from app.market.conditions import TradeKind, classify_conditions
from tests.conftest import ny_epoch


class TestClassification:
    def test_a_plain_trade_is_price_forming(self):
        assert classify_conditions(["@"]) is TradeKind.PRICE_FORMING
        assert classify_conditions([]) is TradeKind.PRICE_FORMING
        assert classify_conditions(None) is TradeKind.PRICE_FORMING

    def test_ordinary_extended_hours_trades_stay_price_forming(self):
        """Every pre-open print on a gapper carries T.

        Measured on a small-cap premarket session: 123,276 prints, 100% of
        them flagged T. Excluding it would leave 04:00-09:30 blank.
        """
        assert classify_conditions(["@", "T"]) is TradeKind.PRICE_FORMING

    def test_out_of_sequence_extended_hours_trades_are_volume_only(self):
        """U is the extended-hours flavour of Z and is treated the same.

        A late report must not plant a wick at a stale price in the session
        this terminal is built around.
        """
        assert classify_conditions(["U"]) is TradeKind.VOLUME_ONLY
        assert classify_conditions(["@", "T", "U"]) is TradeKind.VOLUME_ONLY

    @pytest.mark.parametrize("code", ["W", "Z", "P", "4", "C", "H", "7", "U"])
    def test_late_and_special_prints_are_volume_only(self, code):
        assert classify_conditions(["@", code]) is TradeKind.VOLUME_ONLY

    @pytest.mark.parametrize("code", ["M", "Q", "9"])
    def test_official_reprints_are_skipped(self, code):
        assert classify_conditions([code]) is TradeKind.SKIP

    def test_odd_lots_are_dropped_outright_to_match_the_baseline(self):
        """A deliberate divergence from the SIP rule.

        The specification keeps an odd lot's volume; IBKR does not, and the
        10s history this app is built on is IBKR's. Measured against a
        simultaneous recording of the full tape, its bars reproduce the tape
        minus odd lots to within 0.1% while the whole tape overshoots volume
        by 26.6%. Counting them on the Alpaca path would move volume by a
        quarter on failover.
        """
        assert classify_conditions(["@", "I"]) is TradeKind.SKIP
        assert classify_conditions(["@", "T", "I"]) is TradeKind.SKIP

    def test_skip_outranks_volume_only(self):
        assert classify_conditions(["W", "M"]) is TradeKind.SKIP

    def test_a_packed_condition_string_classifies_like_a_list(self):
        """IBKR hands sale conditions over as one string, not a list."""
        assert classify_conditions("@TZ") is TradeKind.VOLUME_ONLY
        assert classify_conditions("@TI") is TradeKind.SKIP
        assert classify_conditions("@T") is TradeKind.PRICE_FORMING
        assert classify_conditions("") is TradeKind.PRICE_FORMING


class TestBuilderWithVolumeOnlyPrints:
    def test_volume_lands_without_moving_prices(self):
        open_time = ny_epoch(2024, 3, 5, 9, 30)
        builder = BarBuilder(Timeframe.S10)
        builder.add_trade(Trade(time=open_time, price=10.0, size=100))

        # A five-million-share average-price block far off the market.
        builder.add_trade(
            Trade(time=open_time + 3, price=9.0, size=5_000_000, price_forming=False)
        )

        bar = builder.current
        assert (bar.open, bar.high, bar.low, bar.close) == (10.0, 10.0, 10.0, 10.0)
        assert bar.volume == pytest.approx(5_000_100)
        assert bar.trades == 2

    def test_a_volume_only_print_never_opens_a_bar(self):
        builder = BarBuilder(Timeframe.S10)
        builder.add_trade(
            Trade(time=ny_epoch(2024, 3, 5, 9, 30), price=9.0, size=500, price_forming=False)
        )
        assert builder.current is None

    def test_volume_arriving_before_the_open_is_held_not_lost(self):
        """A volume-only print can easily be the first in its period.

        Measured while the odd-lot rule was the SIP's, discarding these cost
        4.2% of volume against Alpaca's published minutes. Odd lots are now
        skipped outright so that particular loss is gone, but late reports and
        average-price blocks land first often enough to be worth holding.
        """
        open_time = ny_epoch(2024, 3, 5, 9, 30)
        builder = BarBuilder(Timeframe.S10)
        builder.add_trade(Trade(time=open_time, price=9.0, size=40, price_forming=False))
        builder.add_trade(Trade(time=open_time + 1, price=10.0, size=100))

        bar = builder.current
        assert (bar.open, bar.high, bar.low, bar.close) == (10.0, 10.0, 10.0, 10.0)
        assert bar.volume == pytest.approx(140)
        assert bar.trades == 2

    def test_held_volume_carries_across_a_rollover(self):
        open_time = ny_epoch(2024, 3, 5, 9, 30)
        builder = BarBuilder(Timeframe.S10)
        builder.add_trade(Trade(time=open_time, price=10.0, size=100))
        # An odd lot opens the *next* period, before any real trade does.
        builder.add_trade(
            Trade(time=open_time + 10, price=9.0, size=30, price_forming=False)
        )
        assert builder.current.time == open_time
        assert builder.current.volume == pytest.approx(100)

        completed = builder.add_trade(Trade(time=open_time + 11, price=11.0, size=50))
        assert completed.time == open_time and completed.volume == pytest.approx(100)
        assert builder.current.volume == pytest.approx(80)
        assert builder.current.open == pytest.approx(11.0)

    def test_a_period_that_never_opens_does_not_leak_forward(self):
        """Held volume belongs to its own period, not the next one."""
        open_time = ny_epoch(2024, 3, 5, 9, 30)
        builder = BarBuilder(Timeframe.S10)
        builder.add_trade(Trade(time=open_time, price=9.0, size=400, price_forming=False))
        builder.add_trade(
            Trade(time=open_time + 10, price=9.0, size=30, price_forming=False)
        )
        builder.add_trade(Trade(time=open_time + 11, price=11.0, size=50))
        assert builder.current.volume == pytest.approx(80)

    def test_a_late_print_for_an_older_period_is_dropped(self):
        open_time = ny_epoch(2024, 3, 5, 9, 30)
        builder = BarBuilder(Timeframe.S10)
        builder.add_trade(Trade(time=open_time + 20, price=10.0, size=100))
        builder.add_trade(
            Trade(time=open_time, price=8.0, size=900, price_forming=False)
        )
        assert builder.current.volume == pytest.approx(100)

    def test_tape_rebuild_applies_the_same_rules(self):
        open_time = ny_epoch(2024, 3, 5, 9, 30)
        bars = build_bars(
            [
                Trade(time=open_time + 1, price=10.0, size=100),
                Trade(time=open_time + 4, price=9.0, size=1_000_000, price_forming=False),
                Trade(time=open_time + 8, price=10.1, size=50),
            ],
            Timeframe.S10,
        )
        assert len(bars) == 1
        assert bars[0].low == pytest.approx(10.0)
        assert bars[0].high == pytest.approx(10.1)
        assert bars[0].volume == pytest.approx(1_000_150)
