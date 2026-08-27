"""Windowed relative volume: the time-matched comparison and its refusals."""

from __future__ import annotations

import pytest

from app.domain.bars import Bar
from app.indicators.functions import windowed_rvol, windowed_rvol_last

# Monday 2026-08-17, 4:00 ET pre-market open (EDT: 08:00 UTC).
PRE_OPEN = 1_786_694_400
DAY = 86_400


def bar(t: int, v: float) -> Bar:
    return Bar(time=t, open=10, high=10, low=10, close=10, volume=v, trades=1)


def session(day: int, count: int, v: float, start_offset: int = 0) -> list[Bar]:
    """``count`` minute bars from a day's 4:00 ET open, constant volume."""
    return [bar(PRE_OPEN + day * DAY + start_offset + i * 60, v) for i in range(count)]


class TestWindowedRvol:
    def test_compares_the_same_time_of_day_not_the_whole_day(self):
        # Yesterday ran 100/min for an hour; today runs 200/min. Thirty
        # minutes in the honest read is 2.0x — a whole-day comparison
        # would have said 1.0x.
        minutes = session(0, 60, 100) + session(1, 30, 200)
        (value,) = windowed_rvol(minutes[-1:], minutes)
        assert value == pytest.approx(2.0)

    def test_averages_every_comparable_prior_day(self):
        minutes = session(0, 30, 100) + session(1, 30, 300) + session(2, 30, 200)
        (value,) = windowed_rvol(minutes[-1:], minutes)
        assert value == pytest.approx(1.0)  # 6000 / mean(3000, 9000)

    def test_the_first_day_has_no_answer(self):
        minutes = session(0, 30, 100)
        assert windowed_rvol_last(minutes, minutes) is None

    def test_a_fetch_truncated_day_is_excluded(self):
        truncated = session(0, 30, 100, start_offset=6 * 3600)  # starts 10:00 ET
        full = session(1, 60, 100)
        today = session(2, 30, 100)
        minutes = truncated + full + today
        assert windowed_rvol_last(minutes, minutes) == pytest.approx(1.0)
        # With ONLY the truncated day behind it: silence, not a fake signal.
        thin = truncated + today
        assert windowed_rvol_last(thin, thin) is None

    def test_past_a_prior_close_the_full_day_is_the_window(self):
        minutes = session(0, 30, 100) + session(1, 46, 100)
        assert windowed_rvol_last(minutes, minutes) == pytest.approx(4600 / 3000)

    def test_stamps_ten_second_bars_from_the_minute_base(self):
        """A 10s chart bar mid-minute reads the last completed minute's
        cumulative — up to a minute of lag, in exchange for history the
        10-second window cannot hold."""
        minutes = session(0, 60, 100) + session(1, 30, 200)
        tensec_time = PRE_OPEN + DAY + 29 * 60 + 30  # 30s into minute 29
        (value,) = windowed_rvol([bar(tensec_time, 33)], minutes)
        assert value == pytest.approx(2.0)

    def test_a_day_the_minute_base_lacks_is_none(self):
        minutes = session(0, 60, 100)
        stray = bar(PRE_OPEN + 5 * DAY, 10)
        (value,) = windowed_rvol([stray], minutes)
        assert value is None
