import json
import logging
from typing import Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connection: Optional[WebSocket] = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._connection = websocket

    def disconnect(self):
        self._connection = None

    @property
    def is_connected(self) -> bool:
        return self._connection is not None

    async def send(self, msg: dict):
        if not self._connection:
            return
        try:
            await self._connection.send_text(json.dumps(msg))
        except Exception as e:
            logger.error(f"Failed to send WS message: {e}")
