"""A slow client's backlog: what is shed, what never is, and when the client is
cut loose to resync."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services.connection import MAX_BACKLOG, QUEUE_SIZE, TRY_AGAIN_LATER, ClientConnection


class RecordingSocket:
    def __init__(self, *, expect: int = 0) -> None:
        self.sent: list[dict] = []
        self.closed_with: int | None = None
        self._expect = expect
        self.done = asyncio.Event()

    async def send_text(self, payload: str) -> None:
        self.sent.append(json.loads(payload))
        if len(self.sent) >= self._expect:
            self.done.set()

    async def close(self, code: int) -> None:
        self.closed_with = code


def backlog_types(connection: ClientConnection) -> list[str]:
    return [json.loads(payload)["type"] for _, payload in connection._backlog]


def test_a_full_backlog_sheds_the_oldest_superseded_update() -> None:
    connection = ClientConnection(RecordingSocket())
    connection.send({"type": "order", "n": -1})
    for n in range(QUEUE_SIZE):
        connection.send({"type": "bar", "n": n})

    assert len(connection._backlog) == QUEUE_SIZE
    assert backlog_types(connection)[0] == "order"
    bars = [json.loads(payload)["n"] for _, payload in connection._backlog][1:]
    assert bars[0] == 1  # bar 0 went, the order before it did not


@pytest.mark.parametrize("kind", ["snapshot", "order", "trading", "error", "news", "watchlist"])
def test_what_nothing_supersedes_is_never_shed(kind: str) -> None:
    """A snapshot or an order acknowledgement dropped under load is simply gone."""
    connection = ClientConnection(RecordingSocket())
    for n in range(QUEUE_SIZE + 5):
        connection.send({"type": kind, "n": n})
    assert len(connection._backlog) == QUEUE_SIZE + 5


async def test_a_client_past_the_hard_limit_is_closed_so_it_resyncs() -> None:
    socket = RecordingSocket()
    connection = ClientConnection(socket)
    for n in range(MAX_BACKLOG + 1):
        connection.send({"type": "order", "n": n})

    await connection.start()
    await asyncio.wait_for(connection._writer, timeout=5)
    assert socket.closed_with == TRY_AGAIN_LATER
    assert socket.sent == []


async def test_messages_go_out_in_the_order_they_were_sent() -> None:
    socket = RecordingSocket(expect=3)
    connection = ClientConnection(socket)
    await connection.start()
    for n in range(3):
        connection.send({"type": "bar", "n": n})
    await asyncio.wait_for(socket.done.wait(), timeout=5)
    await connection.close()
    assert [message["n"] for message in socket.sent] == [0, 1, 2]


@pytest.mark.parametrize(
    ("host", "local"),
    [("127.0.0.1", True), ("::1", True), ("192.168.1.20", False), ("testclient", False)],
)
def test_where_the_socket_came_from_decides_whether_it_is_local(host: str, local: bool) -> None:
    socket = SimpleNamespace(client=SimpleNamespace(host=host))
    assert ClientConnection(socket).is_local is local


def test_a_socket_with_no_peer_is_not_local() -> None:
    assert ClientConnection(SimpleNamespace(client=None)).is_local is False


def test_a_non_finite_number_goes_out_as_null() -> None:
    """JSON has no NaN, and the browser's parser drops the whole frame for one."""
    connection = ClientConnection(RecordingSocket())
    connection.send({"type": "info", "float_shares": float("nan"), "rows": [1.5, float("inf")]})
    _, payload = connection._backlog[-1]
    assert "NaN" not in payload
    assert json.loads(payload) == {"type": "info", "float_shares": None, "rows": [1.5, None]}
