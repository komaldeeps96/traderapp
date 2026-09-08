"""Integration fixtures.

These tests run the real application — real container, real routing, real
WebSocket handler — with only two things stubbed: Alpaca's HTTP endpoint and
its streaming socket. Nothing test-shaped is injected into app code.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.core.clock import UTC
from app.core.settings import (
    CONFIG_DIR,
    AlpacaSettings,
    EdgarSettings,
    IBKRSettings,
    NewsAISettings,
    RegimeSettings,
    ScannerSettings,
    Settings,
    SetupAISettings,
    TradingSettings,
)
from app.main import create_app
from app.providers.alpaca import AlpacaProvider
from tests.conftest import daily_bars_for, minute_bars_for, trades_for

ALPACA_HOST = "https://data.alpaca.markets"


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Alpaca-only: the configuration a user without TWS running would have.

    The TradingView screener and EDGAR are off so no test ever leaves the
    machine; ``edgar_client`` turns EDGAR back on against a stub transport.

    ``news_stream`` is off for the same reason and needs saying out loud: it
    is a *websocket*, so respx does not intercept it and a live one would dial
    Alpaca for real from a unit run. The REST news path is stubbed instead.

    ``trading`` is off, and is written here rather than left to the default
    for the same reason: it is a raw socket to TWS on this machine, respx
    cannot see it, and the thing on the other end of it places real orders
    against a real account. A default is a thing that can be changed by
    someone who does not read this file. See docs/order-entry.md.

    ``news_ai`` and ``setup_ai`` are off for the third variant of the same
    reason: both spawn a ``claude`` process that reaches Anthropic, which
    respx cannot see either. They are tested against a fake binary instead.
    """
    return Settings(
        alpaca=AlpacaSettings(
            key_id="test-key",
            secret_key="test-secret",
            feed="iex",
            news_stream=False,
        ),
        ibkr=IBKRSettings(enabled=False),
        scanner=ScannerSettings(enabled=False),
        regime=RegimeSettings(enabled=False),
        edgar=EdgarSettings(enabled=False),
        trading=TradingSettings(enabled=False),
        news_ai=NewsAISettings(enabled=False),
        setup_ai=SetupAISettings(enabled=False),
        state_file=tmp_path / "state.yaml",
        indicators_file=CONFIG_DIR / "indicators.yaml",
        log_level="WARNING",
    )


@pytest.fixture
def bars_endpoint():
    """Serve Alpaca-shaped bars, choosing the series from the timeframe asked for."""
    now = datetime.now(UTC).replace(second=0, microsecond=0)

    def respond(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        symbol = params.get("symbols", "AAPL")
        timeframe = params.get("timeframe", "1Min")

        if timeframe == "1Day":
            payload = daily_bars_for(symbol, now, 260)
        else:
            payload = minute_bars_for(symbol, now - timedelta(minutes=400), 400)
        return httpx.Response(200, json=payload)

    return respond


@pytest.fixture
def trades_endpoint():
    """Serve a short synthetic tape so the 10s history path is exercised."""
    now = datetime.now(UTC).replace(second=0, microsecond=0)

    def respond(request: httpx.Request) -> httpx.Response:
        symbol = request.url.params.get("symbols", "AAPL")
        return httpx.Response(
            200, json=trades_for(symbol, now - timedelta(minutes=10), 300)
        )

    return respond


@pytest.fixture
def news_endpoint():
    """Serve Alpaca-shaped Benzinga news.

    Two rows, deliberately unalike: a company press release naming one symbol,
    and a movers roundup naming twelve. The panel has to tell them apart.
    """

    def respond(request: httpx.Request) -> httpx.Response:
        symbol = request.url.params.get("symbols", "AAPL")
        return httpx.Response(
            200,
            json={
                "news": [
                    {
                        "id": 61523000,
                        "headline": f"{symbol} Announces FDA Clearance",
                        "created_at": "2026-08-31T14:14:47Z",
                        "source": "benzinga",
                        "url": f"https://www.benzinga.com/news/61523000/{symbol.lower()}",
                        "symbols": [symbol],
                        "content": "<p>The company said the clearance covers…</p>",
                    },
                    {
                        "id": 61518626,
                        "headline": "12 Health Care Stocks Moving In Monday's Pre-Market",
                        "created_at": "2026-08-31T12:06:15Z",
                        "source": "benzinga",
                        "url": "https://www.benzinga.com/movers/61518626/",
                        "symbols": [symbol, *[f"X{n:02d}" for n in range(11)]],
                        "content": "<h3>Gainers</h3><ul><li>…</li></ul>",
                    },
                ]
            },
        )

    return respond


@pytest.fixture
def alpaca_api(bars_endpoint, trades_endpoint, news_endpoint):
    with respx.mock(base_url=ALPACA_HOST, assert_all_called=False) as mock:
        mock.get("/v2/stocks/bars").mock(side_effect=bars_endpoint)
        mock.get("/v2/stocks/trades").mock(side_effect=trades_endpoint)
        mock.get("/v1beta1/news").mock(side_effect=news_endpoint)
        yield mock


@pytest.fixture(autouse=True)
def no_real_stream(monkeypatch):
    """Keep the provider's socket loop from dialling out during tests."""

    async def idle(self):
        await asyncio.sleep(3600)

    monkeypatch.setattr(AlpacaProvider, "_stream_loop", idle)


@pytest.fixture
def client(settings, alpaca_api) -> TestClient:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def edgar_client(settings, alpaca_api) -> TestClient:
    """A client whose EDGAR provider answers from a stub rather than SEC.

    The container builds its own provider, so the transport is swapped on the
    built one — the alternative is threading a test-only argument through
    ``AppContainer``, which the codebase deliberately does not do.
    """
    from app.providers.edgar import EdgarProvider
    from app.services.container import get_container
    from tests.integration.edgar_stub import edgar_transport

    settings = settings.model_copy(update={"edgar": EdgarSettings(enabled=True)})
    app = create_app(settings)
    with TestClient(app) as test_client:
        container = get_container()
        container.edgar = EdgarProvider(
            transport=edgar_transport(), user_agent="traderapp/1.0 (test@example.com)"
        )
        container.symbol_info._edgar = container.edgar
        container.symbol_info._dilution_cache.clear()
        yield test_client


@pytest.fixture
def stub_watchlist_quotes(client):
    """Answer the watchlist's screener query from a fixture.

    The quote fetch is the one part of the panel that leaves the machine, and
    nothing in these tests may. The list itself — order, duplicates, what
    survives a restart — is what is being exercised here.
    """
    from app.services.container import get_container
    from app.services.watchlist import COLUMNS

    def make(symbol: str) -> list:
        values = {
            "name": symbol,
            "description": f"{symbol} Inc.",
            "close": 10.0,
            "change": 1.5,
            "volume": 1_000_000.0,
            "relative_volume_10d_calc": 1.2,
            "market_cap_basic": 400_000_000.0,
            "premarket_change": 0.0,
            "earnings_release_next_date": None,
        }
        return [values[name] for name in COLUMNS]

    known = {"AAPL", "TSLA", "NVDA", "ZM"}

    async def fetch(_query):
        symbols = get_container().watchlist.symbols()
        return [make(symbol) for symbol in symbols if symbol in known]

    watchlist = get_container().watchlist
    watchlist._fetch = fetch
    # These settings run with the screener off so nothing dials out; the stub
    # *is* the network here, so quotes are back on for the tests that use it.
    watchlist._quotes_enabled = True
    return watchlist


@pytest.fixture
def ws(client):
    """A connected client that has consumed the eight opening frames.

    The count is deliberately exact rather than "drain whatever arrives": a
    frame added to the handshake and not added here leaves a stale one at the
    head of the queue, where the next ``receive_until`` finds it and asserts
    against the wrong message. Keep this in step with ``api/ws.py``.
    """
    with client.websocket_connect("/ws") as socket:
        socket.receive_json()  # status
        for _ in range(4):
            socket.receive_json()  # scanner, one per market-cap tier
        socket.receive_json()  # regime
        socket.receive_json()  # api budget
        socket.receive_json()  # trading
        yield socket


def receive_until(socket, message_type: str, limit: int = 12, **fields) -> dict:
    """Read frames until ``message_type`` arrives, matching ``fields`` too.

    Matching on symbol/timeframe mirrors what the real client does: a
    background backfill can push a fresh snapshot for the *previous* chart
    right after a switch, and it must be skipped, not asserted against.
    """
    for _ in range(limit):
        message = socket.receive_json()
        if message.get("type") == message_type and all(
            message.get(key) == value for key, value in fields.items()
        ):
            return message
    raise AssertionError(f"no matching {message_type!r} message within {limit} frames")
