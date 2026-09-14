"""REST endpoints.

Everything here is static or near-static configuration the frontend needs
before it can draw: which indicators exist, which timeframes are offered, and
what the data source is currently doing. Live data goes over the WebSocket.

The dock's panels are served here too: filings and XBRL facts change quarterly,
are read when a tab is opened rather than streamed, and would be forty fields
of dead weight on every broadcast tick. Only the compact verdict the
always-visible chip needs rides on the ``info`` message.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException

from ..domain.news import to_paragraphs
from ..domain.protocol import SYMBOL_PATTERN
from ..domain.scanner import SCAN_CODES, SCANNER_TIERS
from ..domain.screener import SymbolStats
from ..domain.timeframes import Timeframe
from ..services.container import AppContainer, get_container
from ..services.scanner import UNAVAILABLE_NOTE
from .origin import refuse_cross_site

router = APIRouter(prefix="/api", dependencies=[Depends(refuse_cross_site)])

_SYMBOL = re.compile(SYMBOL_PATTERN)


def _container() -> AppContainer:
    return get_container()


def _symbol(raw: str) -> str:
    """Validate a path symbol the same way the WebSocket validates a command.

    It ends up in an upstream URL, so it is checked against the one pattern
    rather than trusted because it arrived over a different transport.
    """
    symbol = raw.strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise HTTPException(status_code=422, detail="invalid symbol")
    return symbol


async def _reference_stats(container: AppContainer, symbol: str) -> SymbolStats | None:
    """TradingView's reference row for a symbol.

    Fetched rather than peeked: a panel opens the moment a symbol changes, which
    can beat the subscribe-time warm. Gated on the regime switch as the
    WebSocket's prefetch is, so a run with it off reaches nothing.
    """
    if container.settings.regime.enabled:
        return await container.tv.get_stats(symbol)
    return container.tv.peek_stats(symbol)


@router.get("/health")
async def health() -> dict:
    container = _container()
    return {
        "status": "ok",
        "clients": container.hub.connection_count,
        **container.fanout.status_payload(),
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
        # Only the toggles that differ from `indicators.yaml`, keyed by
        # timeframe. The client applies them over the defaults it already has
        # from /api/indicators, so the two cannot drift apart.
        "indicators": container.state.indicator_overrides(),
    }


@router.get("/fundamentals/{symbol}")
async def fundamentals(symbol: str) -> dict:
    """Everything the fundamentals tab draws, for one symbol.

    Warmed at subscribe time by the symbol-info prefetch, so normally a cache
    read. It still awaits the prefetch rather than returning empty: a typed
    symbol can arrive before the warm has finished.
    """
    container = _container()
    resolved = _symbol(symbol)
    # TradingView's ratios ride the row the info strip already fetches, so they
    # are free whether or not EDGAR is on.
    stats = await _reference_stats(container, resolved)
    business = stats.to_dict() if stats is not None else None

    if container.edgar is None:
        return {
            "symbol": resolved,
            "available": False,
            "note": None,
            "dilution": None,
            "profile": None,
            "business": business,
        }

    await container.edgar.prefetch(resolved)
    read = container.symbol_info.dilution(resolved)
    profile = container.edgar.peek_profile(resolved)
    return {
        "symbol": resolved,
        "available": True,
        # Set only when EDGAR itself is the problem, so an empty panel can say
        # "SEC refused us" rather than "this company files nothing".
        "note": container.edgar.note(),
        "dilution": read.to_dict() if read is not None else None,
        "profile": profile.to_dict() if profile is not None else None,
        "business": business,
    }


@router.get("/filings/{symbol}")
async def filings(symbol: str) -> dict:
    """The SEC filing trail, classified by what each form means to a trade.

    Dilution and distress forms are what the panel leads with; the rest are
    carried so they can sit behind a fold rather than being dropped.
    """
    container = _container()
    resolved = _symbol(symbol)
    if container.edgar is None:
        return {"symbol": resolved, "available": False, "note": None, "filings": []}

    await container.edgar.prefetch(resolved)
    return {
        "symbol": resolved,
        "available": True,
        "note": container.edgar.note(),
        "filings": [row.to_dict() for row in container.edgar.peek_filings(resolved)],
    }


@router.get("/news/{symbol}")
async def news(symbol: str) -> dict:
    """Thirty days of headlines for a symbol, deduplicated and tagged.

    Warmed at subscribe time and awaited here, like the fundamentals endpoint:
    a typed symbol can reach this before the warm finishes.
    """
    container = _container()
    resolved = _symbol(symbol)
    await container.news.prefetch(resolved)
    return {
        "symbol": resolved,
        "providers": await container.news.providers(),
        "headlines": [row.to_dict() for row in container.news.peek(resolved)],
    }


@router.get("/news/{symbol}/brief")
async def news_brief(symbol: str, refresh: bool = False) -> dict:
    """One day's headlines, read and scored out of ten.

    Awaited rather than kicked off and pushed: a reading takes five to fifteen
    seconds and the panel shows a spinner for that long. A second client asking
    mid-reading joins the same process.

    Never raises for an ordinary absence — no CLI, nothing published today, the
    reader timed out — since the panel prints those in one line and a 500 would
    show as a broken terminal. ``refresh`` overrides the cooldown.
    """
    container = _container()
    resolved = _symbol(symbol)
    await container.news.prefetch(resolved)
    payload = await container.news_ai.brief(resolved, force=refresh)
    return {"symbol": resolved, **payload}


@router.get("/news/{symbol}/article")
async def news_article(symbol: str, provider: str, article_id: str) -> dict:
    """One article body, as plain-text paragraphs.

    The wire sends an HTML fragment, converted to text server-side rather than
    rendered as markup: third-party content on the page that holds the trading
    UI.

    Provider and article id are query parameters, not path segments, because
    IBKR's ids carry a ``$`` (``DJ-N$1f364634``).
    """
    container = _container()
    _symbol(symbol)
    if not provider or not article_id:
        raise HTTPException(status_code=422, detail="provider and article_id are required")
    body = await container.news.article(provider, article_id)
    return {"provider": provider, "article_id": article_id, "paragraphs": to_paragraphs(body)}


@router.get("/watchlist")
async def watchlist() -> dict:
    """The list and a quote for each name on it.

    Adding and removing go over the WebSocket, so every open window sees the
    change; this is the first read, for a client that has just loaded.
    """
    container = _container()
    return {
        "symbols": container.watchlist.symbols(),
        "rows": await container.watchlist.rows(),
        "note": container.watchlist.note,
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
