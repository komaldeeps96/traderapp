"""Request budgets: counting, waiting, and the meter snapshot."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services.api_budget import ApiBudget, ProviderBudget


class TestProviderBudget:
    async def test_counts_requests_inside_the_window(self):
        budget = ProviderBudget("alpaca", limit=5, window_seconds=60)
        for _ in range(3):
            await budget.acquire()
        assert budget.used() == 3

    async def test_snapshot_carries_the_meter_fields(self):
        budget = ProviderBudget("ibkr", limit=60, window_seconds=600)
        await budget.acquire()
        assert budget.snapshot() == {"used": 1, "limit": 60, "window_s": 600}

    async def test_waits_when_the_window_is_full_then_proceeds(self):
        # A 300ms window keeps the test honest without slowing the suite.
        budget = ProviderBudget("alpaca", limit=2, window_seconds=1)
        budget._bucket.rates[0].interval = 300  # milliseconds

        await budget.acquire()
        await budget.acquire()
        started = time.monotonic()
        await budget.acquire()  # must wait for a slot to age out
        waited = time.monotonic() - started

        assert waited >= 0.1
        assert budget.used() >= 1

    async def test_expired_requests_leave_the_count(self):
        budget = ProviderBudget("alpaca", limit=5, window_seconds=1)
        budget._bucket.rates[0].interval = 100  # milliseconds
        await budget.acquire()
        assert budget.used() == 1
        await asyncio.sleep(0.15)
        assert budget.used() == 0

    async def test_concurrent_acquires_never_exceed_the_limit(self):
        budget = ProviderBudget("alpaca", limit=10, window_seconds=60)
        await asyncio.gather(*(budget.acquire() for _ in range(10)))
        assert budget.used() == 10


class TestApiBudget:
    def test_snapshot_covers_both_upstreams(self):
        snapshot = ApiBudget().snapshot()
        assert snapshot["alpaca"] == {"used": 0, "limit": 200, "window_s": 60}
        assert snapshot["ibkr"] == {"used": 0, "limit": 60, "window_s": 600}

    async def test_budgets_are_independent(self):
        budget = ApiBudget()
        await budget.alpaca.acquire()
        assert budget.alpaca.used() == 1
        assert budget.ibkr.used() == 0
