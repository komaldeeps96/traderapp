"""Windowed relative volume: the time-matched comparison and its refusals."""

from __future__ import annotations

import pytest

from app.domain.bars import Bar
from app.indicators.functions import (
    _arith_day,
    _daily_bar_day,
    windowed_rvol,
    windowed_rvol_last,
)

# Monday 2026-08-17, 4:00 ET pre-market open (EDT: 08:00 UTC).
PRE_OPEN = 1_786_694_400
DAY = 86_400


def bar(t: int, v: float) -> Bar:
    return Bar(time=t, open=10, high=10, low=10, close=10, volume=v, trades=1)


def session(day: int, count: int, v: float, start_offset: int = 0) -> list[Bar]:
    """``count`` minute bars from a day's 4:00 ET open, constant volume."""
    return [bar(PRE_OPEN + day * DAY + start_offset + i * 60, v) for i in range(count)]


def daily(day: int, volume: float) -> Bar:
    """A daily bar for ``day``, stamped at New York midnight like the resampler."""
    return bar(PRE_OPEN + day * DAY - 4 * 3600, volume)


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

    def test_one_wild_session_no_longer_swallows_the_reading(self):
        """A mean denominator lets a single 30x day quietly halve every
        reading for a week afterwards — the same contamination that makes a
        50-day average punish a stock for having recently been interesting.
        Today at an ordinary pace should read 1x, not 0.09x."""
        minutes = (
            session(0, 30, 100)
            + session(1, 30, 100)
            + session(2, 30, 3000)  # a 30x day
            + session(3, 30, 100)  # today, back to normal
        )
        assert windowed_rvol_last(minutes, minutes) == pytest.approx(1.0)


class TestDailyBaseDenominator:
    """The denominator reaches past the minute base into the daily one.

    The minute fetch covers about five sessions, on purpose: a wider one
    costs several Alpaca pages on every ticker switch. The daily base is
    already loaded years deep, so the level of each older session comes from
    there and only the *shape* — the fraction of a day's volume done by this
    time — is measured on the minute base.
    """

    # Day 0 runs 100/min for an hour, so its cumulative at minute 29 is
    # 3,000 against a 6,000-share session: a shape of 0.5. Today runs
    # 200/min, so 6,000 by the same minute.
    MINUTES = session(0, 60, 100) + session(1, 30, 200)

    def test_older_sessions_reach_the_denominator_through_their_shape(self):
        dailies = [
            daily(-2, 24_000),  # projects to 12,000 at half the session
            daily(-1, 20_000),  # projects to 10,000
            daily(0, 6_000),  # calibrates the shape
        ]
        # median(3,000 direct, 10,000, 12,000) = 10,000.
        value = windowed_rvol_last(self.MINUTES[-1:], self.MINUTES, dailies)
        assert value == pytest.approx(0.6)
        # Without them the single covered session is the whole comparison.
        assert windowed_rvol_last(self.MINUTES[-1:], self.MINUTES) == pytest.approx(2.0)

    def test_a_session_the_minute_base_covers_is_not_counted_twice(self):
        """Day 0 has both bases. Counting it once directly and again as a
        projection would pull the median toward a day already represented."""
        dailies = [daily(-2, 24_000), daily(-1, 20_000), daily(0, 6_000)]
        assert windowed_rvol_last(self.MINUTES[-1:], self.MINUTES, dailies) == pytest.approx(0.6)

    def test_todays_own_daily_bar_is_not_a_comparison(self):
        """Today's session is the numerator. Letting it into the denominator
        would drag the reading toward 1x exactly when it should be loudest."""
        without = [daily(-1, 20_000), daily(0, 6_000)]
        with_today = [*without, daily(1, 999_000_000)]
        assert windowed_rvol_last(
            self.MINUTES[-1:], self.MINUTES, with_today
        ) == pytest.approx(windowed_rvol_last(self.MINUTES[-1:], self.MINUTES, without))

    def test_without_a_calibrating_session_nothing_is_projected(self):
        """No day carries both bases, so there is no shape to scale a daily
        volume by. Silence beats inventing one."""
        dailies = [daily(-2, 24_000), daily(-1, 20_000)]
        assert windowed_rvol_last(self.MINUTES[-1:], self.MINUTES, dailies) == pytest.approx(2.0)

    def test_a_zero_volume_session_does_not_calibrate_a_shape(self):
        """A halted or untraded session has a daily bar and no volume; it
        must not become a division by zero or an infinite shape."""
        dailies = [daily(-1, 20_000), daily(0, 0)]
        assert windowed_rvol_last(self.MINUTES[-1:], self.MINUTES, dailies) == pytest.approx(2.0)

    def test_the_window_is_the_most_recent_fifty_sessions(self):
        """The daily base runs forty years deep. Reaching all of it would
        compare a runner against its pre-listing history."""
        recent = [daily(-day, 20_000) for day in range(1, 51)]
        ancient = [daily(-day, 900_000_000) for day in range(51, 90)]
        dailies = [daily(0, 6_000), *recent, *ancient]
        capped = windowed_rvol_last(self.MINUTES[-1:], self.MINUTES, dailies)
        assert capped == pytest.approx(
            windowed_rvol_last(self.MINUTES[-1:], self.MINUTES, [daily(0, 6_000), *recent])
        )


class TestMemoisation:
    """Each denominator walks up to fifty sessions, so it is cached per
    (day, minute). What matters is that the key is complete: a cache that
    ignored the day would serve yesterday's comparison to today's bars.
    """

    def test_a_ten_second_series_reads_the_same_as_its_minutes(self):
        minutes = session(0, 60, 100) + session(1, 30, 200)
        dailies = [daily(-1, 20_000), daily(0, 6_000)]
        # Six 10-second bars inside minute 29, all sharing one lookup.
        tens = [bar(PRE_OPEN + DAY + 29 * 60 + step * 10, 33) for step in range(6)]
        values = windowed_rvol(tens, minutes, dailies)
        expected = windowed_rvol(minutes[-1:], minutes, dailies)[0]
        assert values == [pytest.approx(expected)] * 6

    def test_two_days_do_not_share_a_denominator(self):
        """Both readings come out of one call, so a cache keyed on the minute
        alone would serve day 1's comparison to day 2's bars."""
        minutes = session(0, 30, 100) + session(1, 30, 900) + session(2, 30, 100)
        first, second = windowed_rvol([minutes[59], minutes[-1]], minutes)
        assert first == pytest.approx(9.0)  # 27,000 over day 0's 3,000
        assert second == pytest.approx(0.2)  # 3,000 over median(3,000, 27,000)

    def test_a_prior_session_that_had_not_started_yet_is_skipped(self):
        """The older day opens five minutes later. Before its first print it
        has no cumulative to compare against — counting it as zero would read
        as an infinite pace — and after it, it is genuinely five minutes
        behind, which is the whole point of matching on the clock."""
        late = [bar(PRE_OPEN + 300 + i * 60, 100) for i in range(30)]  # opens 4:05
        today = session(1, 30, 100)
        minutes = late + today
        assert windowed_rvol([today[0]], minutes) == [None]
        # By 4:29 today has done 3,000 and the late day had done 2,500.
        assert windowed_rvol([today[-1]], minutes)[0] == pytest.approx(1.2)


class TestDayJoin:
    """Daily bars anchor to New York midnight and intraday bars to the
    session, so the two bases have to be shown to agree about which day they
    mean — under both offsets, because a naive join is off by one all summer.
    """

    @pytest.mark.parametrize(
        ("label", "midnight_utc"),
        [
            ("EST", 1_768_453_200),  # 2026-01-15 00:00 ET = 05:00 UTC
            ("EDT", 1_784_088_000),  # 2026-07-15 00:00 ET = 04:00 UTC
        ],
    )
    def test_a_daily_bar_lands_on_its_own_session(self, label, midnight_utc):
        four_am = midnight_utc + 4 * 3600
        assert _daily_bar_day(midnight_utc) == _arith_day(four_am), label
