"""IBKR → Alpaca failover.

The app has to keep charting when TWS is not running, when it goes away
mid-session, and when it comes back. These tests drive the router directly
with stub providers so each transition can be forced deterministically.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.settings import HistorySettings
from app.domain.bars import Bar
from app.domain.protocol import DataSource
from app.domain.timeframes import Timeframe
from app.market.bar_builder import Trade
from app.providers.base import MarketDataProvider
from app.providers.router import FeedRouter


class StubProvider(MarketDataProvider):
    def __init__(self, name: str, *, available: bool = True, delayed: bool = False):
        super().__init__()
        self.name = name
        self.available = available
        self.delayed = delayed
        self.streamed: set[str] = set()
        self.bars: list[Bar] = []
        self.fetch_calls: list[tuple[str, Timeframe]] = []
        self.fail = False

    @property
    def is_available(self) -> bool:
        return self.available

    @property
    def is_delayed(self) -> bool:
        return self.delayed

    async def fetch_bars(self, symbol, timeframe, start, end):
        self.fetch_calls.append((symbol, timeframe))
        if self.fail:
            raise RuntimeError(f"{self.name} is broken")
        return list(self.bars)

    async def set_stream_symbols(self, symbols):
        self.streamed = set(symbols)

    async def go_offline(self):
        self.available = False
        await self._emit_status()

    async def come_online(self):
        self.available = True
        await self._emit_status()


@pytest.fixture
def alpaca():
    return StubProvider("alpaca")


@pytest.fixture
def ibkr():
    return StubProvider("ibkr", available=False)


@pytest.fixture
def router(alpaca, ibkr):
    return FeedRouter(alpaca, ibkr, HistorySettings())


class TestSourceSelection:
    async def test_prefers_ibkr_when_it_is_up(self, router, ibkr):
        ibkr.available = True
        assert router.active_source is DataSource.IBKR

    async def test_falls_back_to_alpaca(self, router):
        assert router.active_source is DataSource.ALPACA

    async def test_reports_none_when_nothing_is_available(self, router, alpaca):
        alpaca.available = False
        assert router.active_source is DataSource.NONE

    async def test_ibkr_is_never_delayed(self, router, ibkr, alpaca):
        ibkr.available = True
        alpaca.delayed = True
        assert router.is_delayed is False

    async def test_surfaces_an_alpaca_delay(self, router, alpaca):
        alpaca.delayed = True
        assert router.is_delayed is True

    async def test_explains_the_fallback(self, router):
        assert "IBKR unavailable" in router.status_note()

    async def test_mentions_the_delay_in_the_note(self, router, alpaca):
        alpaca.delayed = True
        assert "15-minute delayed" in router.status_note()

    async def test_says_nothing_when_ibkr_is_live(self, router, ibkr):
        ibkr.available = True
        assert router.status_note() is None

    async def test_warns_when_no_provider_is_usable(self, router, alpaca):
        alpaca.available = False
        assert "No market data provider" in router.status_note()


class TestStreamRouting:
    async def test_streams_from_alpaca_when_ibkr_is_down(self, router, alpaca, ibkr):
        await router.set_stream_symbols({"AAPL"})
        assert alpaca.streamed == {"AAPL"}
        assert ibkr.streamed == set()

    async def test_streams_from_ibkr_when_it_is_up(self, router, alpaca, ibkr):
        ibkr.available = True
        await router.set_stream_symbols({"AAPL"})
        assert ibkr.streamed == {"AAPL"}
        assert alpaca.streamed == set()

    async def test_moves_the_stream_when_ibkr_appears(self, router, alpaca, ibkr):
        await router.set_stream_symbols({"AAPL"})
        assert alpaca.streamed == {"AAPL"}

        await ibkr.come_online()
        assert ibkr.streamed == {"AAPL"}
        assert alpaca.streamed == set(), "Alpaca must stop once IBKR takes over"

    async def test_moves_the_stream_back_when_ibkr_drops(self, router, alpaca, ibkr):
        ibkr.available = True
        await router.set_stream_symbols({"AAPL"})
        await ibkr.go_offline()
        assert alpaca.streamed == {"AAPL"}

    async def test_never_streams_from_both_at_once(self, router, alpaca, ibkr):
        """Double-streaming would double-count volume on the live bar."""
        await router.set_stream_symbols({"AAPL"})
        for _ in range(3):
            await ibkr.come_online()
            assert not (ibkr.streamed and alpaca.streamed)
            await ibkr.go_offline()
            assert not (ibkr.streamed and alpaca.streamed)

    async def test_clears_both_when_nothing_is_watched(self, router, alpaca, ibkr):
        await router.set_stream_symbols({"AAPL"})
        await router.set_stream_symbols(set())
        assert alpaca.streamed == set() and ibkr.streamed == set()

    async def test_tracks_several_symbols(self, router, alpaca):
        await router.set_stream_symbols({"AAPL", "TSLA"})
        assert alpaca.streamed == {"AAPL", "TSLA"}


class TestEventForwarding:
    async def test_forwards_trades_from_the_active_provider(self, router, alpaca):
        seen = []

        async def on_trade(symbol, trade):
            seen.append((symbol, trade.price))

        router.on_trade(on_trade)
        await alpaca._emit_trade("AAPL", Trade(time=1_700_000_000, price=12.5, size=10))
        assert seen == [("AAPL", 12.5)]

    async def test_forwards_bars(self, router, alpaca):
        seen = []

        async def on_bar(symbol, timeframe, bar):
            seen.append((symbol, bar.close))

        router.on_bar(on_bar)
        await alpaca._emit_bar(
            "AAPL", Timeframe.M1, Bar(time=60, open=1, high=2, low=0, close=1.5, volume=10)
        )
        assert seen == [("AAPL", 1.5)]

    async def test_forwards_from_ibkr_too(self, router, ibkr):
        seen = []

        async def on_trade(symbol, trade):
            seen.append(symbol)

        router.on_trade(on_trade)
        await ibkr._emit_trade("TSLA", Trade(time=1_700_000_000, price=1.0, size=1))
        assert seen == ["TSLA"]


class TestHistoryAssembly:
    async def test_uses_alpaca_alone_when_ibkr_is_down(self, router, alpaca, ibkr):
        alpaca.bars = [Bar(time=60, open=1, high=1, low=1, close=1, volume=1)]
        bars = await router.fetch_history("AAPL", Timeframe.M1)
        assert len(bars) == 1
        assert ibkr.fetch_calls == []

    async def test_ibkr_overwrites_alpaca_on_a_shared_minute(self, router, alpaca, ibkr):
        """The precise bar must replace, not add to, the delayed one."""
        ibkr.available = True
        alpaca.bars = [Bar(time=60, open=1, high=1, low=1, close=1, volume=100)]
        ibkr.bars = [Bar(time=60, open=2, high=2, low=2, close=2, volume=300)]

        bars = await router.fetch_history("AAPL", Timeframe.M1)
        assert len(bars) == 1
        assert bars[0].close == pytest.approx(2)
        assert bars[0].volume == pytest.approx(300), "volume must not be summed"

    async def test_keeps_older_alpaca_bars_ibkr_does_not_cover(self, router, alpaca, ibkr):
        ibkr.available = True
        alpaca.bars = [
            Bar(time=60, open=1, high=1, low=1, close=1, volume=1),
            Bar(time=120, open=1, high=1, low=1, close=1, volume=1),
        ]
        ibkr.bars = [Bar(time=120, open=9, high=9, low=9, close=9, volume=9)]

        bars = await router.fetch_history("AAPL", Timeframe.M1)
        assert [b.time for b in bars] == [60, 120]
        assert bars[1].close == pytest.approx(9)

    async def test_survives_one_provider_failing(self, router, alpaca, ibkr):
        ibkr.available = True
        ibkr.fail = True
        alpaca.bars = [Bar(time=60, open=1, high=1, low=1, close=1, volume=1)]
        assert len(await router.fetch_history("AAPL", Timeframe.M1)) == 1

    async def test_returns_empty_when_everything_fails(self, router, alpaca):
        alpaca.fail = True
        assert await router.fetch_history("AAPL", Timeframe.M1) == []

    async def test_daily_history_prefers_alpaca(self, router, alpaca, ibkr):
        ibkr.available = True
        alpaca.bars = [Bar(time=86_400, open=1, high=1, low=1, close=1, volume=1)]
        await router.fetch_history("AAPL", Timeframe.D1)
        assert (("AAPL", Timeframe.D1)) in alpaca.fetch_calls
        assert ibkr.fetch_calls == []

    async def test_daily_falls_back_to_ibkr(self, router, alpaca, ibkr):
        ibkr.available = True
        alpaca.available = False
        ibkr.bars = [Bar(time=86_400, open=1, high=1, low=1, close=1, volume=1)]
        assert len(await router.fetch_history("AAPL", Timeframe.D1)) == 1

    async def test_asks_ibkr_only_for_the_recent_window(self, router, alpaca, ibkr):
        """IBKR history is capped; Alpaca supplies the long tail."""
        ibkr.available = True
        captured = {}

        async def record(symbol, timeframe, start, end):
            captured[timeframe] = end - start
            return []

        ibkr.fetch_bars = record
        await router.fetch_history("AAPL", Timeframe.M1)
        assert captured[Timeframe.M1] == timedelta(seconds=HistorySettings().ibkr_recent_seconds)

    async def test_derived_timeframes_load_their_base(self, router, alpaca):
        await router.fetch_history("AAPL", Timeframe.M15)
        assert alpaca.fetch_calls[-1] == ("AAPL", Timeframe.M1)

    async def test_weekly_loads_daily(self, router, alpaca):
        await router.fetch_history("AAPL", Timeframe.W1)
        assert alpaca.fetch_calls[-1] == ("AAPL", Timeframe.D1)

    async def test_intraday_window_matches_settings(self, router, alpaca):
        captured = {}

        async def record(symbol, timeframe, start, end):
            captured["span"] = end - start
            return []

        alpaca.fetch_bars = record
        await router.fetch_history("AAPL", Timeframe.M1)
        assert captured["span"] == timedelta(days=HistorySettings().intraday_days)
