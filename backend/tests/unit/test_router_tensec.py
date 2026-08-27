"""The 10-second history window: eight hours, IBKR-native, two slices.

The recent four hours are the fast first paint (one request); hours four to
eight arrive as the background extension. Alpaca's tape walk exists only as
the fallback for the recent slice when TWS is down — never for the extension,
whose whole point is avoiding that download.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.core.settings import HistorySettings
from app.domain.bars import Bar
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


def router_with(alpaca: StubProvider, ibkr: StubProvider) -> FeedRouter:
    return FeedRouter(alpaca, ibkr, HistorySettings())  # type: ignore[arg-type]


NOW = datetime(2024, 3, 5, 15, 0, tzinfo=UTC)


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


class TestFullWindow:
    async def test_merges_both_slices_with_recent_winning(self):
        shared = 1_000_000
        ibkr = StubProvider("ibkr", True, [make_bar(shared, 5.0)])
        alpaca = StubProvider("alpaca", True, [make_bar(shared, 4.0)])
        router = router_with(alpaca, ibkr)

        bars = await router.fetch_history("RUN", Timeframe.S10)

        # Both IBKR slices returned the same scripted bar; it lands once.
        assert len(bars) == 1
        assert bars[0].close == pytest.approx(5.0)
        assert len(ibkr.calls) == 2

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
