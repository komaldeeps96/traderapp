"""Market-data lines and the IBKR provider's subscription lifecycle.

The stand-in here keeps ib_async's real bookkeeping (``wrapper.startTicker``):
one Ticker per contract, reused across requests, and a cancel that reaches only
the latest request on it. A line leaked on TWS's side shows up as a request id
that nothing can cancel any more.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from app.core.settings import IBKRSettings, ScannerSettings
from app.domain.scanner import ScannerConfig
from app.domain.timeframes import Timeframe
from app.market.resample import bucket_start
from app.providers.ibkr import IBKRProvider
from app.providers.market_lines import MarketLines
from tests.conftest import ny_epoch
from tests.unit.test_ibkr_provider import (
    TIER_ID,
    FakeContract,
    FakeHistoricalBar,
    FakeIB,
    FakeScannerRow,
    FakeScannerSubscription,
    FakeTicker,
)


class SharingIB(FakeIB):
    def __init__(self) -> None:
        super().__init__()
        self.connected = True
        self.tickers: dict[str, FakeTicker] = {}
        self.latest: dict[str, int] = {}
        self.open_lines: dict[str, list[int]] = {}
        self._ids = 0

    def _ticker(self, symbol: str) -> FakeTicker:
        return self.tickers.setdefault(symbol, FakeTicker())

    def reqMktData(self, contract, genericTickList=None, snapshot=False):
        self._ids += 1
        self.latest[contract.symbol] = self._ids
        self.open_lines.setdefault(contract.symbol, []).append(self._ids)
        self.generic_ticks[contract.symbol] = genericTickList
        ticker = self.market_data[contract.symbol] = self._ticker(contract.symbol)
        return ticker

    def cancelMktData(self, contract):
        self.cancelled_market_data.append(contract.symbol)
        request = self.latest.pop(contract.symbol, None)
        if request is not None:
            self.open_lines[contract.symbol].remove(request)

    def reqTickByTickData(self, contract, tick_type, numberOfTicks=0):
        self.tick_subscriptions.append(contract.symbol)
        return self._ticker(contract.symbol)


@pytest.fixture
def sharing() -> tuple[IBKRProvider, SharingIB]:
    provider = IBKRProvider(IBKRSettings(), ScannerSettings())
    ib = SharingIB()
    provider._ib = ib
    provider._stock = FakeContract
    provider._scanner_subscription_cls = FakeScannerSubscription
    return provider, ib


def listing(*symbols: str) -> list[FakeScannerRow]:
    return [FakeScannerRow(rank, symbol) for rank, symbol in enumerate(symbols)]


def a_print(price: float = 3.0, size: float = 40):
    return type("Print", (), {"price": price, "size": size})()


# ── one line per symbol ────────────────────────────────────────────────


class TestOneLinePerSymbol:
    """A symbol on the chart and in a scanner at once is the ordinary case:
    clicking a scanner row to chart it is exactly how it happens."""

    async def test_the_chart_then_a_scanner_leave_no_line_behind(self, sharing):
        provider, ib = sharing
        await provider.set_stream_symbols({"AAPL"})
        provider._sync_scanner_streams(TIER_ID, listing("AAPL"))
        await provider.set_stream_symbols(set())
        provider._sync_scanner_streams(TIER_ID, listing())
        assert ib.open_lines["AAPL"] == []

    async def test_a_scanner_then_the_chart_leave_no_line_behind(self, sharing):
        provider, ib = sharing
        provider._sync_scanner_streams(TIER_ID, listing("AAPL"))
        await provider.set_stream_symbols({"AAPL"})
        provider._sync_scanner_streams(TIER_ID, listing())
        await provider.set_stream_symbols(set())
        assert ib.open_lines["AAPL"] == []

    async def test_the_one_line_carries_every_owners_ticks(self, sharing):
        provider, ib = sharing
        provider._sync_scanner_streams(TIER_ID, listing("AAPL"))
        await provider.set_stream_symbols({"AAPL"})
        assert ib.generic_ticks["AAPL"] == "233,236,292,293,294,295"
        assert len(ib.open_lines["AAPL"]) == 1

    async def test_the_scanner_letting_go_keeps_the_charts_line(self, sharing):
        provider, ib = sharing
        await provider.set_stream_symbols({"AAPL"})
        provider._sync_scanner_streams(TIER_ID, listing("AAPL"))
        provider._sync_scanner_streams(TIER_ID, listing())
        assert len(ib.open_lines["AAPL"]) == 1
        assert provider._lines.owners("AAPL") == {"chart"}

    async def test_a_quote_on_a_shared_line_reaches_the_chart_once(self, sharing):
        provider, ib = sharing
        provider._loop = asyncio.get_running_loop()
        quotes: list = []

        async def on_quote(symbol, quote):
            quotes.append((symbol, quote.bid, quote.ask))

        provider.on_quote(on_quote)
        await provider.set_stream_symbols({"AAPL"})
        provider._sync_scanner_streams(TIER_ID, listing("AAPL"))
        ticker = ib.tickers["AAPL"]
        ticker.bid, ticker.ask, ticker.bidSize, ticker.askSize = 4.25, 4.27, 3, 4
        ticker.updateEvent.fire(ticker)
        await asyncio.sleep(0)
        assert quotes == [("AAPL", 4.25, 4.27)]


# ── listeners that pile up ─────────────────────────────────────────────


class TestListenersDoNotPileUp:
    """eventkit runs a listener once per add, and ib_async hands back the same
    Ticker when a symbol returns, so each add has to be matched by a remove."""

    async def test_a_symbol_leaving_and_returning_is_heard_once(self, sharing):
        provider, ib = sharing
        for symbols in ({"AAPL"}, set(), {"AAPL"}):
            await provider.set_stream_symbols(symbols)
        # One for the tick-by-tick stream, one for the shared market-data line.
        assert len(ib.tickers["AAPL"].updateEvent.handlers) == 2

    async def test_a_row_leaving_and_returning_counts_each_print_once(self, sharing):
        provider, ib = sharing
        for rows in (listing("AAA"), listing(), listing("AAA")):
            provider._sync_scanner_streams(TIER_ID, rows)
        ticker = ib.tickers["AAA"]
        ticker.ticks = [a_print()]
        ticker.updateEvent.fire(ticker)
        assert len(provider._scanner_streams["AAA"]["trades"]) == 1

    async def test_two_tiers_on_one_symbol_count_each_print_once(self, sharing):
        provider, ib = sharing
        provider._sync_scanner_streams(TIER_ID, listing("AAA"))
        provider._sync_scanner_streams("mid_cap", listing("AAA"))
        ticker = ib.tickers["AAA"]
        ticker.ticks = [a_print()]
        ticker.updateEvent.fire(ticker)
        assert len(provider._scanner_streams["AAA"]["trades"]) == 1

    async def test_a_reconnect_does_not_double_the_connection_listeners(self, sharing):
        """Every headline would otherwise be delivered once per reconnect."""
        provider, ib = sharing
        provider._attach()
        provider._attach()
        assert len(ib.disconnectedEvent.handlers) == 1
        assert len(ib.tickNewsEvent.handlers) == 1


# ── a dropped connection ───────────────────────────────────────────────


class TestADroppedConnection:
    async def test_forgets_its_scans_so_the_service_restarts_them(self, sharing):
        """Rows kept from before the drop were re-emitted every few seconds,
        reading as a running scan, so none was started on reconnect."""
        provider, _ = sharing
        await provider.start_scanner(TIER_ID, ScannerConfig(scan_code="TOP_TRADE_RATE"))
        refresh = provider._scanner_refresh_tasks[TIER_ID]
        provider._scanner_raw[TIER_ID] = listing("HOT")

        provider._on_disconnected()
        await asyncio.sleep(0)

        assert refresh.cancelled()
        assert provider._scanner_data == {}
        assert provider._scanner_raw == {}

    async def test_rows_queued_before_the_drop_are_not_emitted(self, sharing):
        provider, ib = sharing
        emitted: list = []

        async def handler(rows):
            emitted.append(rows)

        provider.on_scanner(TIER_ID, handler)
        await provider.start_scanner(TIER_ID, ScannerConfig(scan_code="TOP_TRADE_RATE"))
        provider._on_disconnected()
        ib.connected = False

        await provider._process_scanner(TIER_ID, listing("HOT"))
        assert emitted == []
        assert "HOT" not in ib.open_lines

    async def test_rows_arriving_after_a_stop_open_no_line(self, sharing):
        provider, ib = sharing
        await provider.start_scanner(TIER_ID, ScannerConfig(scan_code="TOP_TRADE_RATE"))
        await provider.stop_scanner(TIER_ID)
        await provider._process_scanner(TIER_ID, listing("LATE"))
        assert "LATE" not in ib.open_lines

    async def test_lines_held_across_the_drop_are_not_cancelled_later(self, sharing):
        """TWS let them go with the connection; cancelling a dead request id on
        the next connection would cancel whatever now has it."""
        provider, ib = sharing
        await provider.set_stream_symbols({"AAPL"})
        provider._on_disconnected()
        await provider.set_stream_symbols(set())
        assert ib.cancelled_market_data == []


# ── daily history ──────────────────────────────────────────────────────


WINDOW = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 9, 12, tzinfo=UTC))


class TestDailyHistoryFromIBKR:
    """ib_async dates a daily bar with a ``date``, not a ``datetime``. Every one
    was skipped, which went unseen only because Alpaca is asked first."""

    async def test_a_daily_bar_is_kept_at_new_york_midnight(self, sharing):
        provider, ib = sharing
        ib.historical = [FakeHistoricalBar(date(2026, 9, 11), 10, 11, 9, 10.5, 1_000, 50)]
        bars = await provider.fetch_bars("AAPL", Timeframe.D1, *WINDOW)
        assert [(bar.time, bar.close) for bar in bars] == [(ny_epoch(2026, 9, 11), 10.5)]

    async def test_a_weekly_bar_lands_on_the_start_of_its_week(self, sharing):
        provider, ib = sharing
        ib.historical = [FakeHistoricalBar(date(2026, 9, 11), 10, 11, 9, 10.5, 1_000, 50)]
        bars = await provider.fetch_bars("AAPL", Timeframe.W1, *WINDOW)
        assert bars[0].time == bucket_start(ny_epoch(2026, 9, 11), Timeframe.W1)


# ── quotes ─────────────────────────────────────────────────────────────


class TestQuotes:
    async def test_an_unchanged_book_is_not_sent_again(self, sharing):
        """The quote line also updates on every trade print."""
        provider, _ = sharing
        provider._loop = asyncio.get_running_loop()
        quotes: list = []

        async def on_quote(symbol, quote):
            quotes.append(quote.ask)

        provider.on_quote(on_quote)
        ticker = FakeTicker()
        ticker.bid, ticker.ask, ticker.bidSize, ticker.askSize = 4.25, 4.27, 1, 2
        provider._on_quote("AAPL", ticker)
        provider._on_quote("AAPL", ticker)
        ticker.ask = 4.28
        provider._on_quote("AAPL", ticker)
        await asyncio.sleep(0)
        assert quotes == [4.27, 4.28]


# ── the registry on its own ────────────────────────────────────────────


class TestMarketLines:
    @staticmethod
    def build() -> tuple[MarketLines, SharingIB]:
        ib = SharingIB()
        return MarketLines(lambda: ib), ib

    def test_an_owner_needing_nothing_new_costs_no_request(self):
        lines, ib = self.build()
        lines.acquire("AAA", FakeContract("AAA"), "a", frozenset({"233", "293"}), print)
        lines.acquire("AAA", FakeContract("AAA"), "b", frozenset({"233"}), print)
        assert ib.open_lines["AAA"] == [1]

    def test_a_wider_owner_reissues_the_one_line(self):
        lines, ib = self.build()
        lines.acquire("AAA", FakeContract("AAA"), "a", frozenset({"233"}), print)
        lines.acquire("AAA", FakeContract("AAA"), "b", frozenset({"236"}), print)
        assert ib.open_lines["AAA"] == [2]
        assert ib.generic_ticks["AAA"] == "233,236"

    def test_releasing_as_someone_who_never_held_it_does_nothing(self):
        lines, ib = self.build()
        lines.acquire("AAA", FakeContract("AAA"), "a", frozenset({"233"}), print)
        lines.release("AAA", "stranger")
        assert ib.open_lines["AAA"] == [1]

    def test_a_refused_request_holds_nothing(self):
        lines, ib = self.build()

        def refuse(*_args, **_kwargs):
            raise RuntimeError("max number of tickers reached")

        ib.reqMktData = refuse
        assert lines.acquire("AAA", FakeContract("AAA"), "a", frozenset({"233"}), print) is None
        assert lines.owners("AAA") == set()
