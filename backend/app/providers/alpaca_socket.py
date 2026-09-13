"""The frame encoding and auth handshake both Alpaca sockets share."""

from __future__ import annotations

import asyncio
import json
import logging

from ..core.settings import AlpacaSettings
from .base import ProviderError

logger = logging.getLogger(__name__)

AUTH_TIMEOUT_SECONDS = 10.0


def decode(raw: str | bytes) -> list[dict]:
    """Alpaca sends a JSON array of frames, occasionally a bare object."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Alpaca sent an undecodable frame")
        return []
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    return []


async def authenticate(websocket, settings: AlpacaSettings) -> None:
    """Send the keys and wait for the verdict.

    The server greets first and answers the auth second, so this reads until
    one or the other resolves rather than assuming an order.
    """
    await websocket.send(
        json.dumps({"action": "auth", "key": settings.key_id, "secret": settings.secret_key})
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + AUTH_TIMEOUT_SECONDS
    while loop.time() < deadline:
        raw = await asyncio.wait_for(websocket.recv(), timeout=AUTH_TIMEOUT_SECONDS)
        for message in decode(raw):
            kind = message.get("T")
            if kind == "success" and message.get("msg") == "authenticated":
                return
            if kind == "error":
                raise ProviderError(
                    f"Alpaca auth failed: {message.get('msg')} (code {message.get('code')})"
                )
    raise ProviderError("Alpaca auth timed out")
