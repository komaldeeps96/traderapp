"""Exchange rates that survive a restart.

A rate for a period that has already closed cannot change, so re-learning
last week's is pure waste — and the endpoint rate-limits under a burst, which
is exactly what opening a terminal on a foreign filer produces.
"""

from __future__ import annotations

import json
from datetime import date

from app.services.fx import FxService


class Recording:
    """Stands in for the network, and counts how often it is asked."""

    def __init__(self, rate: float | None = 0.75):
        self.calls = 0
        self.rate = rate

    async def get(self, url, params=None):
        self.calls += 1
        # A range request answers with a rate per published day; a single
        # date answers with one rate. The service reads them differently.
        return _Response(self.rate, ranged=".." in str(url))


class _Response:
    def __init__(self, rate, ranged: bool = False):
        self.status_code = 200 if rate is not None else 500
        self._rate = rate
        self._ranged = ranged

    def json(self):
        if self._ranged:
            return {"rates": {"2025-06-02": {"USD": self._rate}}}
        return {"rates": {"USD": self._rate}}


class TestPersistence:
    async def test_a_rate_survives_a_restart(self, tmp_path):
        path = tmp_path / "fx.json"
        first = FxService(client=Recording(), cache_path=path)
        assert await first.closing_rate("CAD", date(2025, 12, 31)) == 0.75
        await first.close()

        network = Recording(rate=0.99)
        second = FxService(client=network, cache_path=path)
        # The cached value, and the network was never touched.
        assert await second.closing_rate("CAD", date(2025, 12, 31)) == 0.75
        assert network.calls == 0

    async def test_an_average_survives_too(self, tmp_path):
        path = tmp_path / "fx.json"
        first = FxService(client=Recording(), cache_path=path)
        await first.average_rate("CAD", date(2025, 1, 1), date(2025, 12, 31))
        await first.close()

        network = Recording(rate=0.99)
        second = FxService(client=network, cache_path=path)
        assert await second.average_rate("CAD", date(2025, 1, 1), date(2025, 12, 31)) == 0.75
        assert network.calls == 0

    async def test_a_different_period_is_still_fetched(self, tmp_path):
        path = tmp_path / "fx.json"
        first = FxService(client=Recording(), cache_path=path)
        await first.closing_rate("CAD", date(2025, 12, 31))
        await first.close()

        network = Recording(rate=0.60)
        second = FxService(client=network, cache_path=path)
        assert await second.closing_rate("CAD", date(2024, 12, 31)) == 0.60
        assert network.calls == 1

    async def test_a_refusal_is_not_written_down(self, tmp_path):
        """A rate the endpoint declined once is worth asking for again.

        Caching the miss would turn one rate-limited second into a
        permanently unconvertible period.
        """
        path = tmp_path / "fx.json"
        failing = FxService(client=Recording(rate=None), cache_path=path)
        assert await failing.closing_rate("CAD", date(2025, 12, 31)) is None
        await failing.close()

        network = Recording(rate=0.75)
        second = FxService(client=network, cache_path=path)
        assert await second.closing_rate("CAD", date(2025, 12, 31)) == 0.75
        assert network.calls == 1


class TestRobustness:
    async def test_a_corrupt_cache_costs_one_refetch(self, tmp_path):
        path = tmp_path / "fx.json"
        path.write_text("{not json")
        service = FxService(client=Recording(), cache_path=path)
        assert await service.closing_rate("CAD", date(2025, 12, 31)) == 0.75

    async def test_a_hand_edited_entry_cannot_poison_it(self, tmp_path):
        path = tmp_path / "fx.json"
        path.write_text(json.dumps({"closing": {"CAD|2025-12-31": "cheap", "CAD|nonsense": 0.5}}))
        service = FxService(client=Recording(), cache_path=path)
        # The bad entries are ignored and the rate is fetched properly.
        assert await service.closing_rate("CAD", date(2025, 12, 31)) == 0.75

    async def test_no_cache_path_still_works(self):
        service = FxService(client=Recording())
        assert await service.closing_rate("CAD", date(2025, 12, 31)) == 0.75
        await service.close()

    async def test_dollars_never_touch_the_network_or_the_cache(self, tmp_path):
        network = Recording()
        service = FxService(client=network, cache_path=tmp_path / "fx.json")
        assert await service.closing_rate("USD", date(2025, 12, 31)) == 1.0
        assert network.calls == 0
