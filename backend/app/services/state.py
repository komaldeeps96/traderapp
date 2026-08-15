"""Remembers the last chart the user was looking at.

Kept in its own file so a write can never clobber credentials, which is what
made this worth separating in the first place.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class StateStore:
    def __init__(self, path: str | Path, default_symbol: str, default_timeframe: str):
        self._path = Path(path)
        self._cache: dict[str, str] = {
            "symbol": default_symbol,
            "timeframe": default_timeframe,
        }
        self._load()

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            data = yaml.safe_load(self._path.read_text()) or {}
        except Exception as exc:
            logger.warning("Could not read %s: %s", self._path, exc)
            return

        if isinstance(data, dict):
            for key in ("symbol", "timeframe"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    self._cache[key] = value

    @property
    def symbol(self) -> str:
        return self._cache["symbol"]

    @property
    def timeframe(self) -> str:
        return self._cache["timeframe"]

    def as_dict(self) -> dict[str, str]:
        return dict(self._cache)

    async def save(self, symbol: str, timeframe: str) -> None:
        self._cache = {"symbol": symbol, "timeframe": timeframe}
        await asyncio.to_thread(self._write)

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(yaml.safe_dump(self._cache, sort_keys=True))
        except Exception as exc:
            logger.warning("Could not persist state to %s: %s", self._path, exc)
