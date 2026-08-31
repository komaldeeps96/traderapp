"""Live Benzinga headlines, pushed as they are published.

The measurement that justifies this: four headlines arrived on this socket
about 1.9 seconds *ahead* of their own ``created_at`` stamps. Alpaca's
``delayed_sip`` entitlement governs the price tape and nothing else — news is
a separate product and is not delayed.

It matters because IBKR's live headlines ride generic tick 292, which only
follows the chart that is open. This socket carries the whole market, so a
headline on a watchlist name reaches the terminal while that name is nowhere
on screen — and it does so with no TWS running at all.

Subscribing to everything rather than to a symbol list is deliberate. The
market-wide rate is one or two headlines a minute, which is nothing, and it
removes the resubscribe churn that following a chart around would cost.
Routing is done where the interest is known, not here.

**Alpaca allows one news connection per account.** A second one does not
queue or share — it takes the socket, and the loser sees a close with no
close frame. This was found by running a probe beside a live terminal and
watching the probe get thrown off. So a second copy of this application, or
any other tool holding these keys, will fight this one; the reconnect loop
below then turns that into two clients trading the connection back and forth.
If headlines stop arriving and the log shows repeated drops, look for the
other client before looking here.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable

from websockets.asyncio.client import connect as ws_connect

logger = logging.getLogger(__name__)

# Every headline, filtered by the caller. See the module docstring.
ALL_SYMBOLS = "*"

AUTH_TIMEOUT_SECONDS = 10.0
MAX_BACKOFF_SECONDS = 30.0

HeadlineHandler = Callable[[dict], Awaitable[None]]


class AlpacaNewsStream:
    """One socket, reconnecting for as long as the application is up."""

    def __init__(self, settings):
        self._settings = settings
        self._handlers: list[HeadlineHandler] = []
        self._task: asyncio.Task | None = None
        self._closing = False
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def on_headline(self, handler: HeadlineHandler) -> None:
        self._handlers.append(handler)

    async def start(self) -> None:
        if self._task is not None or not self._settings.enabled:
            return
        if not self._settings.news_stream:
            logger.info("Alpaca news stream disabled by configuration")
            return
        self._closing = False
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._closing = True
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        self._connected = False

    async def _loop(self) -> None:
        url = f"{self._settings.stream_url}/v1beta1/news"
        attempt = 0

        while not self._closing:
            try:
                async with ws_connect(url, max_size=4 * 1024 * 1024) as websocket:
                    await self._authenticate(websocket)
                    await websocket.send(
                        json.dumps({"action": "subscribe", "news": [ALL_SYMBOLS]})
                    )
                    attempt = 0
                    self._connected = True
                    logger.info("Alpaca news stream live")

                    async for raw in websocket:
                        await self._handle(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._closing:
                    break
                attempt += 1
                delay = min(2 ** min(attempt, 5), MAX_BACKOFF_SECONDS)
                logger.warning("Alpaca news stream dropped (%s); retrying in %ss", exc, delay)
            finally:
                self._connected = False

            if self._closing:
                break
            await asyncio.sleep(min(2 ** min(attempt, 5), MAX_BACKOFF_SECONDS))

    async def _authenticate(self, websocket) -> None:
        await websocket.send(
            json.dumps(
                {
                    "action": "auth",
                    "key": self._settings.key_id,
                    "secret": self._settings.secret_key,
                }
            )
        )
        # The server greets first and answers the auth second, so this reads
        # until one or the other resolves rather than assuming an order.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + AUTH_TIMEOUT_SECONDS
        while loop.time() < deadline:
            raw = await asyncio.wait_for(websocket.recv(), timeout=AUTH_TIMEOUT_SECONDS)
            for message in _decode(raw):
                kind = message.get("T")
                if kind == "success" and message.get("msg") == "authenticated":
                    return
                if kind == "error":
                    raise RuntimeError(
                        f"Alpaca news auth failed: {message.get('msg')} "
                        f"(code {message.get('code')})"
                    )
        raise RuntimeError("Alpaca news auth timed out")

    async def _handle(self, raw: str | bytes) -> None:
        for message in _decode(raw):
            # 'n' is a news item; the socket also carries subscription and
            # heartbeat frames, which are not one.
            if message.get("T") != "n":
                continue
            for handler in self._handlers:
                # One bad handler must not take the socket down with it — the
                # reconnect would cost every other headline in the meantime.
                try:
                    await handler(message)
                except Exception:
                    logger.exception("news handler failed")


def _decode(raw: str | bytes) -> list[dict]:
    """Alpaca sends a JSON array of frames, occasionally a bare object."""
    try:
        payload = json.loads(raw)
    except ValueError:
        logger.warning("Alpaca news sent unparseable frame")
        return []
    if isinstance(payload, dict):
        return [payload]
    return [entry for entry in payload if isinstance(entry, dict)]
