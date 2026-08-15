"""REST endpoints.

Everything here is static or near-static configuration the frontend needs
before it can draw: which indicators exist, which timeframes are offered, and
what the data source is currently doing. Live data goes over the WebSocket.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..domain.scanner import SCAN_CODES
from ..domain.timeframes import Timeframe
from ..services.container import AppContainer, get_container

router = APIRouter(prefix="/api")


def _container() -> AppContainer:
    return get_container()


@router.get("/health")
async def health() -> dict:
    container = _container()
    return {
        "status": "ok",
        "clients": container.hub.connection_count,
        **container.status_payload(),
    }


@router.get("/indicators")
async def indicators() -> list[dict]:
    return [spec.to_client() for spec in _container().specs]


@router.get("/timeframes")
async def timeframes() -> list[dict]:
    return [
        {"value": tf.value, "label": tf.label, "intraday": tf.is_intraday}
        for tf in Timeframe
    ]


@router.get("/session")
async def session() -> dict:
    """The chart to open on load: whatever was last viewed."""
    container = _container()
    return {
        "symbol": container.state.symbol,
        "timeframe": container.state.timeframe,
        "default_symbol": container.settings.default_symbol,
        "default_timeframe": container.settings.default_timeframe,
    }


@router.get("/scanner/config")
async def scanner_config() -> dict:
    container = _container()
    state = container.scanner.state
    return {
        "scan_codes": [dict(entry) for entry in SCAN_CODES],
        "config": state.config.to_dict(),
        "running": state.running,
        "available": container.scanner.available,
        "note": container.scanner.note(),
    }
