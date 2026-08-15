"""The two-phase load and the revision counter's monotonicity.

The broadcaster's already-sent caches key on the revision. If a reload
restarted the counter, a drop-and-resubscribe inside one broadcast interval
would leave the fresh load looking already delivered — and on a quiet feed
nothing would ever bump it past the stale value.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.settings import HistorySettings
from app.domain.timeframes import Timeframe
from app.indicators.engine import IndicatorEngine
from app.market.store import BarStore
from app.providers.router import FeedRouter
from app.services.market_data import MarketDataService
from tests.conftest import make_bar, make_minute_series, ny_epoch
from tests.unit.test_router_tensec import StubProvider


def make_service() -> MarketDataService:
    bars = make_minute_series(ny_epoch(2024, 3, 5, 9, 30), [10.0] * 30)
    alpaca = StubProvider("alpaca", True, bars)
    ibkr = StubProvider("ibkr", False)
    router = FeedRouter(alpaca, ibkr, HistorySettings())  # type: ignore[arg-type]
    return MarketDataService(router, BarStore(), IndicatorEngine([]))


class TestTwoPhaseLoad:
    async def test_first_paint_carries_only_the_focused_base(self):
        """A 10s-focus load must not wait for the minute history."""
        service = make_service()
        await service.ensure_loaded("RUN", Timeframe.S10)

        assert service.bars("RUN", Timeframe.S10)
        assert service.bars("RUN", Timeframe.M1) == []

        await service.wait_for_backfill("RUN")
        assert service.bars("RUN", Timeframe.M1)

    async def test_backfill_announces_itself(self):
        service = make_service()
        landed: list[str] = []

        async def handler(symbol: str) -> None:
            landed.append(symbol)

        service.on_backfill(handler)
        await service.ensure_loaded("RUN", Timeframe.S10)
        await service.wait_for_backfill("RUN")

        assert landed == ["RUN"]

    async def test_backfill_bumps_the_revision(self):
        service = make_service()
        await service.ensure_loaded("RUN", Timeframe.S10)
        first = service.revision("RUN")
        await service.wait_for_backfill("RUN")
        assert service.revision("RUN") > first

    async def test_a_click_costs_exactly_two_ibkr_requests(self):
        """The whole point of the split: two 10s slices, nothing else.

        The fresh minute tail comes from resampling the 10s base, so IBKR is
        never asked for minute bars.
        """
        open_ = ny_epoch(2024, 3, 5, 9, 30)
        tensec = [make_bar(open_ + i * 10, 10.0 + i * 0.01, volume=50) for i in range(120)]
        alpaca = StubProvider(
            "alpaca",
            True,
            {
                Timeframe.D1: [make_bar(ny_epoch(2024, 3, 4, 0, 0), 9.0)],
                Timeframe.M1: make_minute_series(open_ - 3600, [9.5] * 30),
            },
        )
        ibkr = StubProvider("ibkr", True, {Timeframe.S10: tensec})
        router = FeedRouter(alpaca, ibkr, HistorySettings())  # type: ignore[arg-type]
        service = MarketDataService(router, BarStore(), IndicatorEngine([]))

        await service.ensure_loaded("RUN", Timeframe.S10)
        await service.wait_for_backfill("RUN")

        assert [call[0] for call in ibkr.calls] == [Timeframe.S10, Timeframe.S10]
        assert Timeframe.M1 not in {call[0] for call in ibkr.calls}

    async def test_fresh_minutes_are_resampled_from_the_tensec_base(self):
        """Six consolidated 10s bars fold into the consolidated minute."""
        open_ = ny_epoch(2024, 3, 5, 9, 30)
        # Two full minutes of 10s bars plus a partial third minute.
        tensec = [make_bar(open_ + i * 10, 10.0, volume=50) for i in range(14)]
        alpaca = StubProvider(
            "alpaca",
            True,
            {
                Timeframe.D1: [make_bar(ny_epoch(2024, 3, 4, 0, 0), 9.0)],
                # Alpaca's delayed minutes end an hour before the open.
                Timeframe.M1: make_minute_series(open_ - 3600, [9.5] * 5),
            },
        )
        ibkr = StubProvider("ibkr", True, {Timeframe.S10: tensec})
        router = FeedRouter(alpaca, ibkr, HistorySettings())  # type: ignore[arg-type]
        service = MarketDataService(router, BarStore(), IndicatorEngine([]))

        await service.ensure_loaded("RUN", Timeframe.S10)
        await service.wait_for_backfill("RUN")

        minutes = {bar.time: bar for bar in service.bars("RUN", Timeframe.M1)}
        # The two complete minutes were derived: volume is six 10s bars' worth.
        assert minutes[open_].volume == pytest.approx(300)
        assert minutes[open_ + 60].volume == pytest.approx(300)
        # The partial third minute is left to the live builder.
        assert open_ + 120 not in minutes
        # Alpaca's older minutes survive untouched alongside.
        assert (open_ - 3600) in minutes


class TestRecentRepair:
    """Healing the seam a delayed-fallback load leaves behind."""

    async def test_repair_merges_fresh_bars_and_announces(self):
        open_ = ny_epoch(2024, 3, 5, 9, 30)
        stale = [make_bar(open_ + i * 10, 10.0) for i in range(6)]
        alpaca = StubProvider("alpaca", True, {
            Timeframe.D1: [make_bar(ny_epoch(2024, 3, 4, 0, 0), 9.0)],
            Timeframe.S10: stale,
            Timeframe.M1: make_minute_series(open_ - 3600, [9.5] * 5),
        })
        ibkr = StubProvider("ibkr", False)
        router = FeedRouter(alpaca, ibkr, HistorySettings())  # type: ignore[arg-type]
        service = MarketDataService(router, BarStore(), IndicatorEngine([]))

        await service.ensure_loaded("RUN", Timeframe.S10)
        await service.wait_for_backfill("RUN")
        assert len(service.bars("RUN", Timeframe.S10)) == 6

        # TWS comes online with the bars the delayed tape could not serve.
        fresh = [make_bar(open_ + i * 10, 11.0) for i in range(6, 12)]
        ibkr._available = True
        ibkr.bars = {Timeframe.S10: fresh}
        landed: list[str] = []

        async def handler(symbol: str) -> None:
            landed.append(symbol)

        service.on_backfill(handler)
        before = service.revision("RUN")
        service.schedule_recent_repair("RUN")
        await service.wait_for_repair("RUN")

        assert len(service.bars("RUN", Timeframe.S10)) == 12
        assert landed == ["RUN"]
        assert service.revision("RUN") > before

    async def test_repair_ignores_unloaded_symbols(self):
        service = make_service()
        service.schedule_recent_repair("GHOST")
        assert "GHOST" not in service._repairs


class TestKeepWarm:
    """Flipping between the same runners must not cost a full reload."""

    async def test_a_flip_back_is_served_from_the_warm_cache(self):
        open_ = ny_epoch(2024, 3, 5, 9, 30)
        alpaca = StubProvider("alpaca", True, {
            Timeframe.D1: [make_bar(ny_epoch(2024, 3, 4, 0, 0), 9.0)],
            Timeframe.S10: [make_bar(open_ + i * 10, 10.0) for i in range(6)],
            Timeframe.M1: make_minute_series(open_, [10.0] * 5),
        })
        router = FeedRouter(alpaca, StubProvider("ibkr", False), HistorySettings())  # type: ignore[arg-type]
        service = MarketDataService(router, BarStore(), IndicatorEngine([]))

        await service.ensure_loaded("RUN", Timeframe.S10)
        await service.wait_for_backfill("RUN")
        calls_after_load = len(alpaca.calls)

        service.unload("RUN")
        assert await service.ensure_loaded("RUN", Timeframe.S10) is True
        # Instant revival: history came from memory, before any repair I/O.
        assert service.bars("RUN", Timeframe.S10)
        await service.wait_for_repair("RUN")

        # Exactly one gap-repair fetch, not a full reload.
        assert len(alpaca.calls) == calls_after_load + 1

    async def test_parked_symbols_expire(self, monkeypatch):
        import app.services.market_data as module

        monkeypatch.setattr(module, "KEEP_WARM_SECONDS", 0.05)
        service = make_service()
        await service.ensure_loaded("RUN", Timeframe.M1)
        service.unload("RUN")
        assert service.bars("RUN", Timeframe.M1)

        await asyncio.sleep(0.15)
        assert service.bars("RUN", Timeframe.M1) == []
        assert "RUN" not in service._parked

    async def test_the_warm_cache_is_bounded(self, monkeypatch):
        import app.services.market_data as module

        monkeypatch.setattr(module, "KEEP_WARM_MAX_SYMBOLS", 2)
        service = make_service()
        for symbol in ("AAA", "BBB", "CCC"):
            await service.ensure_loaded(symbol, Timeframe.M1)
            service.unload(symbol)

        assert service.bars("AAA", Timeframe.M1) == []  # oldest evicted
        assert service.bars("BBB", Timeframe.M1)
        assert service.bars("CCC", Timeframe.M1)


class TestRevisionMonotonicity:
    async def test_reload_bumps_past_the_previous_revision(self):
        service = make_service()

        assert await service.ensure_loaded("RUN") is True
        first = service.revision("RUN")
        assert first > 0

        service.unload("RUN")
        assert await service.ensure_loaded("RUN") is True

        assert service.revision("RUN") > first

    async def test_bars_are_served_after_a_reload(self):
        service = make_service()
        await service.ensure_loaded("RUN")
        service.unload("RUN")
        await service.ensure_loaded("RUN")
        # The minute base rides the background pass when the focus is 10s.
        await service.wait_for_backfill("RUN")
        assert service.bars("RUN", Timeframe.M1)
