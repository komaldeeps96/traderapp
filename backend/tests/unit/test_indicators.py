"""Indicator maths."""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.bars import Bar
from app.domain.sessions import ny_date
from app.indicators.functions import (
    compress_steps,
    ema,
    ema_last,
    premarket_bounds,
    premarket_bounds_last,
    rolling_max,
    rolling_min,
    session_bounds,
    session_bounds_last,
    session_level_series,
    session_levels,
    session_vwap,
    session_vwap_last,
    sma,
    sma_last,
    to_series,
)
from tests.conftest import make_bar, ny_epoch


class TestSMA:
    def test_is_undefined_before_the_window_fills(self):
        assert sma([1, 2, 3, 4], 3)[:2] == [None, None]

    def test_averages_the_trailing_window(self):
        assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]

    def test_returns_all_none_when_shorter_than_the_window(self):
        assert sma([1, 2], 5) == [None, None]

    def test_rejects_a_non_positive_window(self):
        assert sma([1, 2, 3], 0) == [None, None, None]


class TestEMA:
    def test_seeds_with_the_sma_of_the_first_span(self):
        # TradingView's convention: the first defined point is a plain mean.
        values = [10.0, 12.0, 14.0, 16.0]
        assert ema(values, 3)[2] == pytest.approx(12.0)

    def test_follows_the_standard_recurrence_after_seeding(self):
        values = [10.0, 12.0, 14.0, 16.0]
        alpha = 2 / 4
        expected = alpha * 16.0 + (1 - alpha) * 12.0
        assert ema(values, 3)[3] == pytest.approx(expected)

    def test_is_undefined_before_the_span_fills(self):
        assert ema([1.0, 2.0, 3.0], 3)[:2] == [None, None]

    def test_converges_toward_a_constant_input(self):
        result = ema([5.0] * 50, 10)
        assert result[-1] == pytest.approx(5.0)

    def test_tracks_price_more_closely_at_a_shorter_span(self):
        prices = [float(i) for i in range(1, 60)]
        fast = ema(prices, 5)[-1]
        slow = ema(prices, 30)[-1]
        assert fast is not None and slow is not None
        assert abs(prices[-1] - fast) < abs(prices[-1] - slow)


class TestRollingExtremes:
    def test_rolling_max_uses_only_the_window(self):
        assert rolling_max([1, 5, 2, 3, 1], 3) == [None, None, 5, 5, 3]

    def test_rolling_min_uses_only_the_window(self):
        assert rolling_min([4, 1, 6, 3, 9], 3) == [None, None, 1, 1, 3]

    def test_window_of_one_returns_the_input(self):
        assert rolling_max([3, 1, 2], 1) == [3, 1, 2]

    def test_handles_a_window_longer_than_the_data(self):
        assert rolling_max([1, 2], 10) == [None, None]


class TestSessionVWAP:
    def test_first_bar_equals_its_own_typical_price(self):
        bar = Bar(time=ny_epoch(2024, 3, 5, 9, 30), open=10, high=12, low=8, close=10, volume=100)
        assert session_vwap([bar])[0] == pytest.approx(10.0)

    def test_weights_by_volume(self):
        start = ny_epoch(2024, 3, 5, 9, 30)
        bars = [
            Bar(time=start, open=10, high=10, low=10, close=10, volume=100),
            Bar(time=start + 60, open=20, high=20, low=20, close=20, volume=300),
        ]
        # (10*100 + 20*300) / 400
        assert session_vwap(bars)[1] == pytest.approx(17.5)

    def test_resets_at_the_start_of_each_new_york_day(self):
        day_one = ny_epoch(2024, 3, 5, 10, 0)
        day_two = ny_epoch(2024, 3, 6, 10, 0)
        bars = [
            Bar(time=day_one, open=10, high=10, low=10, close=10, volume=1000),
            Bar(time=day_two, open=50, high=50, low=50, close=50, volume=10),
        ]
        # Without a reset the huge day-one volume would dominate day two.
        assert session_vwap(bars)[1] == pytest.approx(50.0)

    def test_does_not_reset_across_utc_midnight_within_one_session(self):
        # 20:00 NY is 01:00 UTC the next day — same trading session.
        evening = ny_epoch(2024, 3, 5, 19, 0)
        later = ny_epoch(2024, 3, 5, 19, 30)
        bars = [
            Bar(time=evening, open=10, high=10, low=10, close=10, volume=100),
            Bar(time=later, open=20, high=20, low=20, close=20, volume=100),
        ]
        assert session_vwap(bars)[1] == pytest.approx(15.0)

    def test_is_undefined_with_no_volume(self):
        bar = Bar(time=ny_epoch(2024, 3, 5, 9, 30), open=10, high=10, low=10, close=10, volume=0)
        assert session_vwap([bar]) == [None]

    def test_anchors_at_0400_not_new_york_midnight(self):
        """A 02:00 print must not seed the day's VWAP.

        The line earns its place through polarity — above is bullish, below
        bearish — and that only holds if it is the same line everyone else
        is watching. Folding in an overnight print makes it a different
        quantity with the same name.
        """
        bars = [
            Bar(time=ny_epoch(2024, 3, 5, 2, 0), open=99, high=99, low=99, close=99, volume=1000),
            Bar(time=ny_epoch(2024, 3, 5, 5, 0), open=10, high=10, low=10, close=10, volume=100),
        ]
        values = session_vwap(bars)
        assert values[0] is None
        assert values[1] == pytest.approx(10.0)

    def test_excludes_prints_after_the_2000_close(self):
        bars = [
            Bar(time=ny_epoch(2024, 3, 5, 19, 0), open=10, high=10, low=10, close=10, volume=100),
            Bar(time=ny_epoch(2024, 3, 5, 21, 0), open=90, high=90, low=90, close=90, volume=900),
        ]
        values = session_vwap(bars)
        assert values[0] == pytest.approx(10.0)
        assert values[1] is None

    def test_the_premarket_session_seeds_the_regular_one(self):
        """04:00-20:00 is one anchor, not three."""
        bars = [
            Bar(time=ny_epoch(2024, 3, 5, 5, 0), open=10, high=10, low=10, close=10, volume=100),
            Bar(time=ny_epoch(2024, 3, 5, 10, 0), open=20, high=20, low=20, close=20, volume=100),
        ]
        assert session_vwap(bars)[1] == pytest.approx(15.0)


class TestSeriesAndLiveAgree:
    """The drawn line and the live update must compute the same thing.

    They did not: the series cleared its seed at the day rollover while the
    live path added it to today's bars, so every tick jumped. Any future
    divergence shows up as a step on the chart the moment live bars arrive,
    which is exactly what it looked like.
    """

    @staticmethod
    def spanning_two_days() -> list[Bar]:
        """The real shape: a 12-hour window reaches yesterday's after-hours."""
        return [
            Bar(time=ny_epoch(2024, 3, 4, 17, 0), open=20, high=20, low=20, close=20, volume=50_000),
            Bar(time=ny_epoch(2024, 3, 4, 19, 0), open=22, high=22, low=22, close=22, volume=50_000),
            Bar(time=ny_epoch(2024, 3, 5, 4, 0), open=10, high=10, low=10, close=10, volume=1_000),
            Bar(time=ny_epoch(2024, 3, 5, 9, 30), open=12, high=12, low=12, close=12, volume=1_000),
        ]

    def test_vwap_matches(self):
        bars = self.spanning_two_days()
        assert session_vwap(bars)[-1] == pytest.approx(session_vwap_last(bars))

    def test_vwap_uses_today_only(self):
        """Yesterday's 50,000-share bars must not weigh on today's average."""
        bars = self.spanning_two_days()
        assert session_vwap_last(bars) == pytest.approx((10 * 1000 + 12 * 1000) / 2000)

    def test_bounds_match(self):
        bars = self.spanning_two_days()
        highs, lows = session_bounds(bars)
        assert (highs[-1], lows[-1]) == session_bounds_last(bars)

    def test_bounds_use_today_only(self):
        bars = self.spanning_two_days()
        assert session_bounds_last(bars) == (12, 10)


class TestSessionBounds:
    def test_tracks_the_running_high_and_low(self):
        start = ny_epoch(2024, 3, 5, 9, 30)
        bars = [
            Bar(time=start, open=10, high=11, low=9, close=10, volume=10),
            Bar(time=start + 60, open=10, high=15, low=10, close=14, volume=10),
            Bar(time=start + 120, open=14, high=14, low=6, close=8, volume=10),
        ]
        highs, lows = session_bounds(bars)
        assert highs == [11, 15, 15]
        assert lows == [9, 9, 6]

    def test_includes_the_premarket_so_a_gapper_keeps_its_high(self):
        """On a gapper the pre-market high often *is* the high of day."""
        bars = [
            Bar(time=ny_epoch(2024, 3, 5, 7, 0), open=9, high=20, low=8, close=10, volume=10),
            Bar(time=ny_epoch(2024, 3, 5, 10, 0), open=10, high=12, low=9, close=11, volume=10),
        ]
        highs, _ = session_bounds(bars)
        assert highs == [20, 20]

    def test_resets_each_day(self):
        bars = [
            Bar(time=ny_epoch(2024, 3, 5, 10, 0), open=10, high=50, low=9, close=10, volume=10),
            Bar(time=ny_epoch(2024, 3, 6, 10, 0), open=10, high=12, low=9, close=11, volume=10),
        ]
        highs, _ = session_bounds(bars)
        assert highs == [50, 12]

    def test_ignores_bars_outside_the_session(self):
        bars = [
            Bar(time=ny_epoch(2024, 3, 5, 2, 0), open=99, high=99, low=99, close=99, volume=10),
            Bar(time=ny_epoch(2024, 3, 5, 10, 0), open=10, high=12, low=9, close=11, volume=10),
        ]
        highs, _ = session_bounds(bars)
        assert highs == [None, 12]


class TestPremarketBounds:
    def test_broadcasts_the_settled_range_across_the_whole_day(self):
        bars = [
            Bar(time=ny_epoch(2024, 3, 5, 5, 0), open=9, high=11, low=8, close=10, volume=10),
            Bar(time=ny_epoch(2024, 3, 5, 8, 0), open=10, high=12, low=9, close=11, volume=10),
            Bar(time=ny_epoch(2024, 3, 5, 14, 0), open=11, high=20, low=1, close=15, volume=10),
        ]
        highs, lows = premarket_bounds(bars)
        # The 14:00 regular-hours bar still carries the pre-market range, and
        # its own extremes do not widen it.
        assert highs == [12, 12, 12]
        assert lows == [8, 8, 8]

    def test_is_undefined_for_a_day_with_no_premarket_bars(self):
        bars = [Bar(time=ny_epoch(2024, 3, 5, 14, 0), open=1, high=2, low=0, close=1, volume=1)]
        highs, lows = premarket_bounds(bars)
        assert highs == [None] and lows == [None]

    def test_keeps_days_separate(self):
        bars = [
            Bar(time=ny_epoch(2024, 3, 5, 5, 0), open=9, high=11, low=8, close=10, volume=10),
            Bar(time=ny_epoch(2024, 3, 6, 5, 0), open=20, high=25, low=19, close=22, volume=10),
        ]
        highs, _ = premarket_bounds(bars)
        assert highs == [11, 25]


class TestCompressSteps:
    def test_keeps_only_the_ends_of_a_constant_run(self):
        points = [(1, 5.0), (2, 5.0), (3, 5.0)]
        assert compress_steps(points) == [(1, 5.0), (3, 5.0)]

    def test_marks_the_boundary_between_runs(self):
        points = [(1, 5.0), (2, 5.0), (3, 9.0), (4, 9.0)]
        assert compress_steps(points) == [(1, 5.0), (2, 5.0), (3, 9.0), (4, 9.0)]

    def test_drops_undefined_points(self):
        points = [(1, None), (2, 7.0), (3, 7.0)]
        assert compress_steps(points) == [(2, 7.0), (3, 7.0)]

    def test_keeps_a_lone_point(self):
        assert compress_steps([(1, 3.0)]) == [(1, 3.0)]

    def test_is_empty_for_all_undefined(self):
        assert compress_steps([(1, None), (2, None)]) == []

    def test_shrinks_a_full_day_of_one_level_to_two_points(self):
        points = [(i * 60, 42.0) for i in range(960)]
        assert len(compress_steps(points)) == 2


class TestToSeries:
    def test_pairs_times_with_values_and_drops_gaps(self):
        bars = [make_bar(60, 1.0), make_bar(120, 2.0), make_bar(180, 3.0)]
        assert to_series(bars, [None, 5.0, 6.0]) == [(120, 5.0), (180, 6.0)]


class TestSingleValueVariants:
    """The cheap paths used by the 1 Hz update loop must match the full ones."""

    def test_sma_last_matches_sma(self):
        values = [float(i % 13) for i in range(200)]
        assert sma_last(values, 20) == pytest.approx(sma(values, 20)[-1])

    def test_ema_last_matches_ema(self):
        values = [float((i * 7) % 23) for i in range(300)]
        assert ema_last(values, 9) == pytest.approx(ema(values, 9)[-1])

    def test_ema_last_is_undefined_when_ema_is(self):
        assert ema_last([1.0, 2.0], 5) is None

    def test_session_vwap_last_matches_session_vwap(self, minute_bars):
        assert session_vwap_last(minute_bars) == pytest.approx(session_vwap(minute_bars)[-1])

    def test_session_vwap_last_only_uses_the_current_day(self):
        bars = [
            Bar(time=ny_epoch(2024, 3, 5, 10, 0), open=10, high=10, low=10, close=10, volume=9999),
            Bar(time=ny_epoch(2024, 3, 6, 10, 0), open=40, high=40, low=40, close=40, volume=1),
        ]
        assert session_vwap_last(bars) == pytest.approx(40.0)

    def test_session_bounds_last_matches_the_full_computation(self, minute_bars):
        highs, lows = session_bounds(minute_bars)
        assert session_bounds_last(minute_bars) == (highs[-1], lows[-1])

    def test_session_bounds_last_only_uses_the_current_day(self):
        bars = [
            Bar(time=ny_epoch(2024, 3, 5, 10, 0), open=10, high=99, low=1, close=10, volume=10),
            Bar(time=ny_epoch(2024, 3, 6, 10, 0), open=40, high=42, low=38, close=40, volume=10),
        ]
        assert session_bounds_last(bars) == (42, 38)

    def test_premarket_last_matches_the_full_computation(self):
        bars = [
            Bar(time=ny_epoch(2024, 3, 5, 5, 0), open=9, high=11, low=8, close=10, volume=10),
            Bar(time=ny_epoch(2024, 3, 5, 14, 0), open=11, high=20, low=1, close=15, volume=10),
        ]
        highs, lows = premarket_bounds(bars)
        assert premarket_bounds_last(bars) == (highs[-1], lows[-1])


class TestMACD:
    def test_undefined_until_the_slow_ema_fills(self):
        from app.indicators.functions import macd

        closes = [float(i) for i in range(40)]
        macd_line, signal_line, histogram = macd(closes)
        assert macd_line[24] is None
        assert macd_line[25] is not None
        # Signal needs nine defined MACD values to seed.
        assert signal_line[32] is None
        assert signal_line[33] is not None
        assert histogram[33] == pytest.approx(macd_line[33] - signal_line[33])

    def test_flat_prices_give_a_zero_macd(self):
        from app.indicators.functions import macd

        macd_line, signal_line, _ = macd([5.0] * 60)
        assert macd_line[-1] == pytest.approx(0.0)
        assert signal_line[-1] == pytest.approx(0.0)

    def test_rising_prices_give_a_positive_macd(self):
        from app.indicators.functions import macd

        macd_line, _, _ = macd([float(i) for i in range(60)])
        assert macd_line[-1] > 0

    def test_last_matches_the_full_series(self):
        from app.indicators.functions import macd, macd_last

        closes = [100.0 + (i % 7) * 0.9 for i in range(80)]
        macd_line, signal_line, histogram = macd(closes)
        last = macd_last(closes)
        assert last[0] == pytest.approx(macd_line[-1])
        assert last[1] == pytest.approx(signal_line[-1])
        assert last[2] == pytest.approx(histogram[-1])

    def test_short_series_returns_nones(self):
        from app.indicators.functions import macd_last

        assert macd_last([1.0, 2.0]) == (None, None, None)


class TestSessionLevels:
    """PM open, RTH open, and the previous session's after-hours extremes."""

    @staticmethod
    def bars() -> list[Bar]:
        def bar(day, hour, minute, price):
            return Bar(time=ny_epoch(2024, 3, day, hour, minute), open=price,
                       high=price + 0.5, low=price - 0.5, close=price, volume=100)
        return [
            bar(4, 10, 0, 20.0),      # prior regular session
            bar(4, 17, 0, 22.0),      # prior after-hours
            bar(4, 19, 0, 25.0),      # prior after-hours, the high
            bar(5, 5, 0, 30.0),       # today, pre-market open
            bar(5, 7, 0, 33.0),
            bar(5, 9, 30, 35.0),      # today, regular open
            bar(5, 11, 0, 40.0),
        ]

    def levels(self):
        from datetime import date

        return session_levels(self.bars(), date(2024, 3, 5))

    def test_pm_open_is_the_first_premarket_print(self):
        assert self.levels().pm_open.value == pytest.approx(30.0)

    def test_rth_open_is_the_0930_print_not_the_days_first(self):
        assert self.levels().rth_open.value == pytest.approx(35.0)

    def test_after_hours_comes_from_the_previous_session(self):
        """Not today's — today's has not happened yet during the session."""
        levels = self.levels()
        assert levels.ah_high.value == pytest.approx(25.5)
        assert levels.ah_low.value == pytest.approx(21.5)

    def test_the_regular_open_is_undefined_before_0930(self):
        """Drawing it across the pre-market would show a price that did not
        exist yet, and would repaint the moment the bell rang."""
        today = [b for b in self.bars() if ny_date(b.time) == date(2024, 3, 5)]
        series = session_level_series(today, self.levels().rth_open)
        assert series[0] is None and series[1] is None      # 05:00 and 07:00
        assert series[2] == pytest.approx(35.0)             # 09:30 onward

    def test_a_day_with_no_prior_after_hours_yields_nothing(self):
        from datetime import date

        only_today = [b for b in self.bars() if ny_date(b.time) == date(2024, 3, 5)]
        assert session_levels(only_today, date(2024, 3, 5)).ah_high.value is None
