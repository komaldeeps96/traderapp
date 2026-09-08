"""Alpaca's streaming half.

The REST path is exercised end to end by the integration suite. The socket is
stubbed out there, which left the code that decodes every live trade and bar
untested — so it is covered here directly, without a network.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.settings import AlpacaSettings
from app.domain.bars import Bar
from app.domain.timeframes import Timeframe
from app.market.bar_builder import Trade
from app.providers.alpaca import (
    DELAYED_WINDOW,
    AlpacaProvider,
    ProviderError,
    _channels,
    _decode,
    _parse_bar,
    _parse_status,
)


def make_provider(**overrides) -> AlpacaProvider:
    settings = AlpacaSettings(key_id="key", secret_key="secret", **overrides)
    return AlpacaProvider(settings)


class Recorder:
    """Collects the events a provider emits."""

    def __init__(self, provider: AlpacaProvider):
        self.trades: list[tuple[str, Trade]] = []
        self.bars: list[tuple[str, Timeframe, Bar]] = []
        self.status_changes = 0
        self.halts: list[tuple[str, bool]] = []
        provider.on_trade(self._trade)
        provider.on_bar(self._bar)
        provider.on_status_change(self._status)
        provider.on_halt(self._halt)

    async def _trade(self, symbol: str, trade: Trade) -> None:
        self.trades.append((symbol, trade))

    async def _bar(self, symbol: str, timeframe: Timeframe, bar: Bar) -> None:
        self.bars.append((symbol, timeframe, bar))

    async def _status(self) -> None:
        self.status_changes += 1

    async def _halt(self, symbol: str, halted: bool) -> None:
        self.halts.append((symbol, halted))


class FakeSocket:
    """A websocket whose script the test writes."""

    def __init__(self, inbound: list[object] | None = None):
        self.sent: list[dict] = []
        self._inbound = list(inbound or [])

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def recv(self) -> str:
        if not self._inbound:
            # Stall rather than raise, so the auth timeout can be exercised.
            await asyncio.sleep(3600)
        message = self._inbound.pop(0)
        return message if isinstance(message, str) else json.dumps(message)


# ── frame decoding ─────────────────────────────────────────────────────


class TestDecode:
    def test_unwraps_the_array_alpaca_sends(self):
        assert _decode('[{"T":"t"},{"T":"b"}]') == [{"T": "t"}, {"T": "b"}]

    def test_accepts_a_bare_object(self):
        assert _decode('{"T":"success"}') == [{"T": "success"}]

    def test_accepts_bytes(self):
        assert _decode(b'[{"T":"t"}]') == [{"T": "t"}]

    def test_survives_malformed_json(self):
        assert _decode("{not json") == []

    def test_drops_non_object_entries(self):
        assert _decode('[{"T":"t"}, 5, null, "x"]') == [{"T": "t"}]

    def test_handles_an_empty_batch(self):
        assert _decode("[]") == []


class TestParseBar:
    def test_maps_every_field(self):
        bar = _parse_bar(
            {"t": "2024-03-05T14:30:00Z", "o": 1.5, "h": 2.0, "l": 1.0, "c": 1.8, "v": 900, "n": 12}
        )
        assert (bar.open, bar.high, bar.low, bar.close) == (1.5, 2.0, 1.0, 1.8)
        assert bar.volume == pytest.approx(900)
        assert bar.trades == pytest.approx(12)

    def test_converts_the_timestamp_to_epoch_seconds(self):
        bar = _parse_bar({"t": "2024-03-05T14:30:00Z", "o": 1, "h": 1, "l": 1, "c": 1})
        assert bar.time == int(datetime(2024, 3, 5, 14, 30, tzinfo=UTC).timestamp())

    def test_tolerates_nanosecond_precision(self):
        # Alpaca sends up to nine fractional digits; datetime accepts six.
        bar = _parse_bar({"t": "2024-03-05T14:30:00.123456789Z", "o": 1, "h": 1, "l": 1, "c": 1})
        assert bar.time == int(datetime(2024, 3, 5, 14, 30, tzinfo=UTC).timestamp())

    def test_defaults_missing_volume_and_trades(self):
        bar = _parse_bar({"t": "2024-03-05T14:30:00Z", "o": 1, "h": 1, "l": 1, "c": 1})
        assert bar.volume == 0.0 and bar.trades == 0.0


class TestChannels:
    def test_subscribes_to_trades_and_bars(self):
        # Trades drive the live bar; the minute bar that follows corrects its
        # volume, so both tapes are needed.
        assert _channels({"AAPL"}) == {"trades": ["AAPL"], "quotes": ["AAPL"], "bars": ["AAPL"]}

    def test_sorts_symbols_for_a_stable_payload(self):
        assert _channels({"TSLA", "AAPL"})["trades"] == ["AAPL", "TSLA"]


# ── live frames ────────────────────────────────────────────────────────


class TestParseStatus:
    @pytest.mark.parametrize(
        ("frame", "expected"),
        [
            ({"sc": "H", "sm": "Trading Halt"}, True),
            ({"sc": "P", "sm": "Pause"}, True),
            ({"sc": "V", "sm": "Volatility Trading Pause"}, True),
            # The resume announcement contains the word "trading" too; the
            # halt check must win on the halt message, not on this one.
            ({"sc": "T", "sm": "Trading Resumption"}, False),
            ({"sc": "", "sm": "Resume"}, False),
            ({"sc": "Z", "sm": "Something New"}, None),
            ({}, None),
        ],
    )
    def test_reads_the_code_then_the_message(self, frame, expected):
        assert _parse_status(frame) is expected


class TestStatusFrames:
    async def test_a_halt_frame_reaches_the_halt_handler(self):
        provider = make_provider()
        events = Recorder(provider)
        await provider._handle_frame(
            json.dumps([{"T": "s", "S": "FGI", "sc": "H", "sm": "Trading Halt", "rc": "LUDP"}])
        )
        assert events.halts == [("FGI", True)]

    async def test_a_resume_frame_reaches_it_too(self):
        provider = make_provider()
        events = Recorder(provider)
        await provider._handle_frame(
            json.dumps([{"T": "s", "S": "FGI", "sc": "T", "sm": "Trading Resumption"}])
        )
        assert events.halts == [("FGI", False)]

    async def test_an_unrecognised_status_is_dropped(self):
        provider = make_provider()
        events = Recorder(provider)
        await provider._handle_frame(json.dumps([{"T": "s", "S": "FGI", "sc": "Z", "sm": "?"}]))
        assert events.halts == []

    async def test_a_status_without_a_symbol_is_dropped(self):
        provider = make_provider()
        events = Recorder(provider)
        await provider._handle_frame(json.dumps([{"T": "s", "sc": "H", "sm": "Trading Halt"}]))
        assert events.halts == []


class TestHandleFrame:
    async def test_emits_a_trade(self):
        provider = make_provider()
        events = Recorder(provider)

        await provider._handle_frame(
            json.dumps([{"T": "t", "S": "AAPL", "p": 12.34, "s": 50, "t": "2024-03-05T14:30:00Z"}])
        )

        symbol, trade = events.trades[0]
        assert symbol == "AAPL"
        assert trade.price == pytest.approx(12.34)
        assert trade.size == pytest.approx(50)

    async def test_an_average_price_print_keeps_volume_but_not_price(self):
        provider = make_provider()
        events = Recorder(provider)

        await provider._handle_frame(
            json.dumps(
                [{"T": "t", "S": "AAPL", "p": 9.0, "s": 5_000_000, "c": ["@", "W"], "t": "2024-03-05T14:30:00Z"}]
            )
        )

        trade = events.trades[0][1]
        assert trade.price_forming is False
        assert trade.size == pytest.approx(5_000_000)

    async def test_an_official_close_reprint_is_dropped(self):
        provider = make_provider()
        events = Recorder(provider)

        await provider._handle_frame(
            json.dumps(
                [{"T": "t", "S": "AAPL", "p": 12.0, "s": 100, "c": ["M"], "t": "2024-03-05T20:00:00Z"}]
            )
        )
        assert events.trades == []

    async def test_a_plain_trade_stays_price_forming(self):
        provider = make_provider()
        events = Recorder(provider)

        await provider._handle_frame(
            json.dumps(
                [{"T": "t", "S": "AAPL", "p": 12.0, "s": 100, "c": ["@", "T"], "t": "2024-03-05T12:30:00Z"}]
            )
        )
        assert events.trades[0][1].price_forming is True

    async def test_trade_timestamp_survives_nanoseconds(self):
        provider = make_provider()
        events = Recorder(provider)

        await provider._handle_frame(
            json.dumps(
                [{"T": "t", "S": "AAPL", "p": 1.0, "s": 1, "t": "2024-03-05T14:30:00.123456789Z"}]
            )
        )
        assert events.trades[0][1].time == pytest.approx(
            datetime(2024, 3, 5, 14, 30, tzinfo=UTC).timestamp(), abs=1
        )

    async def test_emits_a_minute_bar(self):
        provider = make_provider()
        events = Recorder(provider)

        await provider._handle_frame(
            json.dumps(
                [
                    {
                        "T": "b",
                        "S": "TSLA",
                        "o": 1,
                        "h": 2,
                        "l": 0.5,
                        "c": 1.5,
                        "v": 100,
                        "n": 4,
                        "t": "2024-03-05T14:31:00Z",
                    }
                ]
            )
        )

        symbol, timeframe, bar = events.bars[0]
        assert symbol == "TSLA"
        assert timeframe is Timeframe.M1
        assert bar.close == pytest.approx(1.5)

    async def test_handles_a_batch_of_mixed_messages(self):
        provider = make_provider()
        events = Recorder(provider)

        await provider._handle_frame(
            json.dumps(
                [
                    {"T": "t", "S": "AAPL", "p": 1, "s": 1, "t": "2024-03-05T14:30:00Z"},
                    {"T": "b", "S": "AAPL", "o": 1, "h": 1, "l": 1, "c": 1, "t": "2024-03-05T14:30:00Z"},
                    {"T": "subscription", "trades": ["AAPL"], "bars": ["AAPL"]},
                ]
            )
        )
        assert len(events.trades) == 1 and len(events.bars) == 1

    async def test_ignores_a_trade_with_no_size(self):
        provider = make_provider()
        events = Recorder(provider)
        await provider._handle_frame(
            json.dumps([{"T": "t", "S": "AAPL", "p": 5, "t": "2024-03-05T14:30:00Z"}])
        )
        assert events.trades[0][1].size == 0.0

    async def test_logs_an_error_frame_without_raising(self):
        provider = make_provider()
        events = Recorder(provider)
        await provider._handle_frame(json.dumps([{"T": "error", "code": 400, "msg": "bad"}]))
        assert events.trades == [] and events.bars == []

    async def test_ignores_an_unknown_message_type(self):
        provider = make_provider()
        events = Recorder(provider)
        await provider._handle_frame(json.dumps([{"T": "q", "S": "AAPL"}]))
        assert events.trades == [] and events.bars == []

    async def test_survives_a_corrupt_frame(self):
        provider = make_provider()
        await provider._handle_frame("not json at all")


# ── authentication ─────────────────────────────────────────────────────


class TestAuthenticate:
    async def test_sends_the_credentials(self):
        provider = make_provider()
        socket = FakeSocket([[{"T": "success", "msg": "authenticated"}]])

        await provider._authenticate(socket)

        assert socket.sent[0] == {"action": "auth", "key": "key", "secret": "secret"}

    async def test_accepts_a_greeting_before_the_answer(self):
        # The server says "connected" first; that must not read as a failure.
        provider = make_provider()
        socket = FakeSocket(
            [[{"T": "success", "msg": "connected"}], [{"T": "success", "msg": "authenticated"}]]
        )
        await provider._authenticate(socket)

    async def test_raises_on_rejection(self):
        provider = make_provider()
        socket = FakeSocket([[{"T": "error", "code": 402, "msg": "auth failed"}]])

        with pytest.raises(ProviderError, match="auth failed"):
            await provider._authenticate(socket)

    async def test_reports_the_error_code(self):
        provider = make_provider()
        socket = FakeSocket([[{"T": "error", "code": 406, "msg": "connection limit"}]])
        with pytest.raises(ProviderError, match="406"):
            await provider._authenticate(socket)


# ── subscription diffing ───────────────────────────────────────────────


class TestSetStreamSymbols:
    @staticmethod
    async def _with_live_socket(provider: AlpacaProvider) -> FakeSocket:
        """Pretend the stream is already up, so the diff path is taken."""
        socket = FakeSocket()
        provider._ws = socket
        provider._stream_task = asyncio.create_task(asyncio.sleep(3600))
        provider._symbols = {"AAPL"}
        return socket

    async def test_subscribes_to_a_new_symbol(self):
        provider = make_provider()
        socket = await self._with_live_socket(provider)
        try:
            await provider.set_stream_symbols({"AAPL", "TSLA"})
            assert {"action": "subscribe", "trades": ["TSLA"], "quotes": ["TSLA"], "bars": ["TSLA"]} in socket.sent
        finally:
            provider._stream_task.cancel()

    async def test_unsubscribes_from_a_dropped_symbol(self):
        provider = make_provider()
        socket = await self._with_live_socket(provider)
        try:
            await provider.set_stream_symbols({"TSLA"})
            assert {"action": "unsubscribe", "trades": ["AAPL"], "quotes": ["AAPL"], "bars": ["AAPL"]} in socket.sent
        finally:
            provider._stream_task.cancel()

    async def test_does_nothing_when_the_set_is_unchanged(self):
        provider = make_provider()
        socket = await self._with_live_socket(provider)
        try:
            await provider.set_stream_symbols({"AAPL"})
            assert socket.sent == []
        finally:
            provider._stream_task.cancel()

    async def test_clearing_unsubscribes_everything(self):
        provider = make_provider()
        socket = await self._with_live_socket(provider)
        try:
            await provider.set_stream_symbols(set())
            assert socket.sent == [
                {"action": "unsubscribe", "trades": ["AAPL"], "quotes": ["AAPL"], "bars": ["AAPL"]}
            ]
        finally:
            provider._stream_task.cancel()

    async def test_does_nothing_without_credentials(self):
        provider = AlpacaProvider(AlpacaSettings())
        await provider.set_stream_symbols({"AAPL"})
        assert provider._stream_task is None

    async def test_a_send_failure_does_not_propagate(self):
        provider = make_provider()

        class Broken(FakeSocket):
            async def send(self, payload: str) -> None:
                raise RuntimeError("socket gone")

        provider._ws = Broken()
        provider._stream_task = asyncio.create_task(asyncio.sleep(3600))
        provider._symbols = {"AAPL"}
        try:
            await provider.set_stream_symbols({"AAPL", "TSLA"})
        finally:
            provider._stream_task.cancel()


# ── entitlement handling ───────────────────────────────────────────────


class TestFeedWindow:
    def test_passes_a_real_time_feed_through(self):
        provider = make_provider(feed="iex")
        end = datetime.now(UTC)
        feed, clamped = provider._resolve_feed_window(end)
        assert feed == "iex" and clamped == end

    def test_maps_delayed_sip_onto_sip(self):
        # 'delayed_sip' is a streaming feed name; the bars endpoint rejects it.
        provider = make_provider(feed="delayed_sip")
        feed, _ = provider._resolve_feed_window(datetime.now(UTC))
        assert feed == "sip"

    def test_clamps_the_window_for_a_delayed_entitlement(self):
        provider = make_provider(feed="delayed_sip")
        now = datetime.now(UTC)
        _, clamped = provider._resolve_feed_window(now)
        assert clamped <= now - DELAYED_WINDOW + timedelta(seconds=1)

    def test_leaves_an_already_old_window_alone(self):
        provider = make_provider(feed="delayed_sip")
        old = datetime.now(UTC) - timedelta(days=2)
        _, clamped = provider._resolve_feed_window(old)
        assert clamped == old

    def test_reports_the_delay(self):
        assert make_provider(feed="delayed_sip").is_delayed is True
        assert make_provider(feed="iex").is_delayed is False


# ── the 10-second tape walk ────────────────────────────────────────────


class PagingTape:
    """A trades endpoint that pages forever, counting the requests."""

    def __init__(self, per_page: int = 3):
        self.requests: list[httpx.Request] = []
        self._per_page = per_page

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        page = len(self.requests)
        # Each page is older than the last, walking backwards like the real
        # newest-first sort.
        base = datetime(2024, 3, 5, 15, 0, tzinfo=UTC) - timedelta(minutes=page)
        return httpx.Response(
            200,
            json={
                "trades": {
                    "RUN": [
                        {
                            "t": (base + timedelta(seconds=10 * i)).strftime(
                                "%Y-%m-%dT%H:%M:%S.%fZ"
                            ),
                            "p": 4.0 + i,
                            "s": 100,
                        }
                        for i in range(self._per_page)
                    ]
                },
                "next_page_token": f"page-{page}",
            },
        )


async def provider_on(tape: PagingTape, **overrides) -> AlpacaProvider:
    provider = make_provider(feed="iex", **overrides)
    await provider.start()
    provider._client = httpx.AsyncClient(
        base_url="https://data.alpaca.markets", transport=httpx.MockTransport(tape)
    )
    return provider


WINDOW = (
    datetime(2024, 3, 4, 9, 0, tzinfo=UTC),
    datetime(2024, 3, 5, 3, 0, tzinfo=UTC),
)


class TestTapeWalkPaging:
    async def test_the_prior_session_walk_uses_its_own_smaller_cap(self):
        """Off-screen background history is not worth forty pages of tape."""
        tape = PagingTape()
        provider = await provider_on(tape, max_trade_pages=40, max_prior_session_pages=3)

        await provider.fetch_prior_tensec("RUN", *WINDOW)

        assert len(tape.requests) == 3

    async def test_the_on_screen_walk_still_uses_the_full_cap(self):
        tape = PagingTape()
        provider = await provider_on(tape, max_trade_pages=5, max_prior_session_pages=2)

        await provider.fetch_bars("RUN", Timeframe.S10, *WINDOW)

        assert len(tape.requests) == 5

    async def test_truncation_drops_the_bar_whose_open_is_missing(self):
        """The walk runs newest-first, so the oldest bar it reaches is the
        one whose opening trades are still a page away."""
        tape = PagingTape(per_page=2)
        provider = await provider_on(tape, max_prior_session_pages=2)

        bars = await provider.fetch_prior_tensec("RUN", *WINDOW)

        # Four trades, ten seconds apart, over two pages: four 10s buckets,
        # of which the earliest is dropped as incomplete.
        assert len(bars) == 3

    async def test_an_inverted_window_asks_for_nothing(self):
        """The router hands over an empty range whenever IBKR's own window
        already reaches past the previous session's open."""
        tape = PagingTape()
        provider = await provider_on(tape)

        moment = datetime(2024, 3, 5, 3, 0, tzinfo=UTC)
        assert await provider.fetch_prior_tensec("RUN", moment, moment) == []
        assert tape.requests == []


class TestAvailability:
    def test_needs_both_credentials(self):
        assert AlpacaProvider(AlpacaSettings(key_id="k")).is_available is False
        assert AlpacaProvider(AlpacaSettings(secret_key="s")).is_available is False
        assert make_provider().is_available is True

    async def test_fetching_before_start_is_an_error(self):
        provider = make_provider()
        with pytest.raises(ProviderError, match="not started"):
            await provider.fetch_bars(
                "AAPL", Timeframe.M1, datetime.now(UTC) - timedelta(days=1), datetime.now(UTC)
            )

    async def test_stop_is_safe_before_start(self):
        await make_provider().stop()

    async def test_start_without_credentials_does_nothing(self):
        provider = AlpacaProvider(AlpacaSettings())
        await provider.start()
        assert provider._client is None
