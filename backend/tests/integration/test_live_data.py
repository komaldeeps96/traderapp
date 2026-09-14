"""Live data flow: trades in, coalesced chart updates out."""

from __future__ import annotations

import pytest

from app.core.settings import CONFIG_DIR, HistorySettings
from app.domain.bars import Bar
from app.domain.timeframes import Timeframe
from app.indicators.engine import IndicatorEngine
from app.indicators.spec import load_indicator_specs
from app.market.bar_builder import Trade
from app.market.store import BarStore
from app.providers.router import FeedRouter
from app.services.broadcaster import ChartBroadcaster
from app.services.market_data import MarketDataService
from tests.conftest import make_minute_series, ny_epoch
from tests.integration.test_failover import StubProvider

OPEN = ny_epoch(2024, 3, 5, 9, 30)


@pytest.fixture
def alpaca():
    provider = StubProvider("alpaca")
    provider.bars = make_minute_series(OPEN, [100.0 + i * 0.1 for i in range(120)])
    return provider


@pytest.fixture
def service(alpaca):
    engine = IndicatorEngine(load_indicator_specs(CONFIG_DIR / "indicators.yaml"))
    router = FeedRouter(alpaca, StubProvider("ibkr", available=False), HistorySettings())
    return MarketDataService(router, BarStore(), engine)


@pytest.fixture
async def loaded(service):
    await service.start()
    # These tests exercise the minute path, so the minute base is the focus;
    # settling the backfill keeps every assertion deterministic.
    await service.ensure_loaded("AAPL", Timeframe.M1)
    await service.wait_for_backfill("AAPL")
    return service


class TestLoading:
    async def test_loads_a_symbol(self, loaded):
        assert loaded.is_loaded("AAPL")

    async def test_produces_a_snapshot(self, loaded):
        snapshot = loaded.snapshot("AAPL", Timeframe.M1)
        assert snapshot and snapshot["bars"]

    async def test_concurrent_loads_fetch_once(self, service, alpaca):
        import asyncio

        await service.start()
        await asyncio.gather(
            *[service.ensure_loaded("AAPL", Timeframe.M1) for _ in range(5)]
        )
        await service.wait_for_backfill("AAPL")
        intraday_calls = [c for c in alpaca.fetch_calls if c[1] is Timeframe.M1]
        assert len(intraday_calls) == 1

    async def test_reports_failure_for_an_unknown_symbol(self, service, alpaca):
        await service.start()
        alpaca.bars = []
        assert await service.ensure_loaded("NOPE") is False


class TestTrades:
    async def test_a_trade_updates_the_newest_bar(self, loaded):
        last = loaded.bars("AAPL", Timeframe.M1)[-1]
        await loaded._handle_trade("AAPL", Trade(time=last.time + 5, price=999.0, size=10))
        assert loaded.bars("AAPL", Timeframe.M1)[-1].high == pytest.approx(999.0)

    async def test_a_trade_adds_volume(self, loaded):
        last = loaded.bars("AAPL", Timeframe.M1)[-1]
        before = last.volume
        await loaded._handle_trade("AAPL", Trade(time=last.time + 5, price=100.0, size=25))
        assert loaded.bars("AAPL", Timeframe.M1)[-1].volume == pytest.approx(before + 25)

    async def test_a_trade_in_a_new_minute_appends_a_bar(self, loaded):
        bars = loaded.bars("AAPL", Timeframe.M1)
        count, last_time = len(bars), bars[-1].time
        await loaded._handle_trade("AAPL", Trade(time=last_time + 60, price=100.0, size=1))
        assert len(loaded.bars("AAPL", Timeframe.M1)) == count + 1

    async def test_trades_for_unloaded_symbols_are_ignored(self, loaded):
        await loaded._handle_trade("ZZZZ", Trade(time=OPEN, price=1.0, size=1))
        assert not loaded.is_loaded("ZZZZ")

    async def test_a_trade_bumps_the_revision(self, loaded):
        before = loaded.revision("AAPL")
        last = loaded.bars("AAPL", Timeframe.M1)[-1]
        await loaded._handle_trade("AAPL", Trade(time=last.time, price=100.0, size=1))
        assert loaded.revision("AAPL") > before

    async def test_indicators_follow_the_live_bar(self, loaded):
        before = loaded.series("AAPL", Timeframe.M1)["ema9"][-1][1]
        last = loaded.bars("AAPL", Timeframe.M1)[-1]
        await loaded._handle_trade("AAPL", Trade(time=last.time, price=500.0, size=10))
        assert loaded.series("AAPL", Timeframe.M1)["ema9"][-1][1] != pytest.approx(before)


class TestProviderBars:
    async def test_a_minute_our_10s_base_covers_stays_the_sum_of_its_10s_bars(self, loaded):
        """A provider bar counts prints our condition filter drops; taken over a
        built minute, the 1m chart stops agreeing with the 10s one."""
        last = loaded.bars("AAPL", Timeframe.M1)[-1]
        await loaded._handle_trade("AAPL", Trade(time=last.time, price=100.0, size=50))
        built = loaded.bars("AAPL", Timeframe.M1)[-1].volume

        provider = Bar(time=last.time, open=10, high=20, low=5, close=15, volume=99_999)
        await loaded._handle_bar("AAPL", Timeframe.M1, provider)
        assert loaded.bars("AAPL", Timeframe.M1)[-1].volume == pytest.approx(built)

    async def test_past_the_10s_base_later_trades_continue_from_the_provider_bar(self, loaded):
        loaded._store.replace("AAPL", Timeframe.S10, [])
        last = loaded.bars("AAPL", Timeframe.M1)[-1]
        authoritative = Bar(time=last.time, open=10, high=20, low=5, close=15, volume=1000)
        await loaded._handle_bar("AAPL", Timeframe.M1, authoritative)
        await loaded._handle_trade("AAPL", Trade(time=last.time + 1, price=16.0, size=5))

        current = loaded.bars("AAPL", Timeframe.M1)[-1]
        assert current.volume == pytest.approx(1005)
        assert current.close == pytest.approx(16.0)

    async def test_ignores_bars_for_unloaded_symbols(self, loaded):
        bar = Bar(time=OPEN, open=1, high=1, low=1, close=1, volume=1)
        await loaded._handle_bar("ZZZZ", Timeframe.M1, bar)
        assert not loaded.is_loaded("ZZZZ")


class TestTheLoadSeam:
    async def test_prints_that_arrived_during_the_load_are_replayed_past_its_last_bar(self, loaded):
        """The stream starts before the load; dropping its prints leaves the edge short."""
        tensec = loaded.bars("AAPL", Timeframe.S10)
        after = tensec[-1].time + Timeframe.S10.seconds
        loaded._early_trades["AAPL"] = [
            Trade(time=tensec[-1].time, price=1.0, size=1),
            Trade(time=after, price=200.0, size=7),
        ]
        await loaded._replay_early_trades("AAPL")

        tensec = loaded.bars("AAPL", Timeframe.S10)
        assert tensec[-1].time == after
        assert tensec[-1].close == pytest.approx(200.0)
        assert all(bar.low != pytest.approx(1.0) for bar in tensec)

    async def test_a_new_minute_builder_continues_the_10s_tail(self, loaded):
        """With no minute bar that far yet, the builder must not start the minute empty."""
        minute = loaded.bars("AAPL", Timeframe.M1)[-1].time + 60
        loaded._store.merge(
            "AAPL",
            Timeframe.S10,
            [
                Bar(time=minute, open=10, high=11, low=9, close=10.5, volume=4000),
                Bar(time=minute + 10, open=10.5, high=12, low=10, close=11, volume=200),
            ],
        )
        seed = loaded._live_seed("AAPL", Timeframe.M1)
        assert seed is not None
        assert (seed.time, seed.open, seed.volume) == (minute, 10, 4200)


class TestCaching:
    async def test_repeated_reads_reuse_the_cache(self, loaded):
        assert loaded.series("AAPL", Timeframe.M1) is loaded.series("AAPL", Timeframe.M1)

    async def test_the_cache_invalidates_on_new_data(self, loaded):
        first = loaded.series("AAPL", Timeframe.M1)
        last = loaded.bars("AAPL", Timeframe.M1)[-1]
        await loaded._handle_trade("AAPL", Trade(time=last.time, price=101.0, size=1))
        assert loaded.series("AAPL", Timeframe.M1) is not first

    async def test_derived_timeframes_are_cached_separately(self, loaded):
        assert loaded.bars("AAPL", Timeframe.M5) is not loaded.bars("AAPL", Timeframe.M1)


class TestUnload:
    async def test_stops_working_the_symbol_but_keeps_it_warm(self, loaded):
        loaded.unload("AAPL")
        assert not loaded.is_loaded("AAPL")
        # The bars stay parked so a flip back is instant.
        assert loaded.bars("AAPL", Timeframe.M1)

    async def test_a_reload_works_afterwards(self, loaded):
        loaded.unload("AAPL")
        assert await loaded.ensure_loaded("AAPL") is True


class FakeHub:
    def __init__(self, pairs):
        self._pairs = pairs
        self.sent: list[tuple[str, Timeframe, dict]] = []

    def pairs(self):
        return self._pairs

    def send_to_pair(self, symbol, timeframe, message):
        self.sent.append((symbol, timeframe, message))


class TestBroadcaster:
    async def test_sends_an_update_for_a_watched_chart(self, loaded):
        hub = FakeHub({("AAPL", Timeframe.M1)})
        assert ChartBroadcaster(hub, loaded).tick() == 1
        assert hub.sent[0][2]["type"] == "bar"

    async def test_coalesces_when_nothing_changed(self, loaded):
        """Idle charts must not be re-sent every second."""
        broadcaster = ChartBroadcaster(FakeHub({("AAPL", Timeframe.M1)}), loaded)
        broadcaster.tick()
        assert broadcaster.tick() == 0

    async def test_sends_again_once_data_moves(self, loaded):
        hub = FakeHub({("AAPL", Timeframe.M1)})
        broadcaster = ChartBroadcaster(hub, loaded)
        broadcaster.tick()

        last = loaded.bars("AAPL", Timeframe.M1)[-1]
        await loaded._handle_trade("AAPL", Trade(time=last.time, price=123.0, size=1))
        assert broadcaster.tick() == 1

    async def test_updates_every_watched_timeframe(self, loaded):
        hub = FakeHub({("AAPL", Timeframe.M1), ("AAPL", Timeframe.M5)})
        assert ChartBroadcaster(hub, loaded).tick() == 2

    async def test_update_carries_indicator_values(self, loaded):
        hub = FakeHub({("AAPL", Timeframe.M1)})
        ChartBroadcaster(hub, loaded).tick()
        assert "ema9" in hub.sent[0][2]["series"]

    async def test_sends_nothing_when_no_one_is_watching(self, loaded):
        assert ChartBroadcaster(FakeHub(set()), loaded).tick() == 0
