"""Deriving higher timeframes from base bars."""

from __future__ import annotations

import pytest

from app.core.clock import to_ny
from app.domain.bars import Bar
from app.domain.timeframes import Timeframe
from app.market.resample import bucket_start, derive, resample
from tests.conftest import make_minute_series, ny_epoch


class TestBucketStart:
    def test_ten_second_buckets_align_to_ten_second_marks(self):
        moment = ny_epoch(2024, 3, 5, 9, 32) + 47
        assert bucket_start(moment, Timeframe.S10) == ny_epoch(2024, 3, 5, 9, 32) + 40

    def test_ten_second_boundary_opens_its_own_bucket(self):
        moment = ny_epoch(2024, 3, 5, 9, 32) + 40
        assert bucket_start(moment, Timeframe.S10) == moment

    def test_five_minute_buckets_align_to_the_clock(self):
        moment = ny_epoch(2024, 3, 5, 9, 32)
        assert bucket_start(moment, Timeframe.M5) == ny_epoch(2024, 3, 5, 9, 30)

    def test_fifteen_minute_buckets_align_to_the_clock(self):
        moment = ny_epoch(2024, 3, 5, 9, 44)
        assert bucket_start(moment, Timeframe.M15) == ny_epoch(2024, 3, 5, 9, 30)

    def test_thirty_minute_buckets_align_to_the_half_hour(self):
        moment = ny_epoch(2024, 3, 5, 9, 44)
        assert bucket_start(moment, Timeframe.M30) == ny_epoch(2024, 3, 5, 9, 30)

    def test_hour_buckets_align_to_the_hour(self):
        moment = ny_epoch(2024, 3, 5, 10, 37)
        assert bucket_start(moment, Timeframe.H1) == ny_epoch(2024, 3, 5, 10, 0)

    def test_four_hour_buckets_split_the_new_york_day(self):
        # 08:00-12:00 holds the open; the pre-market gets 04:00-08:00 of its
        # own rather than being folded in with it.
        assert bucket_start(ny_epoch(2024, 3, 5, 10, 37), Timeframe.H4) == ny_epoch(
            2024, 3, 5, 8, 0
        )
        assert bucket_start(ny_epoch(2024, 3, 5, 7, 59), Timeframe.H4) == ny_epoch(
            2024, 3, 5, 4, 0
        )
        assert bucket_start(ny_epoch(2024, 3, 5, 15, 59), Timeframe.H4) == ny_epoch(
            2024, 3, 5, 12, 0
        )

    def test_four_hour_buckets_hold_that_split_through_the_winter(self):
        # The reason these are anchored to the local day: on UTC boundaries a
        # four-hour bar opens at 04:00 New York in July and 03:00 in January,
        # so the pre-market bar would move under the trader twice a year.
        january = ny_epoch(2024, 1, 10, 10, 37)
        assert bucket_start(january, Timeframe.H4) == ny_epoch(2024, 1, 10, 8, 0)

    def test_a_bar_on_the_boundary_opens_its_own_bucket(self):
        moment = ny_epoch(2024, 3, 5, 9, 30)
        assert bucket_start(moment, Timeframe.M5) == moment

    def test_daily_buckets_use_new_york_midnight(self):
        # 19:00 NY is already the next UTC day; it must stay on the 5th.
        evening = ny_epoch(2024, 3, 5, 19, 0)
        assert to_ny(bucket_start(evening, Timeframe.D1)).date().day == 5

    def test_weekly_buckets_start_on_monday(self):
        wednesday = ny_epoch(2024, 3, 6, 12, 0)
        start = bucket_start(wednesday, Timeframe.W1)
        assert to_ny(start).weekday() == 0
        assert to_ny(start).date().day == 4


class TestResample:
    def test_folds_five_one_minute_bars_into_one(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0, 11.0, 12.0, 13.0, 14.0])
        result = resample(bars, Timeframe.M5)
        assert len(result) == 1

    def test_takes_open_from_the_first_and_close_from_the_last(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0, 11.0, 12.0, 13.0, 14.0])
        folded = resample(bars, Timeframe.M5)[0]
        assert folded.open == pytest.approx(bars[0].open)
        assert folded.close == pytest.approx(bars[-1].close)

    def test_takes_the_extremes_of_the_period(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0, 11.0, 12.0, 13.0, 14.0])
        folded = resample(bars, Timeframe.M5)[0]
        assert folded.high == pytest.approx(max(b.high for b in bars))
        assert folded.low == pytest.approx(min(b.low for b in bars))

    def test_sums_volume_and_trades(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0] * 5)
        folded = resample(bars, Timeframe.M5)[0]
        assert folded.volume == pytest.approx(sum(b.volume for b in bars))
        assert folded.trades == pytest.approx(sum(b.trades for b in bars))

    def test_starts_a_new_bucket_at_the_boundary(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [float(i) for i in range(10)])
        assert len(resample(bars, Timeframe.M5)) == 2

    def test_stamps_buckets_with_the_period_open(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [float(i) for i in range(10)])
        times = [bar.time for bar in resample(bars, Timeframe.M5)]
        assert times == [ny_epoch(2024, 3, 5, 9, 30), ny_epoch(2024, 3, 5, 9, 35)]

    def test_preserves_total_volume_across_any_timeframe(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [float(i % 7) for i in range(120)])
        total = sum(bar.volume for bar in bars)
        for timeframe in (Timeframe.M5, Timeframe.M15, Timeframe.H1):
            assert sum(b.volume for b in resample(bars, timeframe)) == pytest.approx(total)

    def test_is_empty_for_no_input(self):
        assert resample([], Timeframe.M5) == []

    def test_output_is_sorted(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [float(i) for i in range(60)])
        result = resample(list(reversed(bars)), Timeframe.M15)
        assert [b.time for b in result] == sorted(b.time for b in result)

    def test_partial_period_still_produces_a_bar(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0, 11.0])
        assert len(resample(bars, Timeframe.M5)) == 1


class TestDerive:
    def test_returns_base_bars_untouched(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [1.0, 2.0, 3.0])
        assert derive(bars, Timeframe.M1) == bars

    def test_copies_rather_than_aliasing_the_stored_list(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [1.0])
        assert derive(bars, Timeframe.M1) is not bars

    def test_resamples_a_derived_timeframe(self):
        bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [float(i) for i in range(15)])
        assert len(derive(bars, Timeframe.M5)) == 3

    def test_weekly_folds_daily_bars(self):
        # Mon-Fri then the following Monday: two weekly buckets.
        days = [
            Bar(time=ny_epoch(2024, 3, 4 + i, 0, 0), open=1, high=2, low=0, close=1, volume=1)
            for i in range(5)
        ]
        days.append(Bar(time=ny_epoch(2024, 3, 11, 0, 0), open=1, high=2, low=0, close=1, volume=1))
        assert len(derive(days, Timeframe.W1)) == 2
