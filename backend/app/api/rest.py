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

from ..core.clock import now_epoch
from ..domain.news import to_paragraphs
from ..domain.protocol import SYMBOL_PATTERN
from ..domain.scanner import SCAN_CODES, SCANNER_TIERS
from ..domain.sessions import ny_date
from ..domain.timeframes import Timeframe
from ..services.container import AppContainer, get_container
from ..services.financials import build_statements, convert_to_usd, search_concepts
from ..services.metrics import TTM_QUARTERS, build_metrics
from ..services.ownership import summarise
from ..services.scanner import UNAVAILABLE_NOTE
from ..services.swing import SCREENS, SCREENS_BY_ID

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
    # Everything on this screen is quoted in dollars, so a filer reporting in
    # its own currency is converted rather than captioned and left alone.
    built = await convert_to_usd(built, container.fx)
    return {
        "symbol": resolved,
        "available": True,
        "note": container.edgar.note(),
        "period": "annual" if annual else "quarterly",
        **built,
    }


@router.get("/concepts/{symbol}")
async def concepts(symbol: str, q: str = "", period: str = "annual", limit: int = 8) -> dict:
    """Every concept a filer tags, searchable — not just the statement lines.

    The curated statement is roughly a tenth of what a company reports, and
    the rest is where a specific question gets answered. Values here are **as
    filed**, in the unit the company used: this is the raw view, and
    converting a concept whose meaning is not known would be inventing a
    number rather than reporting one.
    """
    container = _container()
    resolved = _symbol(symbol)
    annual = period != "quarterly"
    limit = max(1, min(limit, MAX_FINANCIAL_PERIODS))

    if container.edgar is None:
        return {"symbol": resolved, "available": False, "query": q, "periods": [], "rows": []}

    await container.edgar.prefetch(resolved)
    found = search_concepts(
        container.edgar.peek_facts(resolved), annual=annual, query=q, limit=limit
    )
    return {"symbol": resolved, "available": True, **found}


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
    facts = container.edgar.peek_facts(resolved)
    # Built and converted once, then handed to the ratios: a foreign filer
    # must not be converted twice, and the two tabs must not disagree.
    statements = await convert_to_usd(
        build_statements(facts, annual=annual, limit=limit), container.fx
    )
    # The quarters, whatever the table is showing, because the multiples are
    # quoted on a trailing twelve months everywhere else and a fiscal-year
    # P/E disagrees with every other screen the user has open.
    trailing = await convert_to_usd(
        build_statements(facts, annual=False, limit=TTM_QUARTERS), container.fx
    )
    built = build_metrics(
        facts,
        annual=annual,
        limit=limit,
        market_cap=market_cap,
        statements=statements,
        trailing=trailing,
        # The same reference row the market cap came from. A filer with no
        # 10-Q leaves nothing to trail, and this carries a trailing year.
        stats=stats.to_dict() if stats is not None else None,
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


@router.get("/peers/{symbol}")
async def peers(symbol: str) -> dict:
    """The company beside the ones it competes with.

    Ranked against its own industry rather than against every filer: a 39x
    earnings multiple is expensive for a utility and cheap for a chip
    designer, and a percentile across all US issuers cannot tell them apart.
    """
    container = _container()
    resolved = _symbol(symbol)
    if not container.settings.regime.enabled:
        return {
            "symbol": resolved,
            "available": False,
            "industry": "",
            "rows": [],
            "ranks": [],
            "note": None,
        }
    comparison = await container.peers.compare(resolved)
    return {"symbol": resolved, "available": True, **comparison}


@router.get("/ownership/{symbol}")
async def ownership(symbol: str) -> dict:
    """What insiders have done, with the payroll set aside.

    Priced per *filing* rather than per company — the numbers live inside
    each Form 4 — so it is capped, cached, and never warmed at subscribe
    time. It runs when the tab is opened and not before.
    """
    container = _container()
    resolved = _symbol(symbol)

    if container.edgar is None:
        return {
            "symbol": resolved,
            "available": False,
            "note": None,
            "summary": None,
            "trades": [],
        }

    await container.edgar.prefetch(resolved)
    filings = container.edgar.peek_filings(resolved)
    trades = await container.ownership.trades(resolved, filings)
    return {
        "symbol": resolved,
        "available": True,
        "note": container.edgar.note(),
        "summary": summarise(trades, ny_date(now_epoch())),
        "trades": [trade.to_dict() for trade in trades],
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


@router.get("/swing/screens")
async def swing_screens() -> dict:
    """The swing setups on offer, and the filters they share.

    These answer from TradingView alone, so unlike the market-cap scanners
    they still work with no TWS running — which is most of the time outside a
    session.
    """
    container = _container()
    return {
        "screens": [
            {"id": screen.id, "label": screen.label, "note": screen.note}
            for screen in SCREENS
        ],
        "config": container.swing.config.to_dict(),
        "note": container.swing.note,
    }


@router.get("/swing/{screen_id}")
async def swing_rows(screen_id: str) -> dict:
    container = _container()
    if screen_id not in SCREENS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Unknown screen {screen_id!r}")
    return {
        "screen_id": screen_id,
        "rows": await container.swing.rows(screen_id),
        "config": container.swing.config.to_dict(),
        "note": container.swing.note,
    }


@router.post("/swing/config")
async def configure_swing(
    min_market_cap: float | None = None,
    min_avg_volume: float | None = None,
    rows: int | None = None,
) -> dict:
    """Retune the screens, and remember it.

    One config shared by all four: they are the same universe seen four ways,
    and a per-screen minimum would mean setting the same number four times.
    """
    container = _container()
    config = container.swing.configure(
        min_market_cap=min_market_cap,
        min_avg_volume=min_avg_volume,
        rows=rows,
    )
    await container.state.save_swing(config.to_dict())
    return {"config": config.to_dict()}


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
