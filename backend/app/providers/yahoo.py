"""Yahoo Finance float, as a second opinion.

TradingView's float goes stale on exactly the day it matters most — an
offering prices, the float doubles, and the screener row still shows last
month's number. There is no single correct source, so the honest move is
two sources and a visible disagreement: the frontend shows a divergence
badge instead of silently trusting either.

This is Yahoo's unofficial API. It wants a session cookie and a "crumb"
token before quoteSummary answers, both of which Yahoo changes at will —
so every failure here degrades to None and the badge simply does not
render. Nothing downstream may depend on this provider answering.

Cache is deliberately long: float changes on corporate events, not
intraday, and an unofficial endpoint earns politeness.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx

from ..core.clock import now_epoch

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 24 * 3600.0
# A failed lookup is retried sooner, but not on every broadcast tick.
MISS_TTL_SECONDS = 3600.0

# Yahoo answers curl-ish agents with a consent wall; a browser string gets
# the JSON. Any current desktop UA works.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

_COOKIE_URL = "https://fc.yahoo.com/"
# Two interchangeable API hosts; the crumb endpoint rate-limits per host, so
# a 429 from one is worth one try against the other.
_CRUMB_URLS = (
    "https://query1.finance.yahoo.com/v1/test/getcrumb",
    "https://query2.finance.yahoo.com/v1/test/getcrumb",
)
_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"


class YahooFloatProvider:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._crumb: str | None = None
        # symbol -> (fetched_at, float or None). None is a cached miss.
        self._cache: dict[str, tuple[float, float | None]] = {}
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def peek_float(self, symbol: str) -> float | None:
        """The cached float, without touching the network."""
        cached = self._cache.get(symbol)
        return cached[1] if cached is not None else None

    async def prefetch(self, symbol: str) -> None:
        cached = self._cache.get(symbol)
        if cached is not None:
            ttl = CACHE_TTL_SECONDS if cached[1] is not None else MISS_TTL_SECONDS
            if now_epoch() - cached[0] < ttl:
                return
        # One flight at a time: the crumb dance must not run concurrently
        # with itself, and float lookups are never urgent.
        async with self._lock:
            value = await self._fetch_float(symbol)
        self._cache[symbol] = (now_epoch(), value)

    async def _fetch_float(self, symbol: str) -> float | None:
        try:
            client = self._ensure_client()
            if await self._ensure_crumb(client) is None:
                return None
            response = await client.get(
                _SUMMARY_URL.format(symbol=symbol),
                params={"modules": "defaultKeyStatistics", "crumb": self._crumb},
            )
            if response.status_code in (401, 403):
                # Crumbs expire with the cookie; one refresh, one retry.
                self._crumb = None
                if await self._ensure_crumb(client) is None:
                    return None
                response = await client.get(
                    _SUMMARY_URL.format(symbol=symbol),
                    params={"modules": "defaultKeyStatistics", "crumb": self._crumb},
                )
            if response.status_code != 200:
                logger.debug("Yahoo %s for %s", response.status_code, symbol)
                return None
            return _parse_float(response.json())
        except Exception:
            logger.debug("Yahoo float lookup failed for %s", symbol, exc_info=True)
            return None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": _UA, "Accept": "*/*"},
                timeout=10.0,
                follow_redirects=True,
                transport=self._transport,
            )
        return self._client

    async def _ensure_crumb(self, client: httpx.AsyncClient) -> str | None:
        if self._crumb:
            return self._crumb
        # Any Yahoo property sets the session cookie; this endpoint 404s but
        # the cookie rides the response anyway and the client keeps it.
        with contextlib.suppress(httpx.HTTPError):
            await client.get(_COOKIE_URL)
        for url in _CRUMB_URLS:
            response = await client.get(url)
            crumb = response.text.strip()
            # A consent page or error body is HTML, never a bare token.
            if response.status_code == 200 and crumb and "<" not in crumb and len(crumb) <= 64:
                self._crumb = crumb
                return crumb
        return None


def _parse_float(payload: dict) -> float | None:
    try:
        stats = payload["quoteSummary"]["result"][0]["defaultKeyStatistics"]
        raw = stats["floatShares"]["raw"]
        value = float(raw)
        return value if value > 0 else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None
