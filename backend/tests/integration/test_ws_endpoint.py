"""The socket's own rules: who may open it, and that one command cannot hold
up or take down the others.
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api.origin import origin_allowed
from app.core.settings import Settings
from app.services.container import get_container
from tests.integration.conftest import receive_until

# How long a stalled load is held before the test lets it go. Only a deadlock
# breaker: every assertion below is about the order frames arrive in.
RELEASE_AFTER_SECONDS = 2.0


class TestOrigin:
    """Browsers exempt WebSockets from CORS, so without a check any page open in
    the browser could drive the terminal — including its order buttons."""

    @pytest.mark.parametrize(
        "origin", ["https://evil.example", "http://localhost:9999", "null"]
    )
    def test_a_foreign_page_is_refused(self, client, origin):
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/ws", headers={"origin": origin}) as socket,
        ):
            socket.receive_json()

    @pytest.mark.parametrize(
        "origin",
        ["http://localhost:3000", "http://127.0.0.1:4173", "http://192.168.1.20:3000"],
        ids=["dev server", "preview", "a phone on the wifi"],
    )
    def test_the_terminals_own_pages_are_accepted(self, client, origin):
        with client.websocket_connect("/ws", headers={"origin": origin}) as socket:
            assert socket.receive_json()["type"] == "status"

    def test_the_api_serving_its_own_ui_is_same_origin(self, client):
        with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as socket:
            assert socket.receive_json()["type"] == "status"


class TestOriginRule:
    def test_no_origin_is_not_a_browser_and_is_let_through(self):
        assert origin_allowed(None, "localhost:8000", Settings(cors_origins=[]))

    def test_an_empty_regex_binds_the_terminal_to_the_listed_origins(self):
        settings = Settings(cors_origins=["http://localhost:3000"], cors_origin_regex="")
        assert origin_allowed("http://localhost:3000", "localhost:8000", settings)
        assert not origin_allowed("http://192.168.1.20:3000", "localhost:8000", settings)

    def test_a_lookalike_host_does_not_match_the_lan_pattern(self):
        assert not origin_allowed(
            "http://192.168.1.20.evil.example:3000", "localhost:8000", Settings()
        )


def stall_subscribes(monkeypatch) -> threading.Event:
    """Make every subscribe wait until the returned gate opens."""
    gate = threading.Event()
    threading.Timer(RELEASE_AFTER_SECONDS, gate.set).start()

    async def slow(connection, symbol, timeframe, extra_timeframes=()):
        connection.symbol, connection.timeframe = symbol, timeframe
        # A thread's Event, because the test opens it from outside the app's loop.
        await asyncio.to_thread(gate.wait)
        return []

    monkeypatch.setattr(get_container().hub, "subscribe", slow)
    return gate


class TestALoadDoesNotHoldUpOtherCommands:
    """A history load can take seconds. A sell or a cancel sent meanwhile has
    to be read at once, not queued behind the chart."""

    def test_a_ping_is_answered_before_a_slow_load_finishes(self, ws, monkeypatch):
        gate = stall_subscribes(monkeypatch)
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        ws.send_json({"action": "ping"})
        first = ws.receive_json()
        gate.set()
        assert first["type"] == "pong"

    def test_an_order_is_answered_before_a_slow_load_finishes(self, ws, monkeypatch):
        gate = stall_subscribes(monkeypatch)
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        ws.send_json({"action": "trade.buy", "symbol": "AAPL", "dollars": 25})
        first = ws.receive_json()
        gate.set()
        assert (first["type"], first["code"]) == ("error", "trade")

    def test_a_newer_subscribe_supersedes_one_still_loading(self, ws, monkeypatch):
        """Only the chart the client is on now is answered."""
        gate = stall_subscribes(monkeypatch)
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        monkeypatch.undo()
        ws.send_json({"action": "subscribe", "symbol": "TSLA"})
        snapshot = receive_until(ws, "snapshot")
        gate.set()
        assert snapshot["symbol"] == "TSLA"


class TestAFailingCommand:
    def test_is_reported_and_the_socket_stays_open(self, ws, monkeypatch):
        async def broken(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(get_container().state, "save_indicators", broken)
        ws.send_json({"action": "indicators.visibility", "timeframe": "10s", "visible": {}})
        error = receive_until(ws, "error")
        assert (error["code"], error["action"]) == ("server", "indicators.visibility")

        ws.send_json({"action": "ping"})
        assert receive_until(ws, "pong")["type"] == "pong"

    def test_a_malformed_subscribe_names_the_command(self, ws):
        """So the client can put it on the chart rather than in a notice."""
        ws.send_json({"action": "subscribe", "symbol": "not a symbol!"})
        error = receive_until(ws, "error")
        assert (error["code"], error["action"]) == ("bad_command", "subscribe")
