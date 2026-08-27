"""REST endpoints.

Everything here is static or near-static configuration the frontend needs
before it can draw: which indicators exist, which timeframes are offered, and
what the data source is currently doing. Live data goes over the WebSocket.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..domain.scanner import SCAN_CODES, SCANNER_TIERS
from ..domain.timeframes import Timeframe
from ..services.container import AppContainer, get_container
from ..services.scanner import UNAVAILABLE_NOTE

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


@router.get("/scanner/tiers")
async def scanner_tiers() -> dict:
    """Static, shared scanner metadata — the four tiers and the scan codes
    they can run. Each tier's live config/rows/running state arrives instead
    over the WebSocket's opening frames moments after connect, so it is not
    duplicated here where it could drift out of sync.
    """
    return {
        "scan_codes": [dict(entry) for entry in SCAN_CODES],
        "tiers": [{"id": tier["id"], "label": tier["label"]} for tier in SCANNER_TIERS],
        "note": UNAVAILABLE_NOTE,
    }
