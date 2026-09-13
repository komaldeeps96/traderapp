"""What both Alpaca sockets share: frame decoding and the auth handshake."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.settings import AlpacaSettings
from app.providers import alpaca_socket
from app.providers.alpaca_socket import authenticate, decode
from app.providers.base import ProviderError

SETTINGS = AlpacaSettings(key_id="key", secret_key="secret")


class FakeSocket:
    """A websocket whose script the test writes."""

    def __init__(self, inbound: list[object] | None = None):
        self.sent: list[dict] = []
        self._inbound = list(inbound or [])

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def recv(self) -> str:
        if not self._inbound:
            await asyncio.sleep(3600)
        message = self._inbound.pop(0)
        return message if isinstance(message, str) else json.dumps(message)


class TestDecode:
    def test_unwraps_the_array_alpaca_sends(self):
        assert decode('[{"T":"t"},{"T":"b"}]') == [{"T": "t"}, {"T": "b"}]

    def test_accepts_a_bare_object(self):
        assert decode('{"T":"success"}') == [{"T": "success"}]

    def test_accepts_bytes(self):
        assert decode(b'[{"T":"t"}]') == [{"T": "t"}]

    def test_survives_malformed_json(self):
        """A bad frame must not break the socket the next one arrives on."""
        assert decode("{not json") == []

    def test_drops_non_object_entries(self):
        assert decode('[{"T":"t"}, 5, null, "x"]') == [{"T": "t"}]

    def test_handles_an_empty_batch(self):
        assert decode("[]") == []

    @pytest.mark.parametrize("raw", ["5", '"x"', "null", "true"])
    def test_a_bare_scalar_is_no_frame(self, raw):
        assert decode(raw) == []


class TestAuthenticate:
    async def test_sends_the_credentials(self):
        socket = FakeSocket([[{"T": "success", "msg": "authenticated"}]])

        await authenticate(socket, SETTINGS)

        assert socket.sent[0] == {"action": "auth", "key": "key", "secret": "secret"}

    async def test_accepts_a_greeting_before_the_answer(self):
        socket = FakeSocket(
            [[{"T": "success", "msg": "connected"}], [{"T": "success", "msg": "authenticated"}]]
        )
        await authenticate(socket, SETTINGS)

    async def test_raises_on_rejection(self):
        socket = FakeSocket([[{"T": "error", "code": 402, "msg": "auth failed"}]])
        with pytest.raises(ProviderError, match="auth failed"):
            await authenticate(socket, SETTINGS)

    async def test_reports_the_error_code(self):
        socket = FakeSocket([[{"T": "error", "code": 406, "msg": "connection limit"}]])
        with pytest.raises(ProviderError, match="406"):
            await authenticate(socket, SETTINGS)

    async def test_gives_up_on_a_silent_server(self, monkeypatch):
        monkeypatch.setattr(alpaca_socket, "AUTH_TIMEOUT_SECONDS", 0.05)
        with pytest.raises(TimeoutError):
            await authenticate(FakeSocket(), SETTINGS)
