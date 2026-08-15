"""The market-regime poll.

How many listed common stocks are up 50% and 100% today. Setup quality holds
in a hot tape and degrades badly in a cold one, so the same chart is worth
trading on one day and not the next — the count is the cheapest read of which
day it is.

This was a full TradingView screener until the panel was removed in favour of
a standard screener on a second monitor. Only the regime survived it, so only
the regime is polled: the scan itself was a wasted request every fifteen
seconds for rows nothing displayed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from ..core.settings import RegimeSettings
from ..domain.screener import RegimeState
from .tv import TVDataService

logger = logging.getLogger(__name__)

UpdateHandler = Callable[[RegimeState], Awaitable[None]]


class RegimeService:
    def __init__(self, tv: TVDataService, settings: RegimeSettings):
        self._tv = tv
        self._settings = settings
        self._handlers: list[UpdateHandler] = []
        self._task: asyncio.Task | None = None
        self._state = RegimeState()

    def on_update(self, handler: UpdateHandler) -> None:
        self._handlers.append(handler)

    @property
    def state(self) -> RegimeState:
        return self._state

    async def start(self) -> None:
        if not self._settings.enabled:
            return
        if self._task is None or self._task.done():
            self._state.running = True
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._state.running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self._poll()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._state.error = str(exc)
                logger.warning("regime poll failed: %s", exc)
                await self._notify()
            await asyncio.sleep(self._settings.refresh_seconds)

    async def _poll(self) -> None:
        self._state.regime = await self._tv.market_regime()
        self._state.error = None
        self._state.running = True
        await self._notify()

    async def _notify(self) -> None:
        for handler in self._handlers:
            try:
                await handler(self._state)
            except Exception:
                logger.exception("regime update handler failed")
