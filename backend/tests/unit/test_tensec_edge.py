"""The older 10s slices are measured from the first paint, not the wall clock.

With the market shut, the four hours TWS serves as the first paint end on
Friday. A window measured back from Sunday asks for the weekend, comes back
empty, and leaves the chart without the session it opened on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.settings import HistorySettings
from app.domain.bars import Bar
from app.domain.sessions import prior_session_open
from app.domain.timeframes import Timeframe
from app.indicators.engine import IndicatorEngine
from app.market.store import BarStore
from app.providers.router import TENSEC_RECENT_SECONDS, TENSEC_WINDOW_SECONDS, FeedRouter
from app.services import market_data
from app.services.market_data import MarketDataService
from tests.conftest import make_bar, make_minute_series, ny_epoch
from tests.unit.test_router_tensec import StubProvider

# Friday 1 March 2024, 15:59:50 New York: where TWS's last four hours begin
# when asked on the Sunday after.
FRIDAY_PAINT_START = ny_epoch(2024, 3, 1, 15, 59) + 50
EXTENSION = timedelta(seconds=TENSEC_WINDOW_SECONDS - TENSEC_RECENT_SECONDS)


def at(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


def hourly_paint(start: int, hours: int = 5) -> list[Bar]:
    return [make_bar(start + hour * 3600, 10.0 + hour * 0.1) for hour in range(hours)]


def service_with(first_paint: list[Bar]) -> tuple[MarketDataService, StubProvider, StubProvider]:
    ibkr = StubProvider("ibkr", True, {Timeframe.S10: first_paint})
    minutes = make_minute_series(ny_epoch(2024, 3, 1, 9, 30), [10.0] * 30)
    alpaca = StubProvider("alpaca", True, {Timeframe.M1: minutes})
    router = FeedRouter(alpaca, ibkr, HistorySettings())  # type: ignore[arg-type]
    return MarketDataService(router, BarStore(), IndicatorEngine([])), ibkr, alpaca


def tensec_windows(provider: StubProvider) -> list[tuple[datetime, datetime]]:
    return [(start, end) for timeframe, start, end in provider.calls if timeframe is Timeframe.S10]


class TestAfterTheClose:
    async def test_the_extension_reaches_back_from_friday_not_from_now(self):
        service, ibkr, _ = service_with(hourly_paint(FRIDAY_PAINT_START))

        await service.ensure_loaded("RUN", Timeframe.S10)
        await service.wait_for_backfill("RUN")

        oldest = at(FRIDAY_PAINT_START)
        assert (oldest - EXTENSION, oldest) in tensec_windows(ibkr)

    async def test_the_prior_session_tape_stops_where_the_extension_starts(self):
        service, _, alpaca = service_with(hourly_paint(FRIDAY_PAINT_START))

        await service.ensure_loaded("RUN", Timeframe.S10)
        await service.wait_for_backfill("RUN")

        edge = at(FRIDAY_PAINT_START + TENSEC_RECENT_SECONDS)
        stop = edge - timedelta(seconds=TENSEC_WINDOW_SECONDS)
        assert tensec_windows(alpaca) == [(prior_session_open(edge, 1), stop)]

    async def test_a_minute_chart_anchors_on_the_slice_it_fetches_itself(self):
        service, ibkr, _ = service_with(hourly_paint(FRIDAY_PAINT_START))

        await service.ensure_loaded("RUN", Timeframe.M1)
        await service.wait_for_backfill("RUN")

        oldest = at(FRIDAY_PAINT_START)
        assert (oldest - EXTENSION, oldest) in tensec_windows(ibkr)


class TestDuringTheSession:
    async def test_a_thin_first_paint_leaves_the_windows_on_now(self, monkeypatch):
        """A name whose first print in the window came an hour ago: the
        extension still abuts now minus four hours, not an hour from now."""
        now = FRIDAY_PAINT_START + 3600
        monkeypatch.setattr(market_data, "now_epoch", lambda: float(now))
        service, ibkr, _ = service_with([make_bar(now - 3600, 10.0), make_bar(now - 60, 10.1)])

        await service.ensure_loaded("RUN", Timeframe.S10)
        await service.wait_for_backfill("RUN")

        edge = at(now)
        window = (
            edge - timedelta(seconds=TENSEC_WINDOW_SECONDS),
            edge - timedelta(seconds=TENSEC_RECENT_SECONDS),
        )
        assert window in tensec_windows(ibkr)


def test_no_first_paint_leaves_the_router_on_now():
    assert MarketDataService._tensec_edge([]) is None
