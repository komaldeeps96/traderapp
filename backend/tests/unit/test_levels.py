"""Daily key levels.

The load-bearing rule is that a level for day D uses only daily bars that
closed *before* D. If that slips, levels repaint intraday — a "prev day close"
would drift as today trades, which is worse than not drawing it at all.
"""

from __future__ import annotations

from datetime import date

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
        ["prev_quarter_high", "prev_quarter_low", "prev_quarter_close",
         "prev_year_high", "prev_year_low", "prev_year_close"],
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
            open=close, high=close + 1, low=close - 1, close=close, volume=1_000,
        )

    def index(self):
        return DailyLevelIndex([
            self.day(2025, 2, 10, 50),
            self.day(2025, 5, 12, 80),
            self.day(2025, 11, 3, 60),
            self.day(2026, 2, 9, 30),
            self.day(2026, 5, 11, 40),
            self.day(2026, 8, 10, 45),
        ])

    def test_previous_quarter_is_the_one_before_this_one(self):
        # 13 Aug 2026 is Q3; the previous quarter is Q2, whose only bar
        # closed at 40 with a 39-41 range.
        idx, today = self.index(), date(2026, 8, 13)
        assert idx.value(LevelKey("prev_quarter_close"), today) == 40
        assert idx.value(LevelKey("prev_quarter_high"), today) == 41
        assert idx.value(LevelKey("prev_quarter_low"), today) == 39

    def test_previous_year_spans_the_whole_year(self):
        idx, today = self.index(), date(2026, 8, 13)
        assert idx.value(LevelKey("prev_year_high"), today) == 81     # May 2025
        assert idx.value(LevelKey("prev_year_low"), today) == 49      # Feb 2025
        assert idx.value(LevelKey("prev_year_close"), today) == 60    # Nov 2025

    def test_no_earlier_period_yields_none(self):
        idx = DailyLevelIndex([self.day(2026, 8, 10, 45)])
        assert idx.value(LevelKey("prev_year_close"), date(2026, 8, 13)) is None
