"""A plain list of symbols, with a price beside each.

No folders, no groups, no sorting rules — a list, in the order things were
added to it. The order is information: the name put there this morning is
usually the one being worked.

Quotes come from the same TradingView row the rest of the terminal uses, in
one request for the whole list. A watchlist is glanced at, not scalped off,
so a price a few seconds old is worth far more than a stream per symbol.

It does **not** reuse the screeners' universe filter, and that is the whole
point of this module. A screener has to decide what deserves to be in a
ranked list nobody asked for, so it keeps to primary listings of US common
stock. A watchlist has no such question to answer: somebody typed the symbol.
Running the screener's filter over it silently blanked three whole classes of
instrument — Canopy Growth, whose primary listing is the TSX; every ADR, since
Alibaba is typed `dr` and not `stock`; and every ETF, which the client library
excludes by default in a filter of its own.
"""

from __future__ import annotations

import asyncio
import logging

from tradingview_screener import Query, col

from ..core.clock import now_epoch
from ..domain.screener import finite

# US listings only, because that is what the chart beside this can draw.
EXCHANGES = ["NASDAQ", "NYSE", "AMEX"]

# Replaces the client library's own default, which admits common and preferred
# stock, depositary receipts and non-ETF funds — and excludes ETFs outright.
# Anything with a US listing and a price is something a person can watch.
ANY_INSTRUMENT = {
    "operator": "or",
    "operands": [
        {"expression": {"left": "type", "operation": "equal", "right": kind}}
        for kind in ("stock", "dr", "fund")
    ],
}

logger = logging.getLogger(__name__)

# Long enough that flicking between tabs costs nothing, short enough that the
# numbers are the ones on the chart beside them.
QUOTES_TTL_SECONDS = 20.0

# Past this the panel is a screener, and the terminal already has two.
MAX_SYMBOLS = 50

COLUMNS = [
    "name",
    "description",
    "close",
    "change",
    "volume",
    "relative_volume_10d_calc",
    "market_cap_basic",
    "premarket_change",
    "earnings_release_next_date",
]


class WatchlistService:
    def __init__(self, state, fetch=None, *, quotes_enabled: bool = True):
        self._state = state
        self._fetch = fetch
        # The same switch every other TradingView call already answers to. The
        # list is the feature; the prices are what it can reach. With the
        # screener off — a test run, or a desk with no outbound access — the
        # names, their order and their persistence all still work.
        self._quotes_enabled = quotes_enabled
        self._quotes: tuple[float, dict[str, dict]] | None = None
        self._note: str | None = None

    @property
    def note(self) -> str | None:
        """Set only when the quote fetch failed, so an empty panel can say
        so rather than reading as an empty list."""
        return self._note

    def symbols(self) -> list[str]:
        return self._state.watchlist()

    async def add(self, symbol: str) -> list[str]:
        """Append, unless it is already there.

        Adding a symbol twice is almost always a mis-click, and a list with
        one name in it twice is worse than useless.
        """
        wanted = symbol.strip().upper()
        current = self.symbols()
        if not wanted or wanted in current or len(current) >= MAX_SYMBOLS:
            return current
        updated = [*current, wanted]
        await self._state.save_watchlist(updated)
        self._quotes = None
        return updated

    async def remove(self, symbol: str) -> list[str]:
        wanted = symbol.strip().upper()
        current = self.symbols()
        if wanted not in current:
            return current
        updated = [entry for entry in current if entry != wanted]
        await self._state.save_watchlist(updated)
        self._quotes = None
        return updated

    async def rows(self) -> list[dict]:
        """One row per symbol, in the list's own order.

        A symbol the screener does not know still gets a row — a delisted or
        mistyped ticker must be visible so it can be removed, not silently
        dropped from the list it is still in.
        """
        symbols = self.symbols()
        if not symbols:
            return []
        if not self._quotes_enabled:
            self._note = "Quotes are switched off; the list is still yours."
            return [{"symbol": symbol, **_blank()} for symbol in symbols]
        quotes = await self._quotes_for(symbols)
        return [{"symbol": symbol, **quotes.get(symbol, _blank())} for symbol in symbols]

    async def _quotes_for(self, symbols: list[str]) -> dict[str, dict]:
        if self._quotes is not None and now_epoch() - self._quotes[0] < QUOTES_TTL_SECONDS:
            cached = self._quotes[1]
            if all(symbol in cached for symbol in symbols):
                return cached

        try:
            payload = await self._run(symbols)
        except Exception as exc:
            logger.warning("Watchlist quotes failed: %s", exc)
            self._note = "TradingView did not answer; prices are stale."
            return self._quotes[1] if self._quotes else {}

        self._note = None
        quotes = _shape(payload)
        self._quotes = (now_epoch(), quotes)
        return quotes

    async def _run(self, symbols: list[str]):
        query = (
            Query()
            .select(*COLUMNS)
            .where(col("exchange").isin(EXCHANGES), col("name").isin(symbols))
            .limit(MAX_SYMBOLS)
        )
        query.set_property("filter2", ANY_INSTRUMENT)
        if self._fetch is not None:
            return await self._fetch(query)
        return await asyncio.to_thread(_scan, query)


def _blank() -> dict:
    return {
        "name": "",
        "close": None,
        "change": None,
        "volume": None,
        "rvol": None,
        "market_cap": None,
        "premarket_change": None,
        "next_earnings": None,
    }


def _scan(query: Query) -> list[list]:
    _, frame = query.get_scanner_data()
    return frame[COLUMNS].values.tolist() if not frame.empty else []


def _shape(payload) -> dict[str, dict]:
    index = {name: position for position, name in enumerate(COLUMNS)}

    def number(row, name):
        return finite(row[index[name]])

    def text(row, name):
        value = row[index[name]]
        return value if isinstance(value, str) else ""

    out: dict[str, dict] = {}
    for row in payload:
        symbol = text(row, "name")
        if not symbol:
            continue
        out[symbol] = {
            "name": text(row, "description"),
            "close": number(row, "close"),
            "change": number(row, "change"),
            "volume": number(row, "volume"),
            "rvol": number(row, "relative_volume_10d_calc"),
            "market_cap": number(row, "market_cap_basic"),
            "premarket_change": number(row, "premarket_change"),
            "next_earnings": number(row, "earnings_release_next_date"),
        }
    return out
