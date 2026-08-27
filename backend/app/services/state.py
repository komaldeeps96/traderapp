"""Remembers the last chart the user was looking at, and each scanner
tier's filters.

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
        self._cache: dict[str, object] = {
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
            scanners = data.get("scanners")
            if isinstance(scanners, dict):
                # Stored as-is, per tier id; ScannerService.adopt_config
                # validates each entry on the way in, so a hand-edited or
                # stale file cannot poison it.
                self._cache["scanners"] = {
                    key: value for key, value in scanners.items() if isinstance(value, dict)
                }

    @property
    def symbol(self) -> str:
        return str(self._cache["symbol"])

    @property
    def timeframe(self) -> str:
        return str(self._cache["timeframe"])

    def scanner_config(self, scanner_id: str) -> dict | None:
        """The last filters saved for one scanner tier, or None if none were."""
        scanners = self._cache.get("scanners")
        if not isinstance(scanners, dict):
            return None
        config = scanners.get(scanner_id)
        return dict(config) if isinstance(config, dict) else None

    def as_dict(self) -> dict[str, object]:
        return dict(self._cache)

    async def save(self, symbol: str, timeframe: str) -> None:
        # Update, not replace: the scanners section must survive a chart save.
        self._cache.update(symbol=symbol, timeframe=timeframe)
        await asyncio.to_thread(self._write)

    async def save_scanner(self, scanner_id: str, config: dict) -> None:
        scanners = self._cache.setdefault("scanners", {})
        if not isinstance(scanners, dict):
            scanners = {}
            self._cache["scanners"] = scanners
        scanners[scanner_id] = dict(config)
        await asyncio.to_thread(self._write)

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(yaml.safe_dump(self._cache, sort_keys=True))
        except Exception as exc:
            logger.warning("Could not persist state to %s: %s", self._path, exc)
