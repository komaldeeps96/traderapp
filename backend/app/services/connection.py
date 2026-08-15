"""One connected browser.

Each connection writes through its own bounded queue and writer task. A client
on a slow link therefore cannot stall the broadcast loop or any other client —
its queue fills and its oldest pending update is dropped, which for a stream of
"here is the newest bar" messages is exactly the right thing to lose.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from itertools import count

from ..domain.timeframes import Timeframe

logger = logging.getLogger(__name__)

_ids = count(1)
QUEUE_SIZE = 64


class ClientConnection:
    def __init__(self, websocket):
        self.id = next(_ids)
        self.websocket = websocket
        self.symbol: str | None = None
        self.timeframe: Timeframe | None = None
        # Secondary timeframes on the same symbol — the mini charts. They are
        # deliberately not part of `subscription`: that one identifies the
        # chart the client is *on*, which is what the session remembers and
        # what a slow load is checked against.
        self.extra_timeframes: tuple[Timeframe, ...] = ()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)
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
        payload = json.dumps(message, separators=(",", ":"), default=float)
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(payload)
            logger.debug("client %s is slow; dropped an update", self.id)

    async def _run_writer(self) -> None:
        try:
            while True:
                payload = await self._queue.get()
                await self.websocket.send_text(payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The receive loop owns disconnect handling; just stop writing.
            logger.debug("client %s write failed; writer stopping", self.id)
            self._closed = True
