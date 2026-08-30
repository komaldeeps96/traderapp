"""REST endpoints.

Everything here is static or near-static configuration the frontend needs
before it can draw: which indicators exist, which timeframes are offered, and
what the data source is currently doing. Live data goes over the WebSocket.

The dock's panels are served here too, and belong here for the same reason: a
company's filings and XBRL facts change quarterly, are read when a tab is
opened rather than streamed, and would be forty fields of dead weight on every
broadcast tick. Only the compact verdict the always-visible chip needs rides
on the ``info`` message.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from ..domain.news import to_paragraphs
from ..domain.protocol import SYMBOL_PATTERN
from ..domain.scanner import SCAN_CODES, SCANNER_TIERS
from ..domain.timeframes import Timeframe
from ..services.container import AppContainer, get_container
from ..services.financials import build_statements
from ..services.metrics import build_metrics
from ..services.scanner import UNAVAILABLE_NOTE

# Twelve years of annual statements, or three of quarterly. Past that the
# request is a scrape rather than a screen.
MAX_FINANCIAL_PERIODS = 12

router = APIRouter(prefix="/api")

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
        # Only the toggles that differ from `indicators.yaml`, keyed by
        # timeframe. The client applies them over the defaults it already has
        # from /api/indicators, so the two cannot drift apart.
        "indicators": container.state.indicator_overrides(),
    }


@router.get("/fundamentals/{symbol}")
async def fundamentals(symbol: str) -> dict:
    """Everything the fundamentals tab draws, for one symbol.

    Warmed at subscribe time by the symbol-info prefetch, so this is normally
    a cache read. It still awaits a prefetch rather than returning empty: a
    symbol reached by typing rather than by clicking a scanner row can arrive
    here before the warm has finished, and an empty panel that fills a second
    later reads as a bug.
    """
    container = _container()
    resolved = _symbol(symbol)
    # TradingView's ratios ride the row the info strip already fetches, so
    # they are free here whether or not EDGAR is switched on.
    #
    # Fetched rather than peeked: this endpoint is called the moment a symbol
    # changes, which can beat the subscribe-time warm, and a peek would then
    # return nothing and leave the Business group missing until the next
    # symbol switch. Gated on the regime switch exactly as the WebSocket's
    # prefetch is, so a run with it off still reaches nothing off-machine.
    stats = (
        await container.tv.get_stats(resolved)
        if container.settings.regime.enabled
        else container.tv.peek_stats(resolved)
    )
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


@router.get("/financials/{symbol}")
async def financials(symbol: str, period: str = "annual", limit: int = 8) -> dict:
    """Income statement, balance sheet and cash flow, from EDGAR.

    Prefetched the same way the fundamentals panel is, and for the same
    reason: a symbol reached by typing can arrive before the subscribe-time
    warm has finished, and an empty statement that fills a second later reads
    as a company that files nothing.
    """
    container = _container()
    resolved = _symbol(symbol)
    annual = period != "quarterly"
    limit = max(1, min(limit, MAX_FINANCIAL_PERIODS))

    if container.edgar is None:
        return {
            "symbol": resolved,
            "available": False,
            "note": None,
            "period": "annual" if annual else "quarterly",
            "periods": [],
            "statements": [],
        }

    await container.edgar.prefetch(resolved)
    built = build_statements(container.edgar.peek_facts(resolved), annual=annual, limit=limit)
    return {
        "symbol": resolved,
        "available": True,
        "note": container.edgar.note(),
        "period": "annual" if annual else "quarterly",
        **built,
    }


@router.get("/metrics/{symbol}")
async def metrics(symbol: str, period: str = "annual", limit: int = 8) -> dict:
    """Ratios per period, and valuation against today's market cap.

    The multiples deliberately mix two sources: the filings for the trailing
    figures and the quote side for market cap. A book value is as of a
    quarter end, and comparing today's price against it is the whole point.
    """
    container = _container()
    resolved = _symbol(symbol)
    annual = period != "quarterly"
    limit = max(1, min(limit, MAX_FINANCIAL_PERIODS))

    stats = (
        await container.tv.get_stats(resolved)
        if container.settings.regime.enabled
        else container.tv.peek_stats(resolved)
    )
    market_cap = stats.market_cap if stats is not None else None

    if container.edgar is None:
        return {
            "symbol": resolved,
            "available": False,
            "period": "annual" if annual else "quarterly",
            "periods": [],
            "groups": [],
            "valuation": None,
        }

    await container.edgar.prefetch(resolved)
    built = build_metrics(
        container.edgar.peek_facts(resolved),
        annual=annual,
        limit=limit,
        market_cap=market_cap,
    )
    return {
        "symbol": resolved,
        "available": True,
        "period": "annual" if annual else "quarterly",
        **built,
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

    Warmed at subscribe time; awaited here for the same reason the
    fundamentals endpoint awaits its prefetch — a symbol typed rather than
    clicked can reach this before the warm finishes.
    """
    container = _container()
    resolved = _symbol(symbol)
    await container.news.prefetch(resolved)
    return {
        "symbol": resolved,
        "providers": await container.news.providers(),
        "headlines": [row.to_dict() for row in container.news.peek(resolved)],
    }


@router.get("/news/{symbol}/article")
async def news_article(symbol: str, provider: str, article_id: str) -> dict:
    """One article body, as plain-text paragraphs.

    The wire sends an HTML fragment. It is converted to text server-side
    rather than rendered as markup in the browser: this is third-party content
    on the page that also holds the trading UI.

    Provider and article id are query parameters rather than path segments
    because IBKR's ids carry a ``$`` (``DJ-N$1f364634``), which is legal in a
    query string and a nuisance in a path.
    """
    container = _container()
    _symbol(symbol)
    if not provider or not article_id:
        raise HTTPException(status_code=422, detail="provider and article_id are required")
    body = await container.news.article(provider, article_id)
    return {"provider": provider, "article_id": article_id, "paragraphs": to_paragraphs(body)}


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
