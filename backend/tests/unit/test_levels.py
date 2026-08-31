"""Daily key levels.

The load-bearing rule is that a level for day D uses only daily bars that
closed *before* D. If that slips, levels repaint intraday — a "prev day close"
would drift as today trades, which is worse than not drawing it at all.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.domain.bars import Bar
from app.indicators.levels import DailyLevelIndex, LevelKey, parse_level_key
from tests.conftest import ny_epoch


@pytest.fixture
def index(daily_bars):
    keys = {
        LevelKey("sma", 5),
        LevelKey("ema", 5),
        LevelKey("high", 3),
        LevelKey("low", 3),
        LevelKey("prev_day_high"),
        LevelKey("prev_day_low"),
        LevelKey("prev_day_close"),
        LevelKey("prev_week_high"),
        LevelKey("prev_week_low"),
        LevelKey("prev_week_close"),
        LevelKey("prev_month_high"),
        LevelKey("prev_month_close"),
    }
    return DailyLevelIndex(daily_bars, keys)


class TestPreviousDay:
    def test_uses_the_prior_trading_day(self, index):
        # Bars run weekdays from 2024-01-08 with closes 90.0 + 0.5 * i.
        # 2024-01-15 is the 6th bar, so the day before it is 2024-01-12.
        assert index.value(LevelKey("prev_day_close"), date(2024, 1, 15)) == pytest.approx(92.0)

    def test_skips_the_weekend(self, index):
        # The day before Monday the 15th is Friday the 12th, not Sunday.
        friday_close = index.value(LevelKey("prev_day_close"), date(2024, 1, 15))
        assert friday_close == pytest.approx(92.0)

    def test_is_undefined_before_any_data(self, index):
        assert index.value(LevelKey("prev_day_close"), date(2024, 1, 8)) is None

    def test_high_and_low_come_from_the_same_prior_bar(self, index):
        assert index.value(LevelKey("prev_day_high"), date(2024, 1, 15)) == pytest.approx(93.0)
        assert index.value(LevelKey("prev_day_low"), date(2024, 1, 15)) == pytest.approx(91.0)

    def test_does_not_include_its_own_day(self, index):
        """The rule that stops levels repainting."""
        same_day = index.value(LevelKey("prev_day_close"), date(2024, 1, 16))
        next_day = index.value(LevelKey("prev_day_close"), date(2024, 1, 17))
        assert same_day != next_day


class TestRollingLevels:
    def test_sma_uses_bars_up_to_the_prior_close(self, index):
        # As of 2024-01-16 the newest completed bar is the 15th (index 5),
        # so a 5-bar mean covers indices 1..5.
        assert index.value(LevelKey("sma", 5), date(2024, 1, 16)) == pytest.approx(91.5)

    def test_rolling_high_tracks_the_window(self, index):
        value = index.value(LevelKey("high", 3), date(2024, 1, 16))
        # Highs are close + 1; the newest three completed closes end at 92.5.
        assert value == pytest.approx(93.5)

    def test_rolling_low_tracks_the_window(self, index):
        value = index.value(LevelKey("low", 3), date(2024, 1, 16))
        # Lows are close - 1 over the newest three completed bars (91.5, 92.0,
        # 92.5), so the window minimum is 90.5.
        assert value == pytest.approx(90.5)

    def test_is_undefined_before_the_window_fills(self, index):
        assert index.value(LevelKey("sma", 5), date(2024, 1, 10)) is None

    def test_unrequested_keys_are_not_computed(self, daily_bars):
        sparse = DailyLevelIndex(daily_bars, {LevelKey("sma", 5)})
        assert sparse.value(LevelKey("ema", 20), date(2024, 2, 20)) is None


class TestPreviousWeekAndMonth:
    def test_previous_week_close_is_last_weeks_final_bar(self, index):
        # The week of Mon 2024-01-15 follows the week of Mon 2024-01-08,
        # which ended Friday the 12th at 92.0.
        assert index.value(LevelKey("prev_week_close"), date(2024, 1, 15)) == pytest.approx(92.0)

    def test_previous_week_high_spans_the_whole_week(self, index):
        assert index.value(LevelKey("prev_week_high"), date(2024, 1, 15)) == pytest.approx(93.0)

    def test_previous_week_low_spans_the_whole_week(self, index):
        assert index.value(LevelKey("prev_week_low"), date(2024, 1, 15)) == pytest.approx(89.0)

    def test_is_stable_all_week(self, index):
        monday = index.value(LevelKey("prev_week_close"), date(2024, 1, 15))
        thursday = index.value(LevelKey("prev_week_close"), date(2024, 1, 18))
        assert monday == thursday

    def test_previous_month_close_is_last_months_final_bar(self, index):
        february = index.value(LevelKey("prev_month_close"), date(2024, 2, 5))
        january = index.value(LevelKey("prev_day_close"), date(2024, 2, 1))
        assert february == pytest.approx(january)

    def test_previous_month_is_undefined_in_the_first_month(self, index):
        assert index.value(LevelKey("prev_month_close"), date(2024, 1, 10)) is None


class TestParseLevelKey:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("sma:20", LevelKey("sma", 20)),
            ("ema:200", LevelKey("ema", 200)),
            ("high:252", LevelKey("high", 252)),
            ("low:65", LevelKey("low", 65)),
            ("prev_day_close", LevelKey("prev_day_close")),
            ("PREV_WEEK_HIGH", LevelKey("prev_week_high")),
        ],
    )
    def test_parses_supported_forms(self, raw, expected):
        assert parse_level_key(raw) == expected

    @pytest.mark.parametrize(
        "raw", ["sma", "sma:0", "sma:x", "bogus", "prev_decade_close", "high:-5"]
    )
    def test_rejects_unsupported_forms(self, raw):
        with pytest.raises(ValueError):
            parse_level_key(raw)

    @pytest.mark.parametrize(
        "raw",
        [
            "prev_quarter_high",
            "prev_quarter_low",
            "prev_quarter_close",
            "prev_year_high",
            "prev_year_low",
            "prev_year_close",
        ],
    )
    def test_accepts_the_longer_periods(self, raw):
        assert parse_level_key(raw) == LevelKey(raw)


class TestEmptyIndex:
    def test_returns_none_for_everything(self):
        empty = DailyLevelIndex([], {LevelKey("sma", 20)})
        assert empty.value(LevelKey("sma", 20), date(2024, 3, 5)) is None
        assert empty.value(LevelKey("prev_day_close"), date(2024, 3, 5)) is None


class TestLongerPeriods:
    """Quarter and year, on the same machinery as week and month."""

    @staticmethod
    def day(year: int, month: int, dom: int, close: float):
        return Bar(
            time=ny_epoch(year, month, dom, 16, 0),
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=1_000,
        )

    def index(self):
        return DailyLevelIndex(
            [
                self.day(2025, 2, 10, 50),
                self.day(2025, 5, 12, 80),
                self.day(2025, 11, 3, 60),
                self.day(2026, 2, 9, 30),
                self.day(2026, 5, 11, 40),
                self.day(2026, 8, 10, 45),
            ]
        )

    def test_previous_quarter_is_the_one_before_this_one(self):
        # 13 Aug 2026 is Q3; the previous quarter is Q2, whose only bar
        # closed at 40 with a 39-41 range.
        idx, today = self.index(), date(2026, 8, 13)
        assert idx.value(LevelKey("prev_quarter_close"), today) == 40
        assert idx.value(LevelKey("prev_quarter_high"), today) == 41
        assert idx.value(LevelKey("prev_quarter_low"), today) == 39

    def test_previous_year_spans_the_whole_year(self):
        idx, today = self.index(), date(2026, 8, 13)
        assert idx.value(LevelKey("prev_year_high"), today) == 81  # May 2025
        assert idx.value(LevelKey("prev_year_low"), today) == 49  # Feb 2025
        assert idx.value(LevelKey("prev_year_close"), today) == 60  # Nov 2025

    def test_no_earlier_period_yields_none(self):
        idx = DailyLevelIndex([self.day(2026, 8, 10, 45)])
        assert idx.value(LevelKey("prev_year_close"), date(2026, 8, 13)) is None


class TestLookupShortcuts:
    """The bisect and the memo must agree with the obvious slow version.

    Both exist because a daily chart asks for a level once per bar rather
    than once per session, which turned a scan over every calendar bucket
    into the dominant cost of a snapshot. Speed-ups on a repainting rule are
    only safe if they are provably the same answer, so this pins them
    against a brute-force scan across the whole history rather than trusting
    the two spot checks the other suites happen to cover.
    """

    @staticmethod
    def _brute_previous(index, prefix, current):
        buckets = index._periods[prefix]
        earlier = [key for key in buckets if key < current]
        return buckets[max(earlier)] if earlier else None

    def test_previous_bucket_matches_a_full_scan(self, index):
        from app.indicators.levels import _PERIOD_BUCKETS

        for prefix, bucket_of in _PERIOD_BUCKETS:
            # Reach a year either side so the empty-history edge is covered.
            for ordinal in range(date(2023, 12, 1).toordinal(), date(2024, 6, 1).toordinal()):
                day = date.fromordinal(ordinal)
                expected = self._brute_previous(index, prefix, bucket_of(day))
                assert index._previous_bucket(prefix, bucket_of(day)) is expected

    def test_memoised_index_matches_a_fresh_search(self, index, daily_bars):
        cold = DailyLevelIndex(daily_bars)
        for ordinal in range(date(2023, 12, 1).toordinal(), date(2024, 6, 1).toordinal()):
            day = date.fromordinal(ordinal)
            # Ask twice: the second read comes from the cache, not the search.
            first = index._last_index_before(day)
            assert first == index._last_index_before(day)
            assert first == cold._last_index_before(day)


class TestCalendarWindows:
    """A "52-week high" is a claim about the calendar, not a bar count.

    252 bars approximates a year and drifts at the edge, which is exactly
    where a yearly extreme tends to sit: Celularity's 4.00 print was 366 days
    old, inside a 252-bar window and outside a 52-week one, and it made our
    high 27% higher than every other terminal's.
    """

    @staticmethod
    def bar(day: date, high: float, low: float | None = None) -> Bar:
        stamp = ny_epoch(day.year, day.month, day.day, 16, 0)
        return Bar(
            time=stamp,
            open=high,
            high=high,
            low=low if low is not None else high,
            close=high,
            volume=1_000,
        )

    def _series(self, entries: list[tuple[date, float]]) -> list[Bar]:
        return [self.bar(day, high) for day, high in entries]

    def test_a_price_older_than_the_window_falls_out(self):
        bars = self._series(
            [
                (date(2025, 1, 1), 100.0),  # 372 days before the last bar
                (date(2025, 6, 1), 50.0),
                (date(2026, 1, 8), 60.0),
            ]
        )
        index = DailyLevelIndex(bars, {LevelKey("high", 52, weeks=True)})
        assert index._rolling[LevelKey("high", 52, weeks=True)][-1] == 60.0

    def test_a_price_inside_the_window_is_kept(self):
        bars = self._series(
            [
                (date(2025, 2, 1), 100.0),  # 341 days back, still inside
                (date(2026, 1, 8), 60.0),
            ]
        )
        index = DailyLevelIndex(bars, {LevelKey("high", 52, weeks=True)})
        assert index._rolling[LevelKey("high", 52, weeks=True)][-1] == 100.0

    def test_the_far_edge_is_open(self):
        """A bar exactly 52 weeks old has left the window.

        Otherwise "52 weeks" quietly means 52 weeks and a day, which is the
        boundary case that started this.
        """
        last = date(2026, 1, 8)
        bars = self._series([(last - timedelta(weeks=52), 100.0), (last, 60.0)])
        index = DailyLevelIndex(bars, {LevelKey("high", 52, weeks=True)})
        assert index._rolling[LevelKey("high", 52, weeks=True)][-1] == 60.0

    def test_lows_use_the_same_window(self):
        bars = [
            self.bar(date(2025, 1, 1), 100.0, low=1.0),
            self.bar(date(2026, 1, 8), 60.0, low=50.0),
        ]
        index = DailyLevelIndex(bars, {LevelKey("low", 52, weeks=True)})
        assert index._rolling[LevelKey("low", 52, weeks=True)][-1] == 50.0

    def test_a_bar_count_still_counts_bars(self):
        """The old form has to keep working; moving averages depend on it."""
        bars = self._series([(date(2025, 1, 1), 100.0), (date(2026, 1, 8), 60.0)])
        index = DailyLevelIndex(bars, {LevelKey("high", 2)})
        # Two bars are inside a two-bar window however far apart in time,
        # which is the whole difference from a calendar span.
        assert index._rolling[LevelKey("high", 2)][-1] == 100.0

    def test_each_bar_gets_its_own_window(self):
        bars = self._series(
            [
                (date(2025, 1, 1), 100.0),
                (date(2025, 6, 1), 50.0),
                (date(2026, 1, 8), 60.0),
            ]
        )
        series = DailyLevelIndex(bars, {LevelKey("high", 52, weeks=True)})._rolling[
            LevelKey("high", 52, weeks=True)
        ]
        # The first two bars still see the 100; only the last has outrun it.
        assert series == [100.0, 100.0, 60.0]


class TestCalendarParsing:
    def test_a_week_suffix_is_calendar_time(self):
        key = parse_level_key("high:52w")
        assert (key.kind, key.span, key.weeks) == ("high", 52, True)

    def test_a_bare_number_is_still_bars(self):
        key = parse_level_key("high:252")
        assert (key.span, key.weeks) == (252, False)

    def test_an_average_cannot_span_weeks(self):
        """Averaging "the last 52 weeks of closes" is a different and
        stranger thing than the highest price in that time."""
        with pytest.raises(ValueError, match="calendar weeks"):
            parse_level_key("sma:52w")

    def test_the_key_prints_back_the_way_it_was_written(self):
        assert str(parse_level_key("high:52w")) == "high:52w"
        assert str(parse_level_key("low:130")) == "low:130"
