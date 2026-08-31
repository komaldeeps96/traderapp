"""The live headline socket.

Real time, and measured rather than assumed: four headlines arrived on this
socket about 1.9 seconds *ahead* of their own ``created_at`` stamps. Alpaca's
``delayed_sip`` entitlement governs the price tape and nothing else.

What earns a test here is the socket's behaviour, not its content — that a
non-news frame is not mistaken for a headline, that a handler blowing up does
not take the connection down with it, and that the thing can be switched off,
because it is a websocket and no test may leave the machine.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.settings import AlpacaSettings
from app.providers.alpaca_news import AlpacaNewsStream, _decode


def settings(**overrides) -> AlpacaSettings:
    base = {"key_id": "k", "secret_key": "s", "news_stream": True}
    base.update(overrides)
    return AlpacaSettings(**base)


class TestDecode:
    def test_reads_the_array_the_socket_sends(self):
        assert _decode('[{"T":"n","id":1}]') == [{"T": "n", "id": 1}]

    def test_reads_a_bare_object_too(self):
        assert _decode('{"T":"success"}') == [{"T": "success"}]

    def test_unparseable_bytes_are_not_an_exception(self):
        """A bad frame must not break the socket the next one arrives on."""
        assert _decode("not json") == []

    def test_non_objects_in_the_array_are_dropped(self):
        assert _decode('[{"T":"n"}, 7, null]') == [{"T": "n"}]


class TestFrames:
    @staticmethod
    async def collect(raw: str) -> list[dict]:
        stream = AlpacaNewsStream(settings())
        seen: list[dict] = []

        async def handler(entry: dict) -> None:
            seen.append(entry)

        stream.on_headline(handler)
        await stream._handle(raw)
        return seen

    async def test_a_news_frame_reaches_the_handler(self):
        seen = await self.collect(json.dumps([{"T": "n", "id": 1, "headline": "Hi"}]))
        assert len(seen) == 1

    @pytest.mark.parametrize("kind", ["success", "subscription", "error"])
    async def test_everything_that_is_not_news_is_ignored(self, kind):
        """The socket carries greetings and subscription acks on the same wire."""
        assert await self.collect(json.dumps([{"T": kind, "msg": "x"}])) == []

    async def test_several_headlines_in_one_frame_all_arrive(self):
        seen = await self.collect(json.dumps([{"T": "n", "id": 1}, {"T": "n", "id": 2}]))
        assert [entry["id"] for entry in seen] == [1, 2]

    async def test_a_failing_handler_does_not_stop_the_others(self):
        """A reconnect would cost every headline published in the meantime."""
        stream = AlpacaNewsStream(settings())
        seen: list[dict] = []

        async def broken(entry: dict) -> None:
            raise RuntimeError("handler is having a day")

        async def working(entry: dict) -> None:
            seen.append(entry)

        stream.on_headline(broken)
        stream.on_headline(working)
        await stream._handle(json.dumps([{"T": "n", "id": 1}]))
        assert len(seen) == 1


class TestSwitchedOff:
    async def test_it_does_not_start_when_disabled(self):
        """No test may leave the machine, and respx does not catch a socket."""
        stream = AlpacaNewsStream(settings(news_stream=False))
        await stream.start()
        assert stream._task is None
        assert stream.connected is False

    async def test_it_does_not_start_without_credentials(self):
        stream = AlpacaNewsStream(settings(key_id="", secret_key=""))
        await stream.start()
        assert stream._task is None

    async def test_stopping_one_that_never_started_is_not_an_error(self):
        await AlpacaNewsStream(settings(news_stream=False)).stop()


class TestAuthentication:
    class FakeSocket:
        def __init__(self, replies):
            self.replies = list(replies)
            self.sent: list[dict] = []

        async def send(self, raw):
            self.sent.append(json.loads(raw))

        async def recv(self):
            if not self.replies:
                await asyncio.sleep(3600)
            return self.replies.pop(0)

    async def test_it_sends_the_credentials_and_accepts_the_ack(self):
        socket = self.FakeSocket([json.dumps([{"T": "success", "msg": "authenticated"}])])
        await AlpacaNewsStream(settings())._authenticate(socket)
        assert socket.sent[0]["action"] == "auth"
        assert socket.sent[0]["key"] == "k"

    async def test_the_greeting_before_the_ack_is_not_a_failure(self):
        """The server greets first and answers the auth second."""
        socket = self.FakeSocket(
            [
                json.dumps([{"T": "success", "msg": "connected"}]),
                json.dumps([{"T": "success", "msg": "authenticated"}]),
            ]
        )
        await AlpacaNewsStream(settings())._authenticate(socket)

    async def test_a_refusal_is_raised_rather_than_retried_blindly(self):
        socket = self.FakeSocket([json.dumps([{"T": "error", "msg": "auth failed", "code": 402}])])
        with pytest.raises(RuntimeError, match="auth failed"):
            await AlpacaNewsStream(settings())._authenticate(socket)
