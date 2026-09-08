"""Every key level, against what other platforms draw.

A level is a line a trader acts on. If ours sits somewhere nobody else's
does, the terminal is showing a different chart from the one the crowd is
watching — and on a level the crowd converges on, that is the whole game.

So this walks the list: the rolling extremes, the previous-period prices,
and the session levels. Where a difference is real it is asserted rather
than tolerated, because a deliberate difference that nobody wrote down
becomes a bug the next time somebody reads the code.
"""

from __future__ import annotations

import math
from datetime import date

import pytest
import yfinance as yf

from app.domain.sessions import ny_date
from app.domain.timeframes import Timeframe
from app.indicators.functions import (
    premarket_bounds_last,
    session_bounds_last,
    session_levels,
)
from app.indicators.levels import DailyLevelIndex, parse_level_key
from app.market.resample import resample
from tests.audit.conftest import relative_difference
from tests.audit.universe import UNIVERSE

pytestmark = pytest.mark.audit

SUBJECTS = [
    pytest.param(s, id=s.symbol) for s in UNIVERSE if s.country == "US" and not s.no_annual_filings
]

# Liquid names with real extended-hours volume, so a premarket level exists
# to compare at all.
SESSION_SUBJECTS = ["AAPL", "NVDA", "TSLA", "AMD", "F"]

# A price is a price: these must agree outright.
EXACT = 0.0005

# Two consolidated tapes disagree about which prints set an extreme —
# odd lots, out-of-sequence trades, and each vendor's own filtering. Measured
# at two to twenty basis points on liquid names, on bars carrying a thousand
# trades apiece, so it is the tape and not the window.
TAPE_TOLERANCE = 0.004


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


@pytest.fixture(scope="session")
def levels_reference():
    from tradingview_screener import Query, col

    columns = [
        "name",
        "close",
        "change",
        "price_52_week_high",
        "price_52_week_low",
        "High.6M",
        "Low.6M",
        "High.3M",
        "Low.3M",
        "high|1W",
        "low|1W",
        "high|1M",
        "low|1M",
        "premarket_high",
        "premarket_low",
        "premarket_open",
        "open",
        "high",
        "low",
    ]
    symbols = [s.symbol for s in UNIVERSE] + SESSION_SUBJECTS
    _, frame = (
        Query().select(*columns).where(col("name").isin(symbols)).limit(100).get_scanner_data()
    )
    return {row["name"]: row for _, row in frame.iterrows()}


class TestRollingExtremes:
    """The 13-, 26- and 52-week highs and lows."""

    @pytest.mark.parametrize("subject", SUBJECTS)
    @pytest.mark.parametrize(
        ("level", "column"),
        [
            ("high:52w", "price_52_week_high"),
            ("low:52w", "price_52_week_low"),
            ("high:26w", "High.6M"),
            ("low:26w", "Low.6M"),
            ("high:13w", "High.3M"),
            ("low:13w", "Low.3M"),
        ],
    )
    def test_it_matches_the_market(self, subject, daily_bars, levels_reference, level, column):
        row = levels_reference.get(subject.symbol)
        bars = daily_bars(subject.symbol)
        if row is None or not bars or not _is_number(row[column]):
            pytest.skip(f"no comparable {column} for {subject.symbol}")
        key = parse_level_key(level)
        ours = DailyLevelIndex(bars, {key})._rolling[key][-1]
        assert relative_difference(ours, float(row[column])) <= EXACT, (
            f"{subject.symbol} {level}: ours {ours} vs {row[column]}"
        )


class TestYearToDate:
    """The high of the current calendar year, against the other tape.

    TradingView audits every other level in this file and cannot audit this
    one: `High.YTD` resolves as a column and comes back null for every symbol
    asked, mega caps included. So the auditor here is yfinance, which
    publishes the daily bars themselves — the check is the one anybody would
    make by hand, the highest print since 1 January.
    """

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_it_matches_the_other_tape(self, subject, daily_bars):
        bars = daily_bars(subject.symbol)
        if not bars:
            pytest.skip(f"no daily bars for {subject.symbol}")
        as_of = ny_date(bars[-1].time)
        key = parse_level_key("ytd_high")
        ours = DailyLevelIndex(bars).value(key, as_of)
        # Ours excludes the day it is drawn on, so theirs must stop at the
        # same bar: `end` is exclusive, and comparing across that one bar
        # would read as a tape disagreement rather than the design it is.
        history = yf.Ticker(subject.symbol).history(
            start=date(as_of.year, 1, 1).isoformat(),
            end=as_of.isoformat(),
            auto_adjust=False,
        )
        if ours is None or history.empty:
            pytest.skip(f"no year-to-date window for {subject.symbol}")
        theirs = float(history["High"].max())
        assert relative_difference(ours, theirs) <= EXACT, (
            f"{subject.symbol} ytd high: ours {ours} vs {theirs}"
        )


class TestPreviousPeriods:
    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_the_previous_close_matches(self, subject, daily_bars, levels_reference):
        """Derived from their own close and change, so it is their number."""
        row = levels_reference.get(subject.symbol)
        bars = daily_bars(subject.symbol)
        if row is None or not bars or not _is_number(row["change"]):
            pytest.skip(f"no comparable close for {subject.symbol}")
        key = parse_level_key("prev_day_close")
        ours = DailyLevelIndex(bars, {key}).value(key, ny_date(bars[-1].time))
        theirs = float(row["close"]) / (1 + float(row["change"]) / 100)
        assert relative_difference(ours, theirs) <= EXACT, (
            f"{subject.symbol} prev close: ours {ours} vs {theirs}"
        )

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_our_weeks_are_their_weeks(self, subject, daily_bars, levels_reference):
        """The previous-week levels are only as right as the bucketing.

        Checked on the *current* week, which is the one they publish: if our
        week boundaries agree with theirs, so does every level built by
        stepping back one bucket.
        """
        row = levels_reference.get(subject.symbol)
        bars = daily_bars(subject.symbol)
        if row is None or not bars or not _is_number(row["high|1W"]):
            pytest.skip(f"no weekly bar for {subject.symbol}")
        week = resample(bars, Timeframe.W1)[-1]
        assert relative_difference(week.high, float(row["high|1W"])) <= EXACT
        assert relative_difference(week.low, float(row["low|1W"])) <= EXACT

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_our_months_are_their_months(self, subject, daily_bars, levels_reference):
        row = levels_reference.get(subject.symbol)
        bars = daily_bars(subject.symbol)
        if row is None or not bars or not _is_number(row["high|1M"]):
            pytest.skip(f"no monthly bar for {subject.symbol}")
        last = ny_date(bars[-1].time)
        month = [
            bar
            for bar in bars
            if ny_date(bar.time).year == last.year and ny_date(bar.time).month == last.month
        ]
        assert relative_difference(max(b.high for b in month), float(row["high|1M"])) <= EXACT
        assert relative_difference(min(b.low for b in month), float(row["low|1M"])) <= EXACT


class TestSessionLevels:
    """Pre-market and open, which only exist on an intraday series."""

    @pytest.mark.parametrize("symbol", SESSION_SUBJECTS)
    def test_the_premarket_window_agrees(self, symbol, minute_bars, levels_reference):
        row = levels_reference.get(symbol)
        bars = minute_bars(symbol)
        if row is None or not bars:
            pytest.skip(f"no minute bars for {symbol}")
        day = ny_date(bars[-1].time)
        session = [bar for bar in bars if ny_date(bar.time) == day]
        high, low = premarket_bounds_last(session)
        for ours, column in ((high, "premarket_high"), (low, "premarket_low")):
            if ours is None or not _is_number(row[column]):
                continue
            assert relative_difference(ours, float(row[column])) <= TAPE_TOLERANCE, (
                f"{symbol} {column}: ours {ours} vs {row[column]}"
            )

    @pytest.mark.parametrize("symbol", SESSION_SUBJECTS)
    def test_the_regular_open_is_exact(self, symbol, minute_bars, levels_reference):
        """One print at one moment, so there is nothing to disagree about."""
        row = levels_reference.get(symbol)
        bars = minute_bars(symbol)
        if row is None or not bars or not _is_number(row["open"]):
            pytest.skip(f"no minute bars for {symbol}")
        day = ny_date(bars[-1].time)
        ours = session_levels(bars, day).rth_open.value
        if ours is None:
            pytest.skip(f"{symbol} has no regular-session open yet")
        assert relative_difference(ours, float(row["open"])) <= TAPE_TOLERANCE, (
            f"{symbol} rth_open: ours {ours} vs {row['open']}"
        )

    @pytest.mark.parametrize("symbol", SESSION_SUBJECTS)
    def test_the_days_range_spans_the_extended_session(self, symbol, minute_bars):
        """A deliberate difference from every RTH-only quote, asserted.

        The high of day is the momentum premise — the level the crowd
        converges on — and on a small cap that level is very often set before
        09:30. So this runs 04:00 to 20:00, which means it can sit outside
        the regular-session range other platforms publish. Apple's low on
        2026-08-28 was its pre-market low, 0.18% under the figure TradingView
        shows.
        """
        bars = minute_bars(symbol)
        if not bars:
            pytest.skip(f"no minute bars for {symbol}")
        day = ny_date(bars[-1].time)
        session = [bar for bar in bars if ny_date(bar.time) == day]
        high, low = session_bounds_last(session)
        premarket_high, premarket_low = premarket_bounds_last(session)
        if None in (high, low, premarket_high, premarket_low):
            pytest.skip(f"{symbol} has no pre-market prints")
        # The day's range contains the pre-market range, by construction.
        assert high >= premarket_high
        assert low <= premarket_low
