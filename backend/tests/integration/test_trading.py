"""Order entry, end to end over the real WebSocket.

The theme of this file is that **nothing places an order**. The application
under test runs with ``trading.enabled=False``, which is the default and is
written out explicitly in the integration settings — so every path here ends
in a refusal, and that is the point. A suite that could reach TWS is a suite
that could spend money from a `pytest` run.

The one live claim is the opening frame: the strip has to learn that trading
is off, rather than rendering as a panel that silently does nothing.
"""

from __future__ import annotations

import pytest

from app.core.settings import (
    CONFIG_DIR,
    AlpacaSettings,
    EdgarSettings,
    IBKRSettings,
    RegimeSettings,
    ScannerSettings,
    Settings,
    TradingSettings,
)
from tests.integration.conftest import receive_until


class TestHandshake:
    def test_the_opening_frames_carry_the_trading_state(self, client):
        with client.websocket_connect("/ws") as socket:
            frame = receive_until(socket, "trading")
            assert frame["state"]["enabled"] is False
            assert frame["positions"] == []
            assert frame["orders"] == []

    def test_the_state_carries_the_button_configuration(self, client):
        """The panel draws whatever the settings define rather than three
        hard-coded amounts, so it has to arrive from here."""
        with client.websocket_connect("/ws") as socket:
            state = receive_until(socket, "trading")["state"]
            assert state["buy_dollars"] == [10.0, 25.0, 50.0]
            assert state["sell_fractions"] == [0.25, 0.5, 1.0]
            assert state["offset_cents"] == 5.0
            assert state["offset_bps"] == 15.0

    def test_the_state_says_which_account_kind_the_port_is(self, client):
        with client.websocket_connect("/ws") as socket:
            assert receive_until(socket, "trading")["state"]["paper"] is False


class TestRefusals:
    """With the switch off, every command is refused and says so."""

    @pytest.mark.parametrize(
        "command",
        [
            {"action": "trade.buy", "symbol": "AAPL", "dollars": 25},
            {"action": "trade.sell", "symbol": "AAPL", "fraction": 0.5},
            {"action": "trade.cancel_all"},
        ],
        ids=["buy", "sell", "cancel"],
    )
    def test_every_order_command_is_refused_while_trading_is_off(self, ws, command):
        ws.send_json(command)
        error = receive_until(ws, "error")
        assert error["code"] == "trade"
        assert "disabled" in error["message"]

    def test_a_refusal_does_not_close_the_socket(self, ws):
        """A rejected order must not cost the user their terminal — the same
        rule the rest of the protocol follows."""
        ws.send_json({"action": "trade.buy", "symbol": "AAPL", "dollars": 25})
        receive_until(ws, "error")
        ws.send_json({"action": "ping"})
        assert receive_until(ws, "pong")["type"] == "pong"

    def test_the_refusal_reaches_the_broadcast_state_too(self, ws):
        """Not only the asking connection: a second window has to see why the
        strip is unhappy, and the strip is drawn from the broadcast."""
        ws.send_json({"action": "trade.buy", "symbol": "AAPL", "dollars": 25})
        frame = receive_until(ws, "trading", limit=20)
        assert frame["state"]["note"] == "Trading is disabled."


class TestTheClientCannotSendAQuantity:
    """The architectural guarantee, enforced at the protocol layer.

    ``_Command`` forbids extra fields, so a hand-written client cannot smuggle
    a share count past the sizing that happens on the server.
    """

    def test_a_share_count_is_rejected_as_a_malformed_command(self, ws):
        ws.send_json({"action": "trade.buy", "symbol": "AAPL", "dollars": 25, "shares": 10_000})
        assert receive_until(ws, "error")["code"] == "bad_command"

    @pytest.mark.parametrize("fraction", [0, -0.5, 1.5, 100])
    def test_a_fraction_outside_the_long_only_range_is_rejected(self, ws, fraction):
        ws.send_json({"action": "trade.sell", "symbol": "AAPL", "fraction": fraction})
        assert receive_until(ws, "error")["code"] == "bad_command"

    @pytest.mark.parametrize("dollars", [0, -25])
    def test_a_non_positive_amount_is_rejected(self, ws, dollars):
        ws.send_json({"action": "trade.buy", "symbol": "AAPL", "dollars": dollars})
        assert receive_until(ws, "error")["code"] == "bad_command"


class TestArmedButUnreachable:
    """Trading switched on, pointed at a port with nothing behind it.

    This is the shape of a real misconfiguration — TWS closed, or the wrong
    socket — and it must degrade to a refusal rather than a hang or a crash.
    Port 1 is chosen because nothing can be listening on it.
    """

    @pytest.fixture
    def armed_client(self, tmp_path, alpaca_api):
        from fastapi.testclient import TestClient

        from app.main import create_app

        settings = Settings(
            alpaca=AlpacaSettings(
                key_id="test-key", secret_key="test-secret", feed="iex", news_stream=False
            ),
            ibkr=IBKRSettings(enabled=False),
            scanner=ScannerSettings(enabled=False),
            regime=RegimeSettings(enabled=False),
            edgar=EdgarSettings(enabled=False),
            trading=TradingSettings(
                enabled=True, port=1, connect_timeout_seconds=0.2, max_reconnect_delay_seconds=0.2
            ),
            state_file=tmp_path / "state.yaml",
            indicators_file=CONFIG_DIR / "indicators.yaml",
            log_level="WARNING",
        )
        with TestClient(create_app(settings)) as client:
            yield client

    def test_the_strip_reports_armed_but_disconnected(self, armed_client):
        with armed_client.websocket_connect("/ws") as socket:
            state = receive_until(socket, "trading")["state"]
            assert state["enabled"] is True
            assert state["connected"] is False

    def test_an_order_with_no_tws_is_refused_not_queued(self, armed_client):
        """An order that quietly waits for a reconnect is the worst outcome
        here: it would arrive minutes later, into a different market."""
        with armed_client.websocket_connect("/ws") as socket:
            socket.send_json({"action": "trade.buy", "symbol": "AAPL", "dollars": 25})
            error = receive_until(socket, "error", limit=20)
            assert error["code"] == "trade"
            assert "not connected" in error["message"]
