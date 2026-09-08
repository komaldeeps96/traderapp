"""The 10-second history window: twelve IBKR-native hours, plus what is behind them.

Three slices. The recent four hours are the fast first paint (one IBKR
request); hours four to twelve arrive as the background extension (two more).
Behind those, the previous session comes off Alpaca's trade tape — the one
place the window pays for a tape walk it does not have to, because IBKR
cannot serve that depth without turning three chunked requests per ticker
switch into ten.

Alpaca's tape is otherwise only the *fallback* for the recent slice when TWS
is down, and never the extension, whose whole point is avoiding that
download.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.clock import NY_TZ, to_ny
from app.core.settings import HistorySettings
from app.domain.bars import Bar
from app.domain.sessions import prior_session_open
from app.domain.timeframes import Timeframe
from app.providers.base import MarketDataProvider
from app.providers.router import (
    TENSEC_RECENT_SECONDS,
    TENSEC_WINDOW_SECONDS,
    FeedRouter,
)
from tests.conftest import make_bar


class StubProvider(MarketDataProvider):
    """Records history requests and serves scripted bars.

    ``bars`` may be a flat list served for every request, or a dict keyed by
    timeframe when a test needs the bases to differ.
    """

    def __init__(
        self,
        name: str,
        available: bool,
        bars: list[Bar] | dict[Timeframe, list[Bar]] | None = None,
    ):
        super().__init__()
        self.name = name
        self._available = available
        self.bars = bars or []
        self.calls: list[tuple[Timeframe, datetime, datetime]] = []

    @property
    def is_available(self) -> bool:
        return self._available

    async def set_status_symbols(self, symbols):
        """The alpaca-only status channel; a no-op for a scripted stub."""

    async def fetch_bars(self, symbol, timeframe, start, end):
        self.calls.append((timeframe, start, end))
        if isinstance(self.bars, dict):
            return list(self.bars.get(timeframe, []))
        return list(self.bars)

    async def fetch_prior_tensec(self, symbol, start, end):
        """The Alpaca-only prior-session walk, recorded like any other fetch."""
        return await self.fetch_bars(symbol, Timeframe.S10, start, end)


def router_with(alpaca: StubProvider, ibkr: StubProvider) -> FeedRouter:
    return FeedRouter(alpaca, ibkr, HistorySettings())  # type: ignore[arg-type]


# 10:00 New York on Tuesday 2024-03-05, mid-session.
NOW = datetime(2024, 3, 5, 15, 0, tzinfo=UTC)
# 04:00 New York on Monday 2024-03-04 — the session before NOW's.
PRIOR_OPEN = datetime(2024, 3, 4, 9, 0, tzinfo=UTC)


def router_with_prior_sessions(
    alpaca: StubProvider, ibkr: StubProvider, sessions: int
) -> FeedRouter:
    return FeedRouter(alpaca, ibkr, HistorySettings(tensec_prior_sessions=sessions))  # type: ignore[arg-type]


class TestRecentSlice:
    async def test_ibkr_serves_the_last_four_hours(self):
        ibkr = StubProvider("ibkr", True, [make_bar(1_000_000, 5.0)])
        alpaca = StubProvider("alpaca", True)
        router = router_with(alpaca, ibkr)

        bars = await router.fetch_recent_tensec("RUN", NOW)

        assert bars
        assert alpaca.calls == []
        (timeframe, start, end) = ibkr.calls[0]
        assert timeframe is Timeframe.S10
        assert end == NOW
        assert start == NOW - timedelta(seconds=TENSEC_RECENT_SECONDS)

    async def test_alpaca_tape_is_only_the_fallback(self):
        ibkr = StubProvider("ibkr", False)
        alpaca = StubProvider("alpaca", True, [make_bar(1_000_000, 4.0)])
        router = router_with(alpaca, ibkr)

        bars = await router.fetch_recent_tensec("RUN", NOW)

        assert bars
        assert ibkr.calls == []
        (_, start, end) = alpaca.calls[0]
        assert end == NOW
        assert start == NOW - timedelta(seconds=TENSEC_RECENT_SECONDS)

    async def test_empty_ibkr_result_falls_through_to_alpaca(self):
        ibkr = StubProvider("ibkr", True, [])
        alpaca = StubProvider("alpaca", True, [make_bar(1_000_000, 4.0)])
        router = router_with(alpaca, ibkr)

        bars = await router.fetch_recent_tensec("RUN", NOW)
        assert bars
        assert len(alpaca.calls) == 1


class TestEarlierSlice:
    async def test_ibkr_serves_hours_four_to_eight(self):
        ibkr = StubProvider("ibkr", True, [make_bar(900_000, 5.0)])
        alpaca = StubProvider("alpaca", True)
        router = router_with(alpaca, ibkr)

        bars = await router.fetch_earlier_tensec("RUN", NOW)

        assert bars
        (timeframe, start, end) = ibkr.calls[0]
        assert timeframe is Timeframe.S10
        assert start == NOW - timedelta(seconds=TENSEC_WINDOW_SECONDS)
        assert end == NOW - timedelta(seconds=TENSEC_RECENT_SECONDS)

    async def test_never_walks_the_tape_for_the_extension(self):
        """With TWS down the extension is skipped, not rebuilt from trades."""
        ibkr = StubProvider("ibkr", False)
        alpaca = StubProvider("alpaca", True, [make_bar(900_000, 4.0)])
        router = router_with(alpaca, ibkr)

        assert await router.fetch_earlier_tensec("RUN", NOW) == []
        assert alpaca.calls == []


class TestPriorSessions:
    """The depth behind the IBKR window, and who is allowed to fetch it."""

    async def test_alpaca_walks_the_tape_from_the_previous_session_open(self):
        ibkr = StubProvider("ibkr", True, [make_bar(900_000, 5.0)])
        alpaca = StubProvider("alpaca", True, [make_bar(800_000, 4.0)])
        router = router_with(alpaca, ibkr)

        bars = await router.fetch_prior_tensec("RUN", NOW)

        assert bars
        assert ibkr.calls == []
        (timeframe, start, end) = alpaca.calls[0]
        assert timeframe is Timeframe.S10
        assert start == PRIOR_OPEN
        # It stops where IBKR's own window begins.
        assert end == NOW - timedelta(seconds=TENSEC_WINDOW_SECONDS)

    async def test_reaches_the_recent_slice_when_tws_is_down(self):
        """Otherwise it would leave the hole the skipped extension makes.

        With IBKR gone nothing serves hours four to twelve, so the tape walk
        that is already happening covers them too rather than fetching an
        island of yesterday with today's morning missing between.
        """
        ibkr = StubProvider("ibkr", False)
        alpaca = StubProvider("alpaca", True, [make_bar(800_000, 4.0)])
        router = router_with(alpaca, ibkr)

        await router.fetch_prior_tensec("RUN", NOW)

        (_, start, end) = alpaca.calls[0]
        assert start == PRIOR_OPEN
        assert end == NOW - timedelta(seconds=TENSEC_RECENT_SECONDS)

    async def test_two_sessions_reaches_one_day_further(self):
        alpaca = StubProvider("alpaca", True, [make_bar(800_000, 4.0)])
        router = router_with_prior_sessions(alpaca, StubProvider("ibkr", True), 2)

        await router.fetch_prior_tensec("RUN", NOW)

        # Friday 2024-03-01, 04:00 New York: the weekend is stepped over.
        assert alpaca.calls[0][1] == datetime(2024, 3, 1, 9, 0, tzinfo=UTC)

    async def test_zero_sessions_turns_the_walk_off(self):
        alpaca = StubProvider("alpaca", True, [make_bar(800_000, 4.0)])
        router = router_with_prior_sessions(alpaca, StubProvider("ibkr", True), 0)

        assert await router.fetch_prior_tensec("RUN", NOW) == []
        assert alpaca.calls == []

    async def test_nothing_to_fetch_when_ibkr_already_reaches_further(self, monkeypatch):
        """Widen the native window past the previous session's open and the
        walk stops happening rather than asking for an inverted range."""
        monkeypatch.setattr("app.providers.router.TENSEC_WINDOW_SECONDS", 72 * 3600)
        alpaca = StubProvider("alpaca", True, [make_bar(800_000, 4.0)])
        router = router_with(alpaca, StubProvider("ibkr", True))

        assert await router.fetch_prior_tensec("RUN", NOW) == []
        assert alpaca.calls == []

    async def test_a_broken_tape_walk_costs_the_window_nothing(self):
        class Broken(StubProvider):
            async def fetch_prior_tensec(self, symbol, start, end):
                raise RuntimeError("tape unavailable")

        router = router_with(Broken("alpaca", True), StubProvider("ibkr", True, [make_bar(1, 5.0)]))
        assert await router.fetch_prior_tensec("RUN", NOW) == []


class TestFullWindow:
    async def test_merges_every_slice_with_the_newer_one_winning(self):
        shared = 1_000_000
        ibkr = StubProvider("ibkr", True, [make_bar(shared, 5.0)])
        alpaca = StubProvider("alpaca", True, [make_bar(shared, 4.0)])
        router = router_with(alpaca, ibkr)

        bars = await router.fetch_history("RUN", Timeframe.S10)

        # Every slice returned the same scripted timestamp; it lands once, and
        # IBKR's close wins it over the tape's.
        assert len(bars) == 1
        assert bars[0].close == pytest.approx(5.0)
        assert len(ibkr.calls) == 2
        assert len(alpaca.calls) == 1

    async def test_the_prior_slice_alone_still_draws_a_chart(self):
        """TWS down and the recent tape empty: yesterday is better than nothing."""
        alpaca = StubProvider("alpaca", True, {Timeframe.S10: [make_bar(800_000, 4.0)]})
        router = router_with(alpaca, StubProvider("ibkr", False))

        assert await router.fetch_history("RUN", Timeframe.S10)

    async def test_nothing_available_returns_nothing(self):
        router = router_with(StubProvider("alpaca", False), StubProvider("ibkr", False))
        assert await router.fetch_history("RUN", Timeframe.S10) == []


class TestFastMinutePath:
    async def test_single_alpaca_request(self):
        ibkr = StubProvider("ibkr", True, [make_bar(2_000_000, 6.0)])
        alpaca = StubProvider("alpaca", True, [make_bar(1_000_000, 5.0)])
        router = router_with(alpaca, ibkr)

        bars = await router.fetch_intraday_fast("RUN")

        assert bars
        assert len(alpaca.calls) == 1
        assert ibkr.calls == []

    async def test_falls_back_to_ibkr_recent(self):
        ibkr = StubProvider("ibkr", True, [make_bar(2_000_000, 6.0)])
        alpaca = StubProvider("alpaca", False)
        router = router_with(alpaca, ibkr)

        bars = await router.fetch_intraday_fast("RUN")

        assert bars
        (timeframe, start, end) = ibkr.calls[0]
        assert timeframe is Timeframe.M1
        assert (end - start).total_seconds() == HistorySettings().ibkr_recent_seconds


class TestPriorSessionOpen:
    """Which 04:00 the window anchors to, from any point in the week."""

    @staticmethod
    def opens_at(year, month, day, hour, minute=0, sessions=1):
        """``prior_session_open`` for a New York wall-clock moment, in NY."""
        reference = datetime(year, month, day, hour, minute, tzinfo=NY_TZ)
        return to_ny(prior_session_open(reference, sessions).timestamp())

    def test_midday_anchors_to_yesterday(self):
        opened = self.opens_at(2024, 3, 5, 12)  # Tuesday lunchtime
        assert (opened.date(), opened.hour) == (date(2024, 3, 4), 4)

    def test_before_the_premarket_opens_today_has_not_traded(self):
        """At 02:00 nothing has printed today, so today is not a session yet
        and one back from the current one is the day before yesterday."""
        opened = self.opens_at(2024, 3, 5, 2)  # Tuesday, small hours
        assert opened.date() == date(2024, 3, 1)  # Friday, not Monday

    def test_monday_steps_over_the_weekend(self):
        opened = self.opens_at(2024, 3, 4, 12)  # Monday
        assert opened.date() == date(2024, 3, 1)  # Friday

    def test_the_weekend_itself_anchors_to_thursday(self):
        """Saturday's most recent session is Friday's, so one back is Thursday."""
        opened = self.opens_at(2024, 3, 9, 12)  # Saturday
        assert opened.date() == date(2024, 3, 7)  # Thursday

    def test_zero_sessions_is_this_session_own_open(self):
        opened = self.opens_at(2024, 3, 5, 12, sessions=0)
        assert (opened.date(), opened.hour) == (date(2024, 3, 5), 4)

    def test_04_00_is_04_00_on_both_sides_of_a_dst_change(self):
        """US clocks moved on 2024-03-10. Anchoring to the wall clock rather
        than to a fixed offset is what keeps the pre-market open the
        pre-market open."""
        before = self.opens_at(2024, 3, 8, 12)  # Friday, EST
        after = self.opens_at(2024, 3, 12, 12)  # Tuesday, EDT
        assert before.hour == after.hour == 4
        assert before.utcoffset() != after.utcoffset()


class TestWindowShape:
    """The window is a deliberate size, not an incidental one."""

    def test_covers_twelve_hours(self):
        assert TENSEC_WINDOW_SECONDS == 12 * 3600

    def test_costs_three_ibkr_requests(self):
        """IBKR caps a 10s request at four hours and the provider chunks the
        rest itself, so the window's depth *is* the request count."""
        from app.providers.ibkr import _MAX_REQUEST_SECONDS

        cap = _MAX_REQUEST_SECONDS[Timeframe.S10]
        recent = math.ceil(TENSEC_RECENT_SECONDS / cap)
        earlier = math.ceil((TENSEC_WINDOW_SECONDS - TENSEC_RECENT_SECONDS) / cap)
        assert recent + earlier == 3

    def test_the_first_paint_is_a_single_request(self):
        from app.providers.ibkr import _MAX_REQUEST_SECONDS

        assert _MAX_REQUEST_SECONDS[Timeframe.S10] >= TENSEC_RECENT_SECONDS

    def test_the_prior_sessions_cost_no_ibkr_requests_at_all(self):
        """The reason they are Alpaca's. Reaching the previous session's
        04:00 natively would be seven more chunks against a sixty-per-ten-
        minutes pacing allowance, two of them the dead overnight hours."""
        from app.providers.ibkr import _MAX_REQUEST_SECONDS

        cap = _MAX_REQUEST_SECONDS[Timeframe.S10]
        native = math.ceil((36 * 3600) / cap)  # NOW's window, were IBKR asked
        assert native >= 9
        assert HistorySettings().tensec_prior_sessions >= 1

    def test_the_depth_matches_the_slowest_line_configured_on_the_chart(self):
        """``ema()`` draws nothing until it has ``span`` bars, so the window
        has to hold more of them than the slowest 10s indicator asks for.

        Measured at midday, twelve hours held 1,078 ten-second bars for SPWR
        and 1,741 for WETO — enough for a 600-span line to start most of the
        way across the chart, and at the open, not to start. One previous
        session took those to 3,064 and 4,738.
        """
        from app.core.settings import get_settings
        from app.indicators.spec import load_indicator_specs

        specs = load_indicator_specs(get_settings().indicators_file)
        spans = [
            spec.span_for(Timeframe.S10)
            for spec in specs
            if spec.span_for(Timeframe.S10) is not None
        ]
        assert max(spans) >= 600, (
            "no slow line left on the 10s chart — if that is deliberate, the "
            "prior-session walk is paying for depth nothing draws against"
        )
        assert HistorySettings().tensec_prior_sessions >= 1


class TestWindowCoversTheSession:
    """VWAP and the day's high/low depend on this, silently.

    They are computed from the 10-second bars alone — no seeding from the
    minute base, because that mixed Alpaca's odd-lot-inclusive volume into
    IBKR's odd-lot-exclusive bars and made the line step. What makes that
    safe is the window reaching the session open. Shrink it and those
    indicators quietly start describing a partial session instead, with
    nothing else failing.
    """

    def test_spans_premarket_open_to_the_regular_close(self):
        from app.domain.sessions import PREMARKET_OPEN_HOUR, REGULAR_CLOSE_HOUR

        session = (REGULAR_CLOSE_HOUR - PREMARKET_OPEN_HOUR) * 3600
        assert session <= TENSEC_WINDOW_SECONDS, (
            "the 10s window no longer reaches 04:00 from the closing bell; "
            "session VWAP and HOD/LOD will describe part of the day"
        )

    def test_after_hours_is_the_known_gap(self):
        """Documented, not fixed.

        IBKR counts duration in *trading* time, so twelve hours reaches
        04:00 right up to the 16:00 close. Past it the window starts later
        than the session does — measured coverage at 11:45 reached the prior
        day's 16:00, but at 20:00 it would begin around 08:00.
        """
        from app.domain.sessions import (
            AFTERHOURS_CLOSE_HOUR,
            PREMARKET_OPEN_HOUR,
            REGULAR_CLOSE_HOUR,
        )

        full_day = (AFTERHOURS_CLOSE_HOUR - PREMARKET_OPEN_HOUR) * 3600
        assert full_day > TENSEC_WINDOW_SECONDS, (
            "the window now covers the whole extended session — delete this "
            "test and the caveat it records"
        )
        assert TENSEC_WINDOW_SECONDS >= (REGULAR_CLOSE_HOUR - PREMARKET_OPEN_HOUR) * 3600
