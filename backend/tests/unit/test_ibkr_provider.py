"""IBKR without TWS.

``ib-async`` is an optional dependency and is not installed for the test run —
that is deliberate, and it is what proves the app works on Alpaca alone. It
also left the IBKR provider almost entirely uncovered, even though it is the
primary data path when TWS *is* running.

These tests supply a stand-in for the library so the provider's own logic —
bar conversion, tick handling, scanner row assembly, sliding-window metrics —
is exercised for real. What is not covered here is the socket handshake itself,
which genuinely needs a gateway.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.core.settings import IBKRSettings, ScannerSettings
from app.domain.scanner import ScannerConfig, ScannerRow
from app.domain.timeframes import Timeframe
from app.market.bar_builder import Trade
from app.providers import ibkr as ibkr_module
from app.providers.ibkr import TRADE_BUFFER_MAX_AGE, IBKRProvider, _clean


# ── stand-ins for ib_async ─────────────────────────────────────────────


class FakeEvent:
    """ib_async exposes callbacks as += / -= event slots."""

    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)
        return self

    def fire(self, *args) -> None:
        for handler in list(self.handlers):
            handler(*args)


class FakeContract:
    def __init__(self, symbol: str, exchange: str = "SMART", currency: str = "USD"):
        self.symbol = symbol
        self.exchange = exchange
        self.currency = currency


class FakeTicker:
    def __init__(self, **fields):
        self.updateEvent = FakeEvent()
        self.ticks: list = []
        self.tickByTicks: list = []
        self.last = fields.get("last")
        self.close = fields.get("close")
        self.volume = fields.get("volume")
        self.vwap = fields.get("vwap")
        self.tradeCount = fields.get("tradeCount")
        self.tradeRate = fields.get("tradeRate")
        self.volumeRate = fields.get("volumeRate")


class FakeHistoricalBar:
    def __init__(self, date, open_, high, low, close, volume, barCount):
        self.date = date
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.barCount = barCount


class FakeScannerSubscription:
    def __init__(self, numberOfRows=0, instrument="", locationCode="", scanCode=""):
        self.numberOfRows = numberOfRows
        self.instrument = instrument
        self.locationCode = locationCode
        self.scanCode = scanCode


class FakeScannerRow:
    def __init__(self, rank: int, symbol: str, exchange: str = "NASDAQ"):
        self.rank = rank
        self.contractDetails = type("Details", (), {"contract": FakeContract(symbol, exchange)})()


class FakeIB:
    def __init__(self) -> None:
        self.connected = False
        self.disconnectedEvent = FakeEvent()
        self.historical: list[FakeHistoricalBar] = []
        self.historical_error: Exception | None = None
        self.history_calls: list[dict] = []
        self.tick_subscriptions: list[str] = []
        self.cancelled_ticks: list[str] = []
        self.market_data: dict[str, FakeTicker] = {}
        self.cancelled_market_data: list[str] = []
        self.scanner_subscription = None
        self.scanner_data = None
        self.scanner_cancelled = False
        self.qualify_failures: set[str] = set()

    def isConnected(self) -> bool:
        return self.connected

    async def connectAsync(self, host, port, clientId=None, readonly=False):
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    async def qualifyContractsAsync(self, contract):
        if contract.symbol in self.qualify_failures:
            raise RuntimeError(f"cannot qualify {contract.symbol}")

    async def reqHistoricalDataAsync(self, contract, **kwargs):
        self.history_calls.append(kwargs)
        if self.historical_error:
            raise self.historical_error
        return self.historical

    def reqTickByTickData(self, contract, tick_type, numberOfTicks=0):
        self.tick_subscriptions.append(contract.symbol)
        return FakeTicker()

    def cancelTickByTickData(self, contract, tick_type):
        self.cancelled_ticks.append(contract.symbol)

    def reqScannerSubscription(self, subscription, scannerSubscriptionFilterOptions=None):
        self.scanner_subscription = subscription
        self.scanner_filter_options = scannerSubscriptionFilterOptions or []
        self.scanner_data = FakeTicker()
        return self.scanner_data

    def cancelScannerSubscription(self, data):
        self.scanner_cancelled = True

    def reqMktData(self, contract, genericTickList=None, snapshot=False):
        ticker = FakeTicker()
        self.market_data[contract.symbol] = ticker
        return ticker

    def cancelMktData(self, contract):
        self.cancelled_market_data.append(contract.symbol)


@pytest.fixture
def provider() -> IBKRProvider:
    """A provider wired to the stand-in, skipping the connection loop."""
    instance = IBKRProvider(IBKRSettings(), ScannerSettings())
    instance._ib = FakeIB()
    instance._stock = FakeContract
    instance._scanner_subscription_cls = FakeScannerSubscription
    instance._ib.connected = True
    return instance


@pytest.fixture
def ib(provider: IBKRProvider) -> FakeIB:
    return provider._ib


@pytest.fixture
async def on_loop(provider: IBKRProvider):
    """Callbacks schedule work on the captured loop."""
    provider._loop = asyncio.get_running_loop()
    return provider


# ── the optional dependency ────────────────────────────────────────────


class TestWithoutTheLibrary:
    async def test_start_is_a_no_op_when_ib_async_is_missing(self, monkeypatch):
        monkeypatch.setattr(ibkr_module, "_import_ib", lambda: None)
        instance = IBKRProvider(IBKRSettings(), ScannerSettings())

        await instance.start()

        assert instance.is_available is False
        assert instance._reconnect_task is None

    async def test_start_respects_being_disabled(self):
        instance = IBKRProvider(IBKRSettings(enabled=False), ScannerSettings())
        await instance.start()
        assert instance.is_available is False

    async def test_stop_is_safe_before_start(self):
        await IBKRProvider(IBKRSettings(), ScannerSettings()).stop()

    async def test_history_returns_nothing_while_unavailable(self):
        instance = IBKRProvider(IBKRSettings(), ScannerSettings())
        bars = await instance.fetch_bars(
            "AAPL", Timeframe.M1, datetime.now(timezone.utc), datetime.now(timezone.utc)
        )
        assert bars == []

    async def test_scanner_refuses_while_unavailable(self):
        instance = IBKRProvider(IBKRSettings(), ScannerSettings())
        assert await instance.start_scanner(ScannerConfig(scan_code="TOP_PERC_GAIN")) is False


class TestCancelAckFilter:
    """The scanner cancel-ack is noise; every other 162 must still log."""

    @staticmethod
    def record(message: str) -> "logging.LogRecord":
        import logging

        return logging.LogRecord("ib_async.wrapper", logging.ERROR, "", 0, message, None, None)

    def test_drops_the_cancel_acknowledgement(self):
        record = self.record(
            "Error 162, reqId 83: Historical Market Data Service error "
            "message:API scanner subscription cancelled: 83"
        )
        assert ibkr_module._CancelAckFilter().filter(record) is False

    def test_keeps_real_historical_data_errors(self):
        record = self.record(
            "Error 162, reqId 12: Historical Market Data Service error "
            "message:HMDS query returned no data"
        )
        assert ibkr_module._CancelAckFilter().filter(record) is True


class TestClean:
    """IBKR reports "no value" as NaN, which must never reach the wire."""

    @pytest.mark.parametrize("value,expected", [(5, 5.0), (2.5, 2.5), (0, 0.0), ("7", 7.0)])
    def test_converts_numbers(self, value, expected):
        assert _clean(value) == expected

    @pytest.mark.parametrize("value", [None, float("nan"), math.nan, "abc", object()])
    def test_rejects_non_values(self, value):
        assert _clean(value) is None


# ── history ────────────────────────────────────────────────────────────


class TestFetchBars:
    async def test_converts_the_library_bars(self, provider, ib):
        ib.historical = [
            FakeHistoricalBar(
                datetime(2024, 3, 5, 14, 30, tzinfo=timezone.utc), 1.0, 2.0, 0.5, 1.5, 900, 12
            )
        ]
        start = datetime(2024, 3, 5, 14, 0, tzinfo=timezone.utc)
        end = datetime(2024, 3, 5, 15, 0, tzinfo=timezone.utc)

        bars = await provider.fetch_bars("AAPL", Timeframe.M1, start, end)

        assert len(bars) == 1
        bar = bars[0]
        assert (bar.open, bar.high, bar.low, bar.close) == (1.0, 2.0, 0.5, 1.5)
        assert bar.volume == pytest.approx(900)
        assert bar.trades == pytest.approx(12)

    async def test_drops_gap_filled_placeholder_bars(self, provider, ib):
        """TWS pads quiet intervals with flat zero-volume bars.

        On an after-hours tape they outnumber real prints four to one and
        render as an invisible chart; the live builder never creates them,
        so history must arrive equally sparse.
        """
        when = datetime(2024, 3, 5, 14, 30, tzinfo=timezone.utc)
        ib.historical = [
            FakeHistoricalBar(when, 5.6, 5.62, 5.6, 5.61, 384, 3),
            FakeHistoricalBar(when + timedelta(seconds=10), 5.61, 5.62, 5.61, 5.61, 0, 0),
            FakeHistoricalBar(when + timedelta(seconds=20), 5.61, 5.62, 5.61, 5.61, 0, 0),
            FakeHistoricalBar(when + timedelta(seconds=30), 5.61, 5.63, 5.61, 5.63, 120, 1),
        ]
        bars = await provider.fetch_bars(
            "BANL",
            Timeframe.S10,
            datetime(2024, 3, 5, 14, tzinfo=timezone.utc),
            datetime(2024, 3, 5, 15, tzinfo=timezone.utc),
        )
        assert [bar.volume for bar in bars] == [pytest.approx(384), pytest.approx(120)]

    async def test_keeps_zero_volume_daily_bars(self, provider, ib):
        """A full-day halt is information, not padding."""
        ib.historical = [
            FakeHistoricalBar(datetime(2024, 3, 5, tzinfo=timezone.utc), 5, 5, 5, 5, 0, 0)
        ]
        bars = await provider.fetch_bars(
            "HALT",
            Timeframe.D1,
            datetime(2024, 2, 5, tzinfo=timezone.utc),
            datetime(2024, 3, 6, tzinfo=timezone.utc),
        )
        assert len(bars) == 1

    async def test_treats_a_naive_timestamp_as_utc(self, provider, ib):
        ib.historical = [FakeHistoricalBar(datetime(2024, 3, 5, 14, 30), 1, 1, 1, 1, 1, 1)]
        bars = await provider.fetch_bars(
            "AAPL",
            Timeframe.M1,
            datetime(2024, 3, 5, 14, tzinfo=timezone.utc),
            datetime(2024, 3, 5, 15, tzinfo=timezone.utc),
        )
        assert bars[0].time == int(datetime(2024, 3, 5, 14, 30, tzinfo=timezone.utc).timestamp())

    async def test_skips_a_bar_with_an_unusable_date(self, provider, ib):
        ib.historical = [FakeHistoricalBar("not a date", 1, 1, 1, 1, 1, 1)]
        bars = await provider.fetch_bars(
            "AAPL",
            Timeframe.M1,
            datetime(2024, 3, 5, 14, tzinfo=timezone.utc),
            datetime(2024, 3, 5, 15, tzinfo=timezone.utc),
        )
        assert bars == []

    async def test_asks_in_seconds_for_a_short_window(self, provider, ib):
        end = datetime.now(timezone.utc)
        await provider.fetch_bars("AAPL", Timeframe.M1, end.replace(microsecond=0), end)
        assert ib.history_calls[0]["durationStr"].endswith(" S")

    async def test_ten_second_bars_use_their_bar_size(self, provider, ib):
        end = datetime(2024, 3, 5, 15, tzinfo=timezone.utc)
        await provider.fetch_bars("AAPL", Timeframe.S10, end - timedelta(hours=1), end)
        assert ib.history_calls[0]["barSizeSetting"] == "10 secs"

    async def test_a_short_ten_second_window_is_one_request(self, provider, ib):
        end = datetime(2024, 3, 5, 15, tzinfo=timezone.utc)
        await provider.fetch_bars("AAPL", Timeframe.S10, end - timedelta(hours=3), end)
        assert len(ib.history_calls) == 1
        # A window ending in the past must carry its explicit end — an empty
        # endDateTime makes TWS serve the most recent bars instead, which is
        # how the background 10s slice silently duplicated the recent one.
        assert ib.history_calls[0]["endDateTime"] == end

    async def test_a_window_ending_now_uses_the_empty_end(self, provider, ib):
        end = datetime.now(timezone.utc)
        await provider.fetch_bars("AAPL", Timeframe.S10, end - timedelta(hours=3), end)
        assert ib.history_calls[0]["endDateTime"] == ""

    async def test_a_long_ten_second_window_is_chunked(self, provider, ib):
        """IBKR caps 10s requests at four hours, so 10 hours takes three.

        The walk goes newest-first with explicit end times, and no chunk may
        span more than the cap.
        """
        end = datetime(2024, 3, 5, 20, tzinfo=timezone.utc)
        await provider.fetch_bars("AAPL", Timeframe.S10, end - timedelta(hours=10), end)

        assert len(ib.history_calls) == 3
        ends = [call["endDateTime"] for call in ib.history_calls]
        assert ends[0] == end
        assert ends == sorted(ends, reverse=True)
        for call in ib.history_calls:
            assert call["barSizeSetting"] == "10 secs"
            assert int(call["durationStr"].removesuffix(" S")) <= 14_400

    async def test_chunks_merge_without_duplicates(self, provider, ib):
        """Chunk boundaries overlap by construction; a bar must land once."""
        ib.historical = [
            FakeHistoricalBar(datetime(2024, 3, 5, 14, 30, 10, tzinfo=timezone.utc), 1, 2, 1, 2, 10, 3),
            FakeHistoricalBar(datetime(2024, 3, 5, 14, 30, 0, tzinfo=timezone.utc), 1, 2, 1, 2, 10, 3),
        ]
        end = datetime(2024, 3, 5, 20, tzinfo=timezone.utc)
        bars = await provider.fetch_bars("AAPL", Timeframe.S10, end - timedelta(hours=10), end)

        assert len(bars) == 2
        assert [bar.time for bar in bars] == sorted(bar.time for bar in bars)

    async def test_asks_in_days_for_a_long_window(self, provider, ib):
        end = datetime(2024, 3, 5, tzinfo=timezone.utc)
        start = datetime(2024, 2, 1, tzinfo=timezone.utc)
        await provider.fetch_bars("AAPL", Timeframe.D1, start, end)
        assert ib.history_calls[0]["durationStr"].endswith(" D")

    async def test_maps_the_timeframe_to_a_bar_size(self, provider, ib):
        end = datetime.now(timezone.utc)
        await provider.fetch_bars("AAPL", Timeframe.M5, end, end)
        assert ib.history_calls[0]["barSizeSetting"] == "5 mins"

    async def test_includes_extended_hours(self, provider, ib):
        # Pre-market is where a small-cap gapper sets up; excluding it would
        # lose the pre-market high entirely.
        end = datetime.now(timezone.utc)
        await provider.fetch_bars("AAPL", Timeframe.M1, end, end)
        assert ib.history_calls[0]["useRTH"] is False

    async def test_an_upstream_failure_yields_no_bars(self, provider, ib):
        ib.historical_error = RuntimeError("no market data permissions")
        bars = await provider.fetch_bars(
            "AAPL", Timeframe.M1, datetime.now(timezone.utc), datetime.now(timezone.utc)
        )
        assert bars == []

    async def test_an_unqualifiable_symbol_yields_no_bars(self, provider, ib):
        ib.qualify_failures.add("NOPE")
        bars = await provider.fetch_bars(
            "NOPE", Timeframe.M1, datetime.now(timezone.utc), datetime.now(timezone.utc)
        )
        assert bars == []

    async def test_contracts_are_reused(self, provider, ib):
        end = datetime.now(timezone.utc)
        await provider.fetch_bars("AAPL", Timeframe.M1, end, end)
        first = provider._contracts["AAPL"]
        await provider.fetch_bars("AAPL", Timeframe.M1, end, end)
        assert provider._contracts["AAPL"] is first


# ── realtime ───────────────────────────────────────────────────────────


class TestStreaming:
    async def test_subscribes_to_the_requested_symbols(self, provider, ib):
        await provider.set_stream_symbols({"AAPL", "TSLA"})
        assert sorted(ib.tick_subscriptions) == ["AAPL", "TSLA"]

    async def test_leaves_an_existing_subscription_alone(self, provider, ib):
        await provider.set_stream_symbols({"AAPL"})
        await provider.set_stream_symbols({"AAPL", "TSLA"})
        assert ib.tick_subscriptions == ["AAPL", "TSLA"]

    async def test_cancels_a_dropped_symbol(self, provider, ib):
        await provider.set_stream_symbols({"AAPL", "TSLA"})
        await provider.set_stream_symbols({"AAPL"})
        assert ib.cancelled_ticks == ["TSLA"]

    async def test_clearing_cancels_everything(self, provider, ib):
        await provider.set_stream_symbols({"AAPL"})
        await provider.set_stream_symbols(set())
        assert ib.cancelled_ticks == ["AAPL"]

    async def test_remembers_symbols_while_disconnected(self, provider, ib):
        ib.connected = False
        await provider.set_stream_symbols({"AAPL"})
        assert ib.tick_subscriptions == []
        assert provider._symbols == {"AAPL"}


class TestTickByTick:
    async def test_emits_a_trade(self, on_loop, ib):
        provider = on_loop
        received: list[tuple[str, Trade]] = []

        async def handler(symbol, trade):
            received.append((symbol, trade))

        provider.on_trade(handler)

        moment = datetime(2024, 3, 5, 14, 30, tzinfo=timezone.utc)
        ticker = FakeTicker()
        ticker.tickByTicks = [type("Tick", (), {"price": 12.5, "size": 100, "time": moment})()]

        provider._on_tick("AAPL", ticker)
        await asyncio.sleep(0)

        symbol, trade = received[0]
        assert symbol == "AAPL"
        assert trade.price == pytest.approx(12.5)
        assert trade.size == pytest.approx(100)
        assert trade.time == pytest.approx(moment.timestamp())

    async def test_drains_the_buffer_so_prints_are_not_replayed(self, on_loop):
        ticker = FakeTicker()
        ticker.tickByTicks = [
            type("Tick", (), {"price": 1.0, "size": 1, "time": datetime.now(timezone.utc)})()
        ]
        on_loop._on_tick("AAPL", ticker)
        assert ticker.tickByTicks == []

    @pytest.mark.parametrize("price,size", [(0, 100), (-1, 100), (10, 0)])
    async def test_ignores_a_print_with_no_substance(self, on_loop, price, size):
        provider = on_loop
        received = []

        async def handler(symbol, trade):
            received.append(trade)

        provider.on_trade(handler)
        ticker = FakeTicker()
        ticker.tickByTicks = [
            type("Tick", (), {"price": price, "size": size, "time": datetime.now(timezone.utc)})()
        ]

        provider._on_tick("AAPL", ticker)
        await asyncio.sleep(0)
        assert received == []

    async def test_an_empty_update_is_ignored(self, on_loop):
        on_loop._on_tick("AAPL", FakeTicker())


class TestTickConditions:
    """Defence in depth: IBKR pre-filters "Last", but a failover to Alpaca
    must not change what a bar means, so the same rule runs on both."""

    @staticmethod
    def _tick(conditions="", *, past_limit=False, unreported=False):
        attribs = type("Attribs", (), {"pastLimit": past_limit, "unreported": unreported})()
        return type("Tick", (), {
            "price": 12.5, "size": 100, "time": datetime.now(timezone.utc),
            "specialConditions": conditions, "tickAttribLast": attribs,
        })()

    async def _emit(self, provider, tick):
        received: list[Trade] = []

        async def handler(symbol, trade):
            received.append(trade)

        provider.on_trade(handler)
        ticker = FakeTicker()
        ticker.tickByTicks = [tick]
        provider._on_tick("AAPL", ticker)
        await asyncio.sleep(0)
        return received

    async def test_an_ordinary_print_forms_price(self, on_loop):
        (trade,) = await self._emit(on_loop, self._tick("@T"))
        assert trade.price_forming is True

    async def test_a_late_report_carries_volume_without_moving_price(self, on_loop):
        """IBKR packs conditions as one string, not a list."""
        (trade,) = await self._emit(on_loop, self._tick("@TZ"))
        assert trade.price_forming is False
        assert trade.size == pytest.approx(100)

    @pytest.mark.parametrize("conditions", ["@M", "@TI"])
    async def test_reprints_and_odd_lots_are_dropped_outright(self, on_loop, conditions):
        assert await self._emit(on_loop, self._tick(conditions)) == []

    @pytest.mark.parametrize("flag", ["past_limit", "unreported"])
    async def test_ibkr_only_flags_bar_price_formation(self, on_loop, flag):
        """Neither has a SIP condition code, so the classifier cannot see them."""
        (trade,) = await self._emit(on_loop, self._tick("@T", **{flag: True}))
        assert trade.price_forming is False


# ── scanner ────────────────────────────────────────────────────────────


class TestScannerSubscription:
    async def test_passes_the_filters_through(self, provider, ib):
        config = ScannerConfig(
            scan_code="TOP_PERC_GAIN",
            above_price=1.5,
            below_price=20.0,
            above_volume=100_000,
            number_of_rows=15,
        )
        assert await provider.start_scanner(config) is True

        subscription = ib.scanner_subscription
        assert subscription.scanCode == "TOP_PERC_GAIN"
        assert subscription.numberOfRows == 15
        assert subscription.abovePrice == 1.5
        assert subscription.belowPrice == 20.0
        assert subscription.aboveVolume == 100_000

    async def test_omits_filters_that_were_not_set(self, provider, ib):
        await provider.start_scanner(ScannerConfig(scan_code="MOST_ACTIVE"))
        assert not hasattr(ib.scanner_subscription, "abovePrice")

    async def test_market_cap_band_lands_on_the_subscription_in_millions(self, provider, ib):
        """IBKR's scanner speaks millions; our config speaks dollars."""
        config = ScannerConfig(
            scan_code="TOP_PERC_GAIN",
            market_cap_above=10_000_000,
            market_cap_below=500_000_000,
        )
        assert await provider.start_scanner(config) is True
        assert ib.scanner_subscription.marketCapAbove == 10
        assert ib.scanner_subscription.marketCapBelow == 500

    async def test_percent_change_rides_the_filter_options(self, provider, ib):
        config = ScannerConfig(scan_code="TOP_PERC_GAIN", change_perc_above=10.0)
        assert await provider.start_scanner(config) is True
        options = dict((o.tag, o.value) for o in ib.scanner_filter_options)
        assert options["changePercAbove"] == "10.0"

    async def test_a_market_cap_ceiling_keeps_large_caps_out(self, provider, ib):
        """Price is not a proxy for size.

        Coupang, SoFi and Grab all cleared a $1-20 price band on the live
        trade-rate scan; only a capitalisation ceiling removes them.
        """
        config = ScannerConfig(scan_code="TOP_TRADE_RATE", market_cap_below=2_000_000_000)
        assert await provider.start_scanner(config) is True
        # IBKR takes millions; our config carries dollars.
        assert ib.scanner_subscription.marketCapBelow == 2000

    async def test_fund_products_are_excluded_by_stock_type(self, provider, ib):
        """`instrument: STK` alone still admits ETFs.

        One tag carrying a comma-separated list: repeating the tag per type
        silently keeps only one of them.
        """
        provider._scanner_settings = ScannerSettings(exclude_stock_types=["ETF", "CEF"])
        await provider.start_scanner(ScannerConfig(scan_code="MOST_ACTIVE"))
        options = dict((o.tag, o.value) for o in ib.scanner_filter_options)
        assert options["stkTypes"] == "exc:ETF,exc:CEF"

    async def test_the_dead_subscription_field_is_left_alone(self, provider, ib):
        """Setting `stockTypeFilter` does nothing — measured, and silently.

        If it ever starts being set, the filter list is the thing that works
        and this guards against a well-meaning "fix" swapping them over.
        """
        await provider.start_scanner(ScannerConfig(scan_code="MOST_ACTIVE"))
        assert not getattr(ib.scanner_subscription, "stockTypeFilter", "")

    async def test_no_filters_at_all_sends_no_options(self, provider, ib):
        provider._scanner_settings = ScannerSettings(exclude_stock_types=[])
        await provider.start_scanner(ScannerConfig(scan_code="MOST_ACTIVE"))
        assert ib.scanner_filter_options == []

    async def test_refresh_loop_reemits_between_ranking_pushes(self, provider, ib):
        """Columns must fill from live tickers, not wait ~30s for IBKR."""
        provider._scanner_settings = ScannerSettings(min_refresh_seconds=0.05)
        emissions: list[list[ScannerRow]] = []

        async def handler(rows):
            emissions.append(rows)

        provider.on_scanner(handler)
        provider._loop = asyncio.get_running_loop()
        await provider.start_scanner(ScannerConfig(scan_code="TOP_TRADE_RATE"))
        try:
            # One ranking push from IBKR; the ticker is empty at that moment.
            provider._on_scanner_update([FakeScannerRow(0, "HOT")])
            await asyncio.sleep(0.02)
            assert emissions and emissions[0][0].price is None

            # The market data line fills in; no further ranking arrives.
            ib.market_data["HOT"].last = 7.5
            ib.market_data["HOT"].tradeRate = 900.0
            await asyncio.sleep(0.15)

            assert emissions[-1][0].price == pytest.approx(7.5)
            assert emissions[-1][0].trades_1m == 900
        finally:
            await provider.stop_scanner()

    async def test_stop_scanner_ends_the_refresh_loop(self, provider):
        provider._scanner_settings = ScannerSettings(min_refresh_seconds=0.05)
        await provider.start_scanner(ScannerConfig(scan_code="MOST_ACTIVE"))
        task = provider._scanner_refresh_task
        assert task is not None
        await provider.stop_scanner()
        assert task.done()

    async def test_reports_a_refusal(self, provider, ib):
        def refuse(subscription):
            raise RuntimeError("scanner subscription limit reached")

        ib.reqScannerSubscription = refuse
        assert await provider.start_scanner(ScannerConfig(scan_code="MOST_ACTIVE")) is False

    async def test_stopping_cancels_the_subscription(self, provider, ib):
        await provider.start_scanner(ScannerConfig(scan_code="MOST_ACTIVE"))
        await provider.stop_scanner()
        assert ib.scanner_cancelled is True

    async def test_stopping_releases_the_row_feeds(self, provider, ib):
        await provider.start_scanner(ScannerConfig(scan_code="MOST_ACTIVE"))
        await provider._process_scanner([FakeScannerRow(0, "ABCD")])
        await provider.stop_scanner()
        assert ib.cancelled_market_data == ["ABCD"]


class TestScannerRows:
    @staticmethod
    async def collect(provider: IBKRProvider, rows: list) -> list[ScannerRow]:
        captured: list[list[ScannerRow]] = []

        async def handler(result):
            captured.append(result)

        provider.on_scanner(handler)
        await provider._process_scanner(rows)
        return captured[0]

    async def test_reports_rank_symbol_and_exchange(self, provider):
        rows = await self.collect(provider, [FakeScannerRow(3, "ABCD", "NASDAQ")])
        assert (rows[0].rank, rows[0].symbol, rows[0].exchange) == (3, "ABCD", "NASDAQ")

    async def test_orders_rows_by_trade_rate(self, provider):
        """The scan picks the universe; prints per minute rank it."""
        entries = [FakeScannerRow(0, "SLOW"), FakeScannerRow(1, "FAST")]
        # First pass registers the per-row market data streams.
        await self.collect(provider, entries)

        now = time.time()
        provider._scanner_streams["FAST"]["trades"].extend((now - i, 5.0, 100) for i in range(30))
        provider._scanner_streams["SLOW"]["trades"].extend((now - i, 5.0, 100) for i in range(3))

        rows = await self.collect(provider, entries)
        assert [row.symbol for row in rows] == ["FAST", "SLOW"]
        assert rows[0].trades_1m > rows[1].trades_1m

    async def test_prefers_ibkr_own_trade_rate_over_the_print_count(self, provider, ib):
        """Tick 294 is what TWS shows; RTVolume prints undercount hot tapes."""
        await self.collect(provider, [FakeScannerRow(0, "HOT")])
        ticker = ib.market_data["HOT"]
        ticker.last = 7.57
        ticker.tradeRate = 1500.0
        ticker.volumeRate = 533_000.0
        # Only a handful of conflated prints actually arrived in the window.
        now = time.time()
        provider._scanner_streams["HOT"]["trades"].extend((now - i, 7.5, 100) for i in range(4))

        rows = await self.collect(provider, [FakeScannerRow(0, "HOT")])
        assert rows[0].trades_1m == 1500
        assert rows[0].dollar_vol_1m == pytest.approx(533_000 * 7.57)

    async def test_falls_back_to_the_window_while_rates_warm_up(self, provider):
        await self.collect(provider, [FakeScannerRow(0, "NEW")])
        now = time.time()
        provider._scanner_streams["NEW"]["trades"].extend((now - i, 4.0, 50) for i in range(5))

        rows = await self.collect(provider, [FakeScannerRow(0, "NEW")])
        assert rows[0].trades_1m == 5
        assert rows[0].dollar_vol_1m == pytest.approx(5 * 4.0 * 50)

    async def test_keeps_the_scan_rank_while_buffers_are_empty(self, provider):
        """Right after a start there are no prints yet; rank order holds."""
        entries = [FakeScannerRow(0, "AAA"), FakeScannerRow(1, "BBB"), FakeScannerRow(2, "CCC")]
        rows = await self.collect(provider, entries)
        assert [row.symbol for row in rows] == ["AAA", "BBB", "CCC"]

    async def test_prefers_the_last_trade_over_the_prior_close(self, provider, ib):
        await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        ib.market_data["ABCD"].last = 12.0
        ib.market_data["ABCD"].close = 10.0

        rows = await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        assert rows[0].price == pytest.approx(12.0)

    async def test_falls_back_to_the_prior_close(self, provider, ib):
        await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        ib.market_data["ABCD"].close = 10.0

        rows = await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        assert rows[0].price == pytest.approx(10.0)

    async def test_computes_the_percentage_change(self, provider, ib):
        await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        ib.market_data["ABCD"].last = 11.0
        ib.market_data["ABCD"].close = 10.0

        rows = await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        assert rows[0].pct_change == pytest.approx(10.0)

    async def test_leaves_change_undefined_without_a_prior_close(self, provider, ib):
        await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        ib.market_data["ABCD"].last = 11.0

        rows = await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        assert rows[0].pct_change is None

    async def test_day_volume_is_converted_from_lots_to_shares(self, provider, ib):
        """Tick 8 counts lots. Reporting it raw was a 100x understatement."""
        await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        ib.market_data["ABCD"].volume = 1_000.0

        rows = await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        assert rows[0].volume == pytest.approx(100_000.0)

    async def test_computes_the_day_dollar_volume(self, provider, ib):
        await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        ib.market_data["ABCD"].volume = 1_000.0
        ib.market_data["ABCD"].vwap = 5.0

        rows = await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        assert rows[0].dollar_vol_day == pytest.approx(500_000.0)

    async def test_ignores_nan_fields(self, provider, ib):
        await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        ib.market_data["ABCD"].last = float("nan")
        ib.market_data["ABCD"].volume = float("nan")

        rows = await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        assert rows[0].price is None and rows[0].volume is None

    async def test_counts_trades_in_the_trailing_windows(self, provider):
        await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        now = time.time()
        trades = provider._scanner_streams["ABCD"]["trades"]
        trades.append((now - 10, 2.0, 100))  # inside 1m
        trades.append((now - 120, 2.0, 50))  # inside 5m only
        trades.append((now - 280, 2.0, 25))  # inside 5m only

        rows = await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        assert rows[0].trades_1m == 1
        assert rows[0].trades_5m == 3

    async def test_sums_dollar_volume_over_the_windows(self, provider):
        await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        now = time.time()
        provider._scanner_streams["ABCD"]["trades"].append((now - 5, 2.0, 100))

        rows = await self.collect(provider, [FakeScannerRow(0, "ABCD")])
        assert rows[0].dollar_vol_1m == pytest.approx(200.0)


class TestScannerStreams:
    async def test_opens_a_feed_for_each_row(self, provider, ib):
        provider._sync_scanner_streams([FakeScannerRow(0, "AAA"), FakeScannerRow(1, "BBB")])
        assert sorted(ib.market_data) == ["AAA", "BBB"]

    async def test_closes_a_feed_when_the_row_drops_out(self, provider, ib):
        provider._sync_scanner_streams([FakeScannerRow(0, "AAA"), FakeScannerRow(1, "BBB")])
        provider._sync_scanner_streams([FakeScannerRow(0, "AAA")])
        assert ib.cancelled_market_data == ["BBB"]

    async def test_keeps_the_trade_buffer_across_refreshes(self, provider):
        # Continuity is the entire point of a sliding window; resubscribing
        # each refresh would reset every rate to zero.
        provider._sync_scanner_streams([FakeScannerRow(0, "AAA")])
        provider._scanner_streams["AAA"]["trades"].append((time.time(), 1.0, 10))

        provider._sync_scanner_streams([FakeScannerRow(0, "AAA"), FakeScannerRow(1, "BBB")])
        assert len(provider._scanner_streams["AAA"]["trades"]) == 1

    async def test_records_incoming_prints(self, provider):
        provider._sync_scanner_streams([FakeScannerRow(0, "AAA")])
        ticker = provider._scanner_streams["AAA"]["ticker"]
        ticker.ticks = [type("T", (), {"price": 3.0, "size": 40})()]

        provider._on_scanner_tick("AAA", ticker)
        assert len(provider._scanner_streams["AAA"]["trades"]) == 1

    async def test_ignores_a_print_with_no_size(self, provider):
        provider._sync_scanner_streams([FakeScannerRow(0, "AAA")])
        ticker = provider._scanner_streams["AAA"]["ticker"]
        ticker.ticks = [type("T", (), {"price": 3.0, "size": 0})()]

        provider._on_scanner_tick("AAA", ticker)
        assert len(provider._scanner_streams["AAA"]["trades"]) == 0

    async def test_prunes_prints_past_the_window(self, provider):
        provider._sync_scanner_streams([FakeScannerRow(0, "AAA")])
        trades = provider._scanner_streams["AAA"]["trades"]
        trades.append((time.time() - TRADE_BUFFER_MAX_AGE - 60, 1.0, 10))

        ticker = provider._scanner_streams["AAA"]["ticker"]
        ticker.ticks = [type("T", (), {"price": 3.0, "size": 40})()]
        provider._on_scanner_tick("AAA", ticker)

        assert len(trades) == 1

    async def test_an_update_for_an_unknown_symbol_is_ignored(self, provider):
        provider._on_scanner_tick("GONE", FakeTicker())
