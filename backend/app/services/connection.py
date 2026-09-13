"""One connected browser.

Each connection writes through its own backlog and writer task, so a client on a
slow link cannot stall the broadcast loop or any other client. A full backlog
sheds the oldest message a newer one of its kind supersedes; a client that
falls past ``MAX_BACKLOG`` anyway is closed, and its reconnect resends state.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
from collections import deque
from itertools import count

from ..domain.timeframes import Timeframe

logger = logging.getLogger(__name__)

_ids = count(1)
QUEUE_SIZE = 64
MAX_BACKLOG = 1024
# Superseded by the next message of the same kind. A snapshot, an order, the
# trading state, a headline or an error is not, and is never shed.
SUPERSEDED = frozenset({"bar", "quote", "info", "api", "scanner", "regime"})
# RFC 6455 "try again later".
TRY_AGAIN_LATER = 1013
LOOPBACK = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"})


class ClientConnection:
    def __init__(self, websocket):
        self.id = next(_ids)
        self.websocket = websocket
        client = getattr(websocket, "client", None)
        self.is_local = client is not None and client.host in LOOPBACK
        self.symbol: str | None = None
        self.timeframe: Timeframe | None = None
        # Secondary timeframes on the same symbol — the mini charts. They are
        # deliberately not part of `subscription`: that one identifies the
        # chart the client is *on*, which is what the session remembers and
        # what a slow load is checked against.
        self.extra_timeframes: tuple[Timeframe, ...] = ()
        self._backlog: deque[tuple[bool, str]] = deque()
        self._wake = asyncio.Event()
        self._overflowed = False
        self._writer: asyncio.Task | None = None
        self._closed = False

    @property
    def subscription(self) -> tuple[str, Timeframe] | None:
        if self.symbol and self.timeframe:
            return (self.symbol, self.timeframe)
        return None

    @property
    def subscriptions(self) -> set[tuple[str, Timeframe]]:
        """Every chart this client is being fed: the primary plus the extras."""
        primary = self.subscription
        if primary is None:
            return set()
        return {primary} | {(primary[0], timeframe) for timeframe in self.extra_timeframes}

    def clear_subscription(self) -> None:
        self.symbol = None
        self.timeframe = None
        self.extra_timeframes = ()

    async def start(self) -> None:
        self._writer = asyncio.create_task(self._run_writer())

    async def close(self) -> None:
        self._closed = True
        if self._writer:
            self._writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._writer
            self._writer = None

    def send(self, message: dict) -> None:
        """Queue a message. Never blocks and never raises."""
        if self._closed:
            return
        payload = _encode(message)
        if len(self._backlog) >= QUEUE_SIZE:
            self._shed()
        if len(self._backlog) >= MAX_BACKLOG:
            self._overflowed = True
        else:
            self._backlog.append((message.get("type") in SUPERSEDED, payload))
        self._wake.set()

    def _shed(self) -> None:
        for index, (superseded, _) in enumerate(self._backlog):
            if superseded:
                del self._backlog[index]
                logger.debug("client %s is slow; dropped an update", self.id)
                return

    async def _run_writer(self) -> None:
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                if self._overflowed:
                    logger.warning("client %s fell %d messages behind; closing", self.id, MAX_BACKLOG)
                    self._closed = True
                    await self.websocket.close(code=TRY_AGAIN_LATER)
                    return
                while self._backlog:
                    _, payload = self._backlog.popleft()
                    await self.websocket.send_text(payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The receive loop owns disconnect handling; just stop writing.
            logger.debug("client %s write failed; writer stopping", self.id)
            self._closed = True


_reported_non_finite: set[object] = set()


def _encode(message: dict) -> str:
    """The message as JSON. JSON has no NaN, and the browser's parser rejects a
    whole frame for one, so a non-finite number goes out as null."""
    try:
        return json.dumps(message, separators=(",", ":"), default=float, allow_nan=False)
    except ValueError:
        kind = message.get("type")
        if kind not in _reported_non_finite:
            _reported_non_finite.add(kind)
            logger.warning("a %r message carried a non-finite number; sent as null", kind)
        return json.dumps(_finite(message), separators=(",", ":"), default=float)


def _finite(value: object) -> object:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    return value
