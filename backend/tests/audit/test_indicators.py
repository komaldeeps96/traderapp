"""The chart half, checked against somebody else's arithmetic.

The statements have published figures to be measured against. A moving
average over *our* bars does not — nobody else computes one. So this checks
the two things that can be checked, and keeps them apart on purpose:

**The bars agree.** If our closes differ from everyone else's, every
indicator drawn on them is wrong and nothing downstream is worth testing.

**The arithmetic lands where theirs does.** Given the same closes, our `sma`
and `ema` reproduce TradingView's published values — and they do, to the
cent: Apple's 20-day average is 309.86 on both sides.

Then a third thing, which is *design* rather than arithmetic: the level the
chart actually draws deliberately excludes today's bar, so it cannot repaint
while the session runs. That is a one-bar difference from every other
terminal and it is intentional, so it is asserted rather than tolerated.
"""

from __future__ import annotations

import math
from datetime import timedelta

import pytest

from app.domain.sessions import ny_date
from app.domain.timeframes import Timeframe
from app.indicators.engine import IndicatorEngine
from app.indicators.functions import ema, macd, rolling_max, rolling_min, sma
from app.indicators.levels import DailyLevelIndex, LevelKey
from app.indicators.spec import load_indicator_specs
from tests.audit.conftest import relative_difference
from tests.audit.universe import UNIVERSE

pytestmark = pytest.mark.audit


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


# US-listed and liquid enough that the feed has three years of daily bars.
SUBJECTS = [
    pytest.param(s, id=s.symbol) for s in UNIVERSE if s.country == "US" and not s.no_annual_filings
]

# Same closes, same formula: a real difference here is a bug in the maths,
# not a vendor disagreement. Left at a tenth of a percent to absorb the last
# decimal of a split adjustment.
ARITHMETIC_TOLERANCE = 0.001

# Prices themselves must agree outright.
PRICE_TOLERANCE = 0.0005


@pytest.fixture(scope="session")
def engine():
    from app.core.settings import CONFIG_DIR

    return IndicatorEngine(load_indicator_specs(CONFIG_DIR / "indicators.yaml"))


@pytest.fixture(scope="session")
def charts():
    """TradingView's own indicator values for the same symbols."""
    from tradingview_screener import Query, col

    columns = [
        "name",
        "close",
        "SMA20",
        "SMA50",
        "SMA200",
        "EMA20",
        "EMA50",
        "EMA200",
        "RSI",
        "price_52_week_high",
        "price_52_week_low",
    ]
    symbols = [subject.symbol for subject in UNIVERSE]
    _, frame = (
        Query().select(*columns).where(col("name").isin(symbols)).limit(100).get_scanner_data()
    )
    return {row["name"]: row for _, row in frame.iterrows()}


class TestTheBarsThemselves:
    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_our_last_close_is_everyone_elses(self, subject, daily_bars, charts):
        """Nothing downstream matters if the bars are wrong."""
        row = charts.get(subject.symbol)
        bars = daily_bars(subject.symbol)
        if row is None or not bars:
            pytest.skip(f"no data for {subject.symbol}")
        drift = relative_difference(bars[-1].close, float(row["close"]))
        assert drift <= PRICE_TOLERANCE, (
            f"{subject.symbol}: our close {bars[-1].close} vs {row['close']}"
        )

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_a_bar_is_internally_coherent(self, subject, daily_bars):
        """low <= open, close <= high, and volume is never negative.

        Cheap, and it catches a feed that has started interleaving symbols.
        """
        for bar in daily_bars(subject.symbol)[-250:]:
            assert bar.low <= bar.open <= bar.high, f"{subject.symbol} {bar.time}"
            assert bar.low <= bar.close <= bar.high, f"{subject.symbol} {bar.time}"
            assert bar.volume >= 0


class TestTheArithmetic:
    """Given the same closes, do we land where they land?"""

    @pytest.mark.parametrize("subject", SUBJECTS)
    @pytest.mark.parametrize(("window", "column"), [(20, "SMA20"), (50, "SMA50"), (200, "SMA200")])
    def test_simple_moving_averages_match(self, subject, daily_bars, charts, window, column):
        row = charts.get(subject.symbol)
        bars = daily_bars(subject.symbol)
        if row is None or len(bars) < window or not _is_number(row[column]):
            pytest.skip(f"no comparable {column} for {subject.symbol}")
        ours = sma([bar.close for bar in bars], window)[-1]
        drift = relative_difference(ours, float(row[column]))
        assert drift <= ARITHMETIC_TOLERANCE, (
            f"{subject.symbol} {column}: ours {ours:.4f} vs {row[column]:.4f} ({drift:.3%})"
        )

    @pytest.mark.parametrize("subject", SUBJECTS)
    @pytest.mark.parametrize(("window", "column"), [(20, "EMA20"), (50, "EMA50"), (200, "EMA200")])
    def test_exponential_moving_averages_match(self, subject, daily_bars, charts, window, column):
        """An EMA never forgets its seed, so this also checks we carry enough
        history for the long ones to have converged."""
        row = charts.get(subject.symbol)
        bars = daily_bars(subject.symbol)
        if row is None or len(bars) < window * 2 or not _is_number(row[column]):
            pytest.skip(f"no comparable {column} for {subject.symbol}")
        ours = ema([bar.close for bar in bars], window)[-1]
        drift = relative_difference(ours, float(row[column]))
        assert drift <= ARITHMETIC_TOLERANCE, (
            f"{subject.symbol} {column}: ours {ours:.4f} vs {row[column]:.4f} ({drift:.3%})"
        )


class TestTheLevelsDrawn:
    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_the_yearly_range_is_exact(self, subject, daily_bars, charts, engine):
        """A 52-week high is a fact, not an average: it must match outright.

        Measured at the latest bar, which is the window every other terminal
        quotes. What the chart *draws* is one bar behind that on purpose, and
        the next test is where that is pinned.
        """
        row = charts.get(subject.symbol)
        bars = daily_bars(subject.symbol)
        if row is None or not bars:
            pytest.skip(f"no data for {subject.symbol}")
        index = DailyLevelIndex(bars, engine.all_level_keys())
        for key, column in (
            (LevelKey("high", 52, weeks=True), "price_52_week_high"),
            (LevelKey("low", 52, weeks=True), "price_52_week_low"),
        ):
            series = index._rolling.get(key)
            theirs = row[column]
            if not series or not _is_number(theirs):
                continue
            ours = series[-1]
            assert relative_difference(ours, float(theirs)) <= PRICE_TOLERANCE, (
                f"{subject.symbol} {key}: ours {ours} vs {theirs}"
            )

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_the_yearly_window_is_weeks_and_not_a_bar_count(self, subject, daily_bars, engine):
        """252 bars is an approximation of a year and drifts at the edge.

        Celularity's 4.00 print is dated 2025-08-29 — 366 days back, inside
        a 252-bar window and outside a 52-week one — and it made our high
        27% higher than the market's until the window was counted in weeks.
        """
        bars = daily_bars(subject.symbol)
        if len(bars) < 300:
            pytest.skip(f"not enough history for {subject.symbol}")
        index = DailyLevelIndex(bars, {LevelKey("high", 52, weeks=True)})
        ours = index._rolling[LevelKey("high", 52, weeks=True)][-1]

        cutoff = ny_date(bars[-1].time) - timedelta(weeks=52)
        inside = [bar.high for bar in bars if ny_date(bar.time) > cutoff]
        assert ours == max(inside)

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_a_drawn_level_excludes_todays_bar(self, subject, daily_bars, engine):
        """The non-repaint rule, asserted rather than tolerated.

        Every other terminal's 200-day average includes today. Ours does not,
        so a level drawn on an intraday chart cannot move while the session
        runs. That is a deliberate one-bar difference, and this is where it
        is stated.
        """
        bars = daily_bars(subject.symbol)
        if len(bars) < 210:
            pytest.skip(f"not enough history for {subject.symbol}")
        index = DailyLevelIndex(bars, engine.all_level_keys())
        latest = engine.latest(
            bars, Timeframe.D1, level_index=index, daily_bars=bars, minute_bars=[]
        )
        drawn = latest.get("d_sma200")
        if drawn is None:
            pytest.skip(f"{subject.symbol} draws no 200-day average")

        closes = [bar.close for bar in bars]
        without_today = sma(closes[:-1], 200)[-1]
        assert drawn == pytest.approx(without_today, rel=1e-9)


class TestInvariants:
    """Properties that hold whatever the market did, needing no other source."""

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_the_macd_line_is_the_difference_of_its_averages(self, subject, daily_bars):
        """MACD is defined as one EMA minus another, and the histogram as the
        line minus its signal. Both are identities, so any drift is a bug."""
        closes = [bar.close for bar in daily_bars(subject.symbol)]
        if len(closes) < 200:
            pytest.skip(f"not enough history for {subject.symbol}")
        line, signal, histogram = macd(closes, 12, 26, 9)
        fast, slow = ema(closes, 12), ema(closes, 26)

        checked = 0
        for index in range(len(closes)):
            if None in (line[index], fast[index], slow[index]):
                continue
            checked += 1
            assert line[index] == pytest.approx(fast[index] - slow[index], rel=1e-9)
            if signal[index] is not None and histogram[index] is not None:
                assert histogram[index] == pytest.approx(line[index] - signal[index], rel=1e-9)
        assert checked > 100, f"{subject.symbol}: only {checked} points checked"

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_a_rolling_extreme_is_drawn_from_its_own_window(self, subject, daily_bars):
        """A 52-week high must be a price that actually traded."""
        bars = daily_bars(subject.symbol)
        if len(bars) < 300:
            pytest.skip(f"not enough history for {subject.symbol}")
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]
        assert rolling_max(highs, 252)[-1] == max(highs[-252:])
        assert rolling_min(lows, 252)[-1] == min(lows[-252:])

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_a_moving_average_sits_inside_the_range_it_averages(self, subject, daily_bars):
        """An average of closes cannot exceed the highest close it covers."""
        closes = [bar.close for bar in daily_bars(subject.symbol)]
        if len(closes) < 60:
            pytest.skip(f"not enough history for {subject.symbol}")
        window = closes[-50:]
        assert min(window) <= sma(closes, 50)[-1] <= max(window)
