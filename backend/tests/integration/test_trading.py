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

import contextlib

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


LOOPBACK = ("127.0.0.1", 50000)
ON_THE_WIFI = ("192.168.1.20", 50000)


@pytest.fixture
def arm(tmp_path, alpaca_api):
    """A client on an app with trading switched on, pointed at port 1.

    Port 1 is chosen because nothing can be listening on it, so nothing here can
    reach TWS. ``peer`` is the address the socket appears to come from.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    @contextlib.contextmanager
    def build(peer=LOOPBACK, **trading):
        settings = Settings(
            alpaca=AlpacaSettings(
                key_id="test-key", secret_key="test-secret", feed="iex", news_stream=False
            ),
            ibkr=IBKRSettings(enabled=False),
            scanner=ScannerSettings(enabled=False),
            regime=RegimeSettings(enabled=False),
            edgar=EdgarSettings(enabled=False),
            trading=TradingSettings(
                enabled=True,
                port=1,
                connect_timeout_seconds=0.2,
                max_reconnect_delay_seconds=0.2,
                **trading,
            ),
            state_file=tmp_path / "state.yaml",
            indicators_file=CONFIG_DIR / "indicators.yaml",
            log_level="WARNING",
        )
        with TestClient(create_app(settings), client=peer) as client:
            yield client

    return build


def drain_opening_frames(socket) -> None:
    """The eight frames every connection opens with; see ``ws`` in conftest."""
    for _ in range(8):
        socket.receive_json()


def frames_until(socket, message_type: str, limit: int = 20) -> list[dict]:
    """Every frame up to and including the first ``message_type``."""
    seen = []
    for _ in range(limit):
        seen.append(socket.receive_json())
        if seen[-1]["type"] == message_type:
            return seen
    raise AssertionError(f"no {message_type!r} within {limit} frames: {seen}")


class TestArmedButUnreachable:
    """Trading switched on, pointed at a port with nothing behind it.

    This is the shape of a real misconfiguration — TWS closed, or the wrong
    socket — and it must degrade to a refusal rather than a hang or a crash.
    """

    @pytest.fixture
    def armed_client(self, arm):
        with arm() as client:
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
            assert error["action"] == "trade.buy"
            assert "not connected" in error["message"]


class TestOnlyThisMachinePlacesOrders:
    """The terminal is served to the LAN so a phone can watch it. Anything on
    the WiFi can open the socket, so buys and sells are refused unless they come
    from loopback or ``trading.allow_remote`` says otherwise."""

    def test_a_buy_from_another_machine_is_refused(self, arm):
        with arm(peer=ON_THE_WIFI) as client, client.websocket_connect("/ws") as socket:
            drain_opening_frames(socket)
            socket.send_json({"action": "trade.buy", "symbol": "AAPL", "dollars": 25})
            error = receive_until(socket, "error", limit=20)
            assert error["code"] == "trade"
            assert "only from this machine" in error["message"]

    def test_a_sell_from_another_machine_is_refused(self, arm):
        with arm(peer=ON_THE_WIFI) as client, client.websocket_connect("/ws") as socket:
            drain_opening_frames(socket)
            socket.send_json({"action": "trade.sell", "symbol": "AAPL", "fraction": 1.0})
            assert "only from this machine" in receive_until(socket, "error", limit=20)["message"]

    def test_the_refusal_is_not_broadcast_as_the_strips_note(self, arm):
        """It is about the asking window, not the account: every other window's
        strip must not start saying orders are refused."""
        with arm(peer=ON_THE_WIFI) as client, client.websocket_connect("/ws") as socket:
            drain_opening_frames(socket)
            socket.send_json({"action": "trade.buy", "symbol": "AAPL", "dollars": 25})
            receive_until(socket, "error", limit=20)
            socket.send_json({"action": "trade.cancel_all"})
            state = receive_until(socket, "trading", limit=20)["state"]
            assert state["note"] is None or "only from this machine" not in state["note"]

    def test_cancel_all_is_accepted_from_another_machine(self, arm):
        """Cancelling reduces risk, and a phone is where it might be pressed."""
        with arm(peer=ON_THE_WIFI) as client, client.websocket_connect("/ws") as socket:
            drain_opening_frames(socket)
            socket.send_json({"action": "trade.cancel_all"})
            frames = frames_until(socket, "trading")
            assert not [frame for frame in frames if frame["type"] == "error"]

    def test_allow_remote_lets_another_machine_through_to_the_other_guards(self, arm):
        with (
            arm(peer=ON_THE_WIFI, allow_remote=True) as client,
            client.websocket_connect("/ws") as socket,
        ):
            drain_opening_frames(socket)
            socket.send_json({"action": "trade.buy", "symbol": "AAPL", "dollars": 25})
            assert "not connected" in receive_until(socket, "error", limit=20)["message"]

    def test_with_trading_off_the_refusal_says_so_first(self, client):
        """A disabled switch is the more fundamental answer, and says what to change."""
        with client.websocket_connect("/ws") as socket:
            drain_opening_frames(socket)
            socket.send_json({"action": "trade.buy", "symbol": "AAPL", "dollars": 25})
            assert "disabled" in receive_until(socket, "error")["message"]
