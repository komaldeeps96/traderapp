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
    RegimeSettings,
    ScannerSettings,
    Settings,
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
    """
    return Settings(
        alpaca=AlpacaSettings(key_id="test-key", secret_key="test-secret", feed="iex"),
        ibkr=IBKRSettings(enabled=False),
        scanner=ScannerSettings(enabled=False),
        regime=RegimeSettings(enabled=False),
        edgar=EdgarSettings(enabled=False),
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
def alpaca_api(bars_endpoint, trades_endpoint):
    with respx.mock(base_url=ALPACA_HOST, assert_all_called=False) as mock:
        mock.get("/v2/stocks/bars").mock(side_effect=bars_endpoint)
        mock.get("/v2/stocks/trades").mock(side_effect=trades_endpoint)
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
def ws(client):
    """A connected client that has consumed the seven opening frames."""
    with client.websocket_connect("/ws") as socket:
        socket.receive_json()  # status
        for _ in range(4):
            socket.receive_json()  # scanner, one per market-cap tier
        socket.receive_json()  # regime
        socket.receive_json()  # api budget
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
