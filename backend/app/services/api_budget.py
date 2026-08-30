"""Request budgets for the two market-data upstreams.

Switching tickers aggressively burns historical-data requests, and both
upstreams punish overuse — Alpaca throttles past 200 REST calls a minute,
IBKR pacing rejects historical requests past roughly 60 in ten minutes.
Every request takes a slot here first (waiting, not failing, when the window
is full), and the meters in the toolbar read the same buckets, so "can I
switch symbols comfortably right now" is answerable at a glance.

The windowing is pyrate-limiter's sliding in-memory bucket; this wraps it
with asyncio-friendly waiting, because the library's own blocking delay
would stall the event loop.
"""

from __future__ import annotations

import asyncio
import logging

from pyrate_limiter import Duration, InMemoryBucket, MonotonicClock, Rate, RateItem

logger = logging.getLogger(__name__)

# Alpaca's documented REST allowance on the free plan.
ALPACA_LIMIT = 200
ALPACA_WINDOW_SECONDS = 60

# IBKR historical-data pacing: ~60 requests per 10 minutes before it starts
# refusing with pacing violations.
IBKR_LIMIT = 60
IBKR_WINDOW_SECONDS = 600

# SEC asks for no more than ten requests a second and blocks on sustained
# excess. Nine leaves room for the occasional retry without ever touching the
# published limit.
EDGAR_LIMIT = 9
EDGAR_WINDOW_SECONDS = 1

_POLL_SECONDS = 0.2


class ProviderBudget:
    def __init__(self, name: str, limit: int, window_seconds: int):
        self.name = name
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = MonotonicClock()
        self._bucket = InMemoryBucket([Rate(limit, window_seconds * Duration.SECOND)])
        self._warned = False

    async def acquire(self) -> None:
        """Take one request slot, waiting for the window when it is full.

        Waiting is the point: a request held back a few seconds keeps the
        upstream friendly, where a request fired anyway earns a throttle that
        stalls everything.
        """
        while not self._bucket.put(RateItem(self.name, self._clock.now())):
            if not self._warned:
                self._warned = True
                logger.warning(
                    "%s request budget exhausted (%d per %ds); holding requests",
                    self.name,
                    self.limit,
                    self.window_seconds,
                )
            await asyncio.sleep(_POLL_SECONDS)
        self._warned = False

    def used(self) -> int:
        """Requests currently inside the sliding window."""
        self._bucket.leak(self._clock.now())
        return self._bucket.count()

    def snapshot(self) -> dict:
        return {"used": self.used(), "limit": self.limit, "window_s": self.window_seconds}


class ApiBudget:
    """One budget per upstream, shared by every service that calls out."""

    def __init__(self) -> None:
        self.alpaca = ProviderBudget("alpaca", ALPACA_LIMIT, ALPACA_WINDOW_SECONDS)
        self.ibkr = ProviderBudget("ibkr", IBKR_LIMIT, IBKR_WINDOW_SECONDS)
        self.edgar = ProviderBudget("edgar", EDGAR_LIMIT, EDGAR_WINDOW_SECONDS)

    def snapshot(self) -> dict:
        return {
            "alpaca": self.alpaca.snapshot(),
            "ibkr": self.ibkr.snapshot(),
            "edgar": self.edgar.snapshot(),
        }
