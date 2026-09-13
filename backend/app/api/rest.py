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
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..core.clock import now_epoch
from ..domain.financials import build_statements, convert_to_usd, search_concepts
from ..domain.news import to_paragraphs
from ..domain.protocol import SYMBOL_PATTERN
from ..domain.scanner import SCAN_CODES, SCANNER_TIERS
from ..domain.screener import SymbolStats
from ..domain.sessions import ny_date
from ..domain.timeframes import Timeframe
from ..services.container import AppContainer, get_container
from ..services.metrics import TTM_QUARTERS, build_metrics
from ..services.ownership import summarise
from ..services.scanner import UNAVAILABLE_NOTE
from ..services.swing import SCREENS, SCREENS_BY_ID
from .origin import refuse_cross_site

# Twelve years of annual statements, or three of quarterly. Past that the
# request is a scrape rather than a screen.
MAX_FINANCIAL_PERIODS = 12

Period = Literal["annual", "quarterly"]

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


def _window(period: Period, limit: int) -> tuple[bool, int]:
    """Whether the statements are annual, and how many periods, within bounds."""
    return period == "annual", max(1, min(limit, MAX_FINANCIAL_PERIODS))


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


@router.get("/financials/{symbol}")
async def financials(symbol: str, period: Period = "annual", limit: int = 8) -> dict:
    """Income statement, balance sheet and cash flow, from EDGAR.

    Prefetched like the fundamentals panel: a typed symbol can arrive before
    the subscribe-time warm finishes, and an empty statement reads as a company
    that files nothing.
    """
    container = _container()
    resolved = _symbol(symbol)
    annual, limit = _window(period, limit)

    if container.edgar is None:
        return {
            "symbol": resolved,
            "available": False,
            "note": None,
            "period": period,
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
        "period": period,
        **built,
    }


@router.get("/concepts/{symbol}")
async def concepts(symbol: str, q: str = "", period: Period = "annual", limit: int = 8) -> dict:
    """Every concept a filer tags, searchable — not just the statement lines.

    The curated statement is roughly a tenth of what a company reports. Values
    are **as filed**, in the unit the company used — converting a concept whose
    meaning is not known would invent a number rather than report one.
    """
    container = _container()
    resolved = _symbol(symbol)
    annual, limit = _window(period, limit)

    if container.edgar is None:
        return {"symbol": resolved, "available": False, "query": q, "periods": [], "rows": []}

    await container.edgar.prefetch(resolved)
    found = search_concepts(
        container.edgar.peek_facts(resolved), annual=annual, query=q, limit=limit
    )
    return {"symbol": resolved, "available": True, **found}


@router.get("/metrics/{symbol}")
async def metrics(symbol: str, period: Period = "annual", limit: int = 8) -> dict:
    """Ratios per period, and valuation against today's market cap.

    The multiples mix two sources: the filings for trailing figures and the
    quote side for market cap. A book value is as of a quarter end, and
    comparing today's price against it is the point.
    """
    container = _container()
    resolved = _symbol(symbol)
    annual, limit = _window(period, limit)

    stats = await _reference_stats(container, resolved)
    market_cap = stats.market_cap if stats is not None else None

    if container.edgar is None:
        return {
            "symbol": resolved,
            "available": False,
            "period": period,
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
        "period": period,
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

    Ranked against its own industry rather than every filer: a 39x earnings
    multiple is expensive for a utility and cheap for a chip designer.
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

    Priced per *filing* rather than per company, since the numbers live inside
    each Form 4 — so it is capped, cached, and runs when the tab is opened
    rather than at subscribe time.
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


@router.get("/swing/screens")
async def swing_screens() -> dict:
    """The swing setups on offer, and the filters they share.

    These answer from TradingView alone, so unlike the market-cap scanners they
    still work with no TWS running.
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
        "note": container.swing.note_for(screen_id),
    }


class SwingConfigChange(BaseModel):
    """A JSON body: a page on another site cannot send one without a CORS
    preflight, where query parameters ride a bare form post."""

    model_config = ConfigDict(extra="forbid")

    min_market_cap: float | None = Field(default=None, ge=0)
    min_avg_volume: float | None = Field(default=None, ge=0)
    rows: int | None = Field(default=None, ge=1, le=50)


@router.post("/swing/config")
async def configure_swing(change: SwingConfigChange) -> dict:
    """Retune the screens, and remember it.

    One config shared by all four: they are the same universe seen four ways,
    and a per-screen minimum would mean setting the same number four times.
    """
    container = _container()
    config = container.swing.configure(**change.model_dump())
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
