"""Reverse splits, the serial-diluter tell.

A reverse split on a small cap is rarely housekeeping: it is how a company
that has diluted its way under listing compliance buys another year of
listing. On the momentum cohort a recent one reads as "this management
sells stock into strength", which is exactly the information a long wants
before paying up. The corporate-actions endpoint is the only place to see
it — our own history is fetched split-*adjusted*, so the discontinuity is
invisible in the bars by construction.

Same shape as the TradingView stats service: an async ``prefetch`` warmed at
subscribe time, a sync ``peek`` read on the broadcast path, and a TTL long
enough that one fetch a day per symbol is the steady state. Misses are
cached too — most symbols have no splits, and refetching an empty answer
every broadcast would burn the request budget on nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta

from ..core.clock import now_epoch
from ..domain.sessions import ny_date

logger = logging.getLogger(__name__)

# How far back a reverse split still says something about management.
# Generous next to the display: the frontend decides what is "recent".
WINDOW_DAYS = 400

CACHE_TTL_SECONDS = 24 * 3600.0

FetchSplits = Callable[[str, date], Awaitable[list[dict]]]


@dataclass(slots=True)
class ReverseSplit:
    """One reverse split: ``ratio`` old shares became one new share."""

    ratio: float
    ex_date: date


class ReverseSplitService:
    def __init__(self, fetch: FetchSplits):
        self._fetch = fetch
        # symbol -> (fetched_at, latest split or None). The None is a cached
        # miss, deliberately: "no splits" is the common answer.
        self._cache: dict[str, tuple[float, ReverseSplit | None]] = {}

    async def prefetch(self, symbol: str) -> None:
        cached = self._cache.get(symbol)
        if cached is not None and now_epoch() - cached[0] < CACHE_TTL_SECONDS:
            return
        try:
            rows = await self._fetch(symbol, ny_date(now_epoch()) - timedelta(days=WINDOW_DAYS))
        except Exception:
            logger.debug("reverse split fetch failed for %s", symbol, exc_info=True)
            return
        self._cache[symbol] = (now_epoch(), _latest(rows))

    def peek(self, symbol: str) -> ReverseSplit | None:
        cached = self._cache.get(symbol)
        return cached[1] if cached is not None else None


def _latest(rows: list[dict]) -> ReverseSplit | None:
    """The most recent well-formed split, or None."""
    best: ReverseSplit | None = None
    for row in rows:
        parsed = _parse(row)
        if parsed is not None and (best is None or parsed.ex_date > best.ex_date):
            best = parsed
    return best


def _parse(row: dict) -> ReverseSplit | None:
    try:
        old_rate = float(row["old_rate"])
        new_rate = float(row["new_rate"])
        stamp = row.get("ex_date") or row.get("process_date")
        if old_rate <= 0 or new_rate <= 0 or not stamp:
            return None
        return ReverseSplit(ratio=old_rate / new_rate, ex_date=date.fromisoformat(str(stamp)))
    except (KeyError, TypeError, ValueError):
        return None
