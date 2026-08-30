"""A company against the ones it competes with.

A ratio on its own is not a judgement. A 39× earnings multiple is expensive
for a utility and cheap for a chip designer, and the only cheap way to know
which is to put the company beside its own industry.

This is why the terminal ranks against *peers* rather than against every
filer. SEC's frames endpoint would give a market-wide percentile across some
six thousand companies, and a gross margin in the 80th percentile of "all
US issuers" says almost nothing — the comparison set is dominated by
businesses with no relationship to this one.

Everything here rides a single TradingView query, so a peer table costs one
request rather than one per company.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from statistics import median

from tradingview_screener import Query, col

from ..core.clock import now_epoch
from ..domain.screener import finite
from .tv import _common_stock_terms

logger = logging.getLogger(__name__)

PEERS_TTL_SECONDS = 900.0

# Industries run to a few dozen listed names; this is a ceiling, not a target.
MAX_PEERS = 60

COLUMNS = [
    "name",
    "description",
    "market_cap_basic",
    "price_earnings_ttm",
    "price_sales_current",
    "price_book_fq",
    "gross_margin",
    "operating_margin",
    "return_on_equity",
    "debt_to_equity",
    "total_revenue",
    "Perf.YTD",
    "earnings_release_next_date",
    "industry",
]


@dataclass(frozen=True, slots=True)
class Measure:
    key: str
    label: str
    unit: str
    # Whether a bigger number is the better one. Decides which end of the
    # ranking counts as first, and it is not always obvious: a low P/E is a
    # good rank, a low gross margin is a bad one.
    higher_is_better: bool


MEASURES: tuple[Measure, ...] = (
    Measure("market_cap", "Market cap", "money", True),
    Measure("price_earnings", "P/E", "multiple", False),
    Measure("price_sales", "P/S", "multiple", False),
    Measure("price_book", "P/B", "multiple", False),
    Measure("gross_margin", "Gross margin", "percent", True),
    Measure("operating_margin", "Operating margin", "percent", True),
    Measure("return_on_equity", "Return on equity", "percent", True),
    Measure("debt_to_equity", "Debt / equity", "ratio", False),
    Measure("perf_ytd", "Performance YTD", "percent", True),
)


# TradingView quotes margins and returns as whole percents — 36.15 for
# 36.15%. Everything else in this terminal carries a percentage as a
# fraction, so they are converted once here rather than at each place that
# draws them; the peer *median* is computed from these, and a strip reading
# "median 3614.6%" is what a second conversion site produces.
_PERCENT_COLUMNS = frozenset({"gross_margin", "operating_margin", "return_on_equity", "Perf.YTD"})


def _shape(payload) -> list[dict]:
    index = {name: position for position, name in enumerate(COLUMNS)}

    def number(row, name):
        value = finite(row[index[name]])
        if value is None:
            return None
        return value / 100.0 if name in _PERCENT_COLUMNS else value

    def text(row, name):
        value = row[index[name]]
        return value if isinstance(value, str) else ""

    rows: list[dict] = []
    for row in payload:
        symbol = text(row, "name")
        if not symbol:
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": text(row, "description"),
                "industry": text(row, "industry"),
                "market_cap": number(row, "market_cap_basic"),
                "price_earnings": number(row, "price_earnings_ttm"),
                "price_sales": number(row, "price_sales_current"),
                "price_book": number(row, "price_book_fq"),
                "gross_margin": number(row, "gross_margin"),
                "operating_margin": number(row, "operating_margin"),
                "return_on_equity": number(row, "return_on_equity"),
                "debt_to_equity": number(row, "debt_to_equity"),
                "revenue": number(row, "total_revenue"),
                "perf_ytd": number(row, "Perf.YTD"),
                "next_earnings": number(row, "earnings_release_next_date"),
            }
        )
    return rows


def rank(rows: list[dict], symbol: str) -> list[dict]:
    """Where the subject sits among its peers, measure by measure.

    A rank needs at least one company to compare against, and a measure the
    subject does not report cannot be ranked at all — an unranked row says
    so rather than guessing a middle.
    """
    subject = next((row for row in rows if row["symbol"] == symbol), None)
    if subject is None:
        return []

    out: list[dict] = []
    for measure in MEASURES:
        values = [row[measure.key] for row in rows if isinstance(row.get(measure.key), float)]
        mine = subject.get(measure.key)
        if mine is None or len(values) < 2:
            out.append(
                {
                    "key": measure.key,
                    "label": measure.label,
                    "unit": measure.unit,
                    "value": mine,
                    "median": median(values) if values else None,
                    "position": None,
                    "total": len(values),
                }
            )
            continue

        ordered = sorted(values, reverse=measure.higher_is_better)
        out.append(
            {
                "key": measure.key,
                "label": measure.label,
                "unit": measure.unit,
                "value": mine,
                "median": median(values),
                "position": ordered.index(mine) + 1,
                "total": len(ordered),
            }
        )
    return out


class PeerService:
    def __init__(self, tv, fetch=None):
        self._tv = tv
        self._fetch = fetch
        self._cache: dict[str, tuple[float, dict]] = {}

    def peek(self, symbol: str) -> dict | None:
        cached = self._cache.get(symbol)
        if cached is None or now_epoch() - cached[0] >= PEERS_TTL_SECONDS:
            return None
        return cached[1]

    async def compare(self, symbol: str) -> dict:
        fresh = self.peek(symbol)
        if fresh is not None:
            return fresh

        stats = await self._tv.get_stats(symbol)
        industry = getattr(stats, "industry", "") if stats is not None else ""
        if not industry:
            empty = {"industry": "", "rows": [], "ranks": [], "note": None}
            self._cache[symbol] = (now_epoch(), empty)
            return empty

        try:
            payload = await self._run(industry)
        except Exception as exc:
            logger.warning("Peer query for %s failed: %s", symbol, exc)
            return {
                "industry": industry,
                "rows": [],
                "ranks": [],
                "note": "TradingView did not answer; no peer table.",
            }

        rows = _shape(payload)
        result = {
            "industry": industry,
            "rows": rows,
            "ranks": rank(rows, symbol),
            "note": None,
        }
        self._cache[symbol] = (now_epoch(), result)
        return result

    async def _run(self, industry: str):
        query = (
            Query()
            .select(*COLUMNS)
            .where(*_common_stock_terms(), col("industry") == industry)
            .order_by("market_cap_basic", ascending=False)
            .limit(MAX_PEERS)
        )
        if self._fetch is not None:
            return await self._fetch(query)
        return await asyncio.to_thread(_scan, query)


def _scan(query: Query) -> list[list]:
    _, frame = query.get_scanner_data()
    return frame[COLUMNS].values.tolist() if not frame.empty else []
