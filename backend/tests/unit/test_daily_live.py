"""Today's candle on the daily and weekly charts.

The daily base is fetched and never streamed, so its newest row is frozen at
whatever the provider had published when the symbol was loaded. Left alone,
the 1D chart's last candle sits at that price for the rest of the session
while the 10s tape beside it runs — which is exactly the thing a context chart
is there to prevent. It is folded out of the minute base on read instead.
"""

from __future__ import annotations

import pytest

from app.domain.bars import Bar
from app.domain.timeframes import Timeframe
from app.indicators.engine import IndicatorEngine
from app.market.store import BarStore
from app.services.market_data import MarketDataService
from tests.conftest import make_bar, ny_epoch

MONDAY = ny_epoch(2024, 3, 4, 0, 0)
TUESDAY = ny_epoch(2024, 3, 5, 0, 0)
OPEN = ny_epoch(2024, 3, 5, 9, 30)


def service_with(daily: list[Bar], minutes: list[Bar]) -> MarketDataService:
    """A service over a seeded store — the read path, no loading involved."""
    store = BarStore()
    store.replace("RUN", Timeframe.D1, daily)
    store.replace("RUN", Timeframe.M1, minutes)
    service = MarketDataService(None, store, IndicatorEngine([]))  # type: ignore[arg-type]
    service._loaded.add("RUN")
    return service


def day(bars: list[Bar]) -> Bar:
    return bars[-1]


class TestTodaysCandle:
    def test_the_close_follows_the_minute_base(self):
        """The frozen row is the bug; the newest print is the fix."""
        stale = Bar(time=TUESDAY, open=1.0, high=1.7, low=0.9, close=1.66, volume=90e6)
        minutes = [make_bar(OPEN + i * 60, 1.9 + i * 0.01) for i in range(5)]
        service = service_with([make_bar(MONDAY, 0.88), stale], minutes)

        assert day(service.bars("RUN", Timeframe.D1)).close == pytest.approx(1.94)

    def test_the_range_widens_but_never_narrows(self):
        """A thin minute base has seen less of the day than the fetched row."""
        stored = Bar(time=TUESDAY, open=1.0, high=2.5, low=0.7, close=1.66, volume=90e6)
        # One late minute: high above the fetched row's, low well inside it.
        minutes = [Bar(time=OPEN, open=1.9, high=2.9, low=1.8, close=1.97, volume=1e6)]
        service = service_with([make_bar(MONDAY, 0.88), stored], minutes)

        today = day(service.bars("RUN", Timeframe.D1))
        assert today.high == pytest.approx(2.9)
        assert today.low == pytest.approx(0.7)
        assert today.volume == pytest.approx(90e6)

    def test_the_open_stays_the_provider_s(self):
        """The gap is measured from the day's first print, which is theirs."""
        stored = Bar(time=TUESDAY, open=1.0, high=1.7, low=0.9, close=1.66, volume=90e6)
        minutes = [Bar(time=OPEN, open=1.9, high=2.0, low=1.85, close=1.97, volume=1e6)]
        service = service_with([stored], minutes)

        assert day(service.bars("RUN", Timeframe.D1)).open == pytest.approx(1.0)

    def test_volume_tracks_the_session_once_it_passes_the_fetched_row(self):
        """Whichever side counted more wins; the day's volume never goes back."""
        stored = Bar(time=TUESDAY, open=1.0, high=1.7, low=0.9, close=1.66, volume=1e6)
        minutes = [make_bar(OPEN + i * 60, 1.9, volume=2e6) for i in range(5)]
        service = service_with([stored], minutes)

        assert day(service.bars("RUN", Timeframe.D1)).volume == pytest.approx(10e6)

    def test_a_day_the_provider_has_not_published_yet_is_appended(self):
        """Pre-market: the fetched history still ends yesterday."""
        minutes = [make_bar(OPEN + i * 60, 1.9) for i in range(3)]
        service = service_with([make_bar(MONDAY, 0.88)], minutes)

        bars = service.bars("RUN", Timeframe.D1)
        assert [bar.time for bar in bars] == [MONDAY, TUESDAY]
        assert day(bars).open == pytest.approx(minutes[0].open)

    def test_only_the_newest_session_is_folded(self):
        """Yesterday's minutes must not leak into today's candle."""
        minutes = [make_bar(ny_epoch(2024, 3, 4, 15, 0) + i * 60, 0.88, volume=5e6) for i in range(5)]
        minutes += [make_bar(OPEN + i * 60, 1.9, volume=2e6) for i in range(3)]
        service = service_with([], minutes)

        bars = service.bars("RUN", Timeframe.D1)
        assert [bar.time for bar in bars] == [TUESDAY]
        assert day(bars).volume == pytest.approx(6e6)

    def test_a_stale_minute_base_leaves_the_daily_history_alone(self):
        """The weekend, and the beat before a load's minutes land."""
        stored = make_bar(TUESDAY, 1.66)
        service = service_with([stored], [make_bar(ny_epoch(2024, 3, 4, 15, 0), 0.88)])

        assert service.bars("RUN", Timeframe.D1) == [stored]

    def test_no_minute_base_at_all_serves_the_history_untouched(self):
        daily = [make_bar(MONDAY, 0.88), make_bar(TUESDAY, 1.66)]
        service = service_with(daily, [])

        assert service.bars("RUN", Timeframe.D1) == daily


class TestWeeklyFollows:
    def test_the_week_in_progress_carries_today_s_price(self):
        """1W resamples the daily base, so it inherits the same fix."""
        stale = Bar(time=TUESDAY, open=1.0, high=1.7, low=0.9, close=1.66, volume=90e6)
        minutes = [Bar(time=OPEN, open=1.9, high=2.9, low=1.85, close=1.97, volume=1e6)]
        service = service_with([make_bar(MONDAY, 0.88), stale], minutes)

        week = day(service.bars("RUN", Timeframe.W1))
        assert week.time == ny_epoch(2024, 3, 4, 0, 0)  # the Monday
        assert week.close == pytest.approx(1.97)
        assert week.high == pytest.approx(2.9)


class TestLevelsStayHistorical:
    def test_the_daily_store_is_never_written_back(self):
        """Key levels are built from the store, and must not repaint intraday."""
        stored = Bar(time=TUESDAY, open=1.0, high=1.7, low=0.9, close=1.66, volume=90e6)
        service = service_with([stored], [make_bar(OPEN, 1.97)])

        service.bars("RUN", Timeframe.D1)

        assert service._store.get("RUN", Timeframe.D1) == [stored]
