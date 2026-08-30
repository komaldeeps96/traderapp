"""Foreign exchange, so a filer's statements can be read in dollars.

A company reporting in CAD, DKK or CNY is not comparable to anything else on
the screen until it is converted. The rates come from Frankfurter, which
serves the European Central Bank's published reference rates: free, no key,
no attribution requirement, and a source that can be pointed at if a number
is ever questioned.

**Two conventions, because a balance and a flow are not converted the same
way.** IAS 21 puts income and expenses at the rate on the transaction date —
approximated, as every data provider does, by the average across the period —
and assets and liabilities at the closing rate on the balance-sheet date.
Using one rate for both is the common shortcut and it is wrong: checked
against TradingView's own USD figures for Alibaba, the period average lands
within 0.06% while the closing rate is out by 2.94%.

Rates for a period that has already ended never change, so they are cached
for the life of the process. The public endpoint rate-limits, and a miss is
worth one retry rather than a wrong number: a failed conversion returns None
and the caller reports the statements in their own currency instead.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from datetime import date

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.frankfurter.app"
USD = "USD"

# One retry, after a pause. The endpoint answers 429 under a burst, and the
# alternative to waiting is a statement converted at no rate at all.
RETRY_DELAY_SECONDS = 1.5
MAX_ATTEMPTS = 2
TIMEOUT_SECONDS = 20.0


class FxService:
    """Rates into USD, cached forever because history does not move."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owned: httpx.AsyncClient | None = None
        self._closing: dict[tuple[str, date], float | None] = {}
        self._average: dict[tuple[str, date, date], float | None] = {}
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owned is not None:
            await self._owned.aclose()
            self._owned = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        if self._owned is None:
            self._owned = httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=True)
        return self._owned

    async def closing_rate(self, currency: str, on: date) -> float | None:
        """The rate on one day — what a balance sheet is converted at.

        Frankfurter answers a weekend or holiday with the previous business
        day's rate, which is the same thing every provider does and the same
        thing an accountant does.
        """
        if currency == USD:
            return 1.0
        key = (currency, on)
        if key in self._closing:
            return self._closing[key]
        payload = await self._get(f"/{on.isoformat()}", currency)
        rate = _extract(payload)
        self._closing[key] = rate
        return rate

    async def average_rate(self, currency: str, start: date, end: date) -> float | None:
        """The mean rate across a period — what a flow is converted at.

        Every published business day in the window, equally weighted. A
        revenue figure is earned across the year, not on its last day.
        """
        if currency == USD:
            return 1.0
        if start > end:
            start, end = end, start
        key = (currency, start, end)
        if key in self._average:
            return self._average[key]

        payload = await self._get(f"/{start.isoformat()}..{end.isoformat()}", currency)
        rates: list[float] = []
        if isinstance(payload, dict):
            for entry in (payload.get("rates") or {}).values():
                value = (entry or {}).get(USD) if isinstance(entry, dict) else None
                if isinstance(value, (int, float)) and value > 0:
                    rates.append(float(value))
        rate = statistics.fmean(rates) if rates else None
        self._average[key] = rate
        return rate

    async def _get(self, path: str, base: str) -> dict | None:
        async with self._lock:
            for attempt in range(MAX_ATTEMPTS):
                try:
                    response = await self._http().get(
                        f"{BASE_URL}{path}", params={"base": base, "symbols": USD}
                    )
                    if response.status_code == 200:
                        return response.json()
                    logger.debug("FX %s for %s%s", response.status_code, BASE_URL, path)
                except Exception:
                    logger.debug("FX request failed: %s%s", BASE_URL, path, exc_info=True)
                if attempt + 1 < MAX_ATTEMPTS:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
        return None


def _extract(payload: dict | None) -> float | None:
    if not isinstance(payload, dict):
        return None
    value = (payload.get("rates") or {}).get(USD)
    return float(value) if isinstance(value, (int, float)) and value > 0 else None
