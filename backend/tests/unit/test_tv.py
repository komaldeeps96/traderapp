"""TradingView reference data: regime counts and per-symbol stats.

The network seam is the injectable ``fetch``; these tests capture the query
it would send and feed back canned payloads, so no test dials out.
"""

from __future__ import annotations

import json

import pytest

from app.services.tv import _COLUMNS, TVDataService


def payload_row(symbol: str, **values) -> dict:
    """One raw API row with named overrides on top of blanks."""
    row = [None] * len(_COLUMNS)
    index = {name: i for i, name in enumerate(_COLUMNS)}
    row[index["name"]] = symbol
    for key, value in values.items():
        row[index[key]] = value
    return {"s": f"NASDAQ:{symbol}", "d": row}


class Recorder:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.queries: list[dict] = []

    def __call__(self, query) -> dict:
        self.queries.append(query.query)
        return self.responses.pop(0)


class TestStats:
    async def test_fetches_and_caches(self):
        fetch = Recorder(
            [
                {
                    "totalCount": 1,
                    "data": [
                        payload_row(
                            "GME",
                            float_shares_outstanding=8_000_000,
                            market_cap_basic=90_000_000,
                            average_volume_10d_calc=3_000_000,
                            description="GameStop",
                        )
                    ],
                }
            ]
        )
        service = TVDataService(fetch=fetch)

        stats = await service.get_stats("GME")
        assert stats is not None
        assert stats.float_shares == pytest.approx(8_000_000)

        again = await service.get_stats("GME")
        assert again is stats
        assert len(fetch.queries) == 1  # served from cache

        assert service.peek_stats("GME") is stats

    async def test_missing_symbol_returns_none(self):
        # Two empty responses: the exact lookup and the substring fallback.
        fetch = Recorder([{"totalCount": 0, "data": []}] * 2)
        service = TVDataService(fetch=fetch)
        assert await service.get_stats("ZZZZ") is None
        assert len(fetch.queries) == 2

    async def test_falls_back_to_a_substring_search(self):
        """Newly listed symbols are missing from the exact-match index.

        Measured on DFSC (DEFSEC Technologies, NASDAQ common): matching on
        `name` equality returned nothing, and so did a lookup by its own
        reported ticker — while a substring search returned the row. A fresh
        listing is exactly what a momentum scanner surfaces, so the miss is
        not an edge case.
        """
        fetch = Recorder(
            [
                {"totalCount": 0, "data": []},
                {
                    "totalCount": 2,
                    "data": [
                        payload_row("DFSCX", market_cap_basic=1.0),
                        payload_row("DFSC", float_shares_outstanding=2_650_000,
                                    market_cap_basic=3_300_000),
                    ],
                },
            ]
        )
        service = TVDataService(fetch=fetch)

        stats = await service.get_stats("DFSC")
        assert stats is not None
        assert stats.symbol == "DFSC"
        assert stats.float_shares == pytest.approx(2_650_000)

    async def test_the_fallback_does_not_accept_a_near_miss(self):
        """`like` is a substring match — searching FGI also returns MFGI."""
        fetch = Recorder(
            [
                {"totalCount": 0, "data": []},
                {"totalCount": 1, "data": [payload_row("MFGI", market_cap_basic=1.0)]},
            ]
        )
        service = TVDataService(fetch=fetch)
        assert await service.get_stats("FGI") is None

    async def test_network_failure_keeps_the_cache(self):
        calls = {"n": 0}

        def flaky(query):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "totalCount": 1,
                    "data": [payload_row("GME", float_shares_outstanding=1.0)],
                }
            raise RuntimeError("down")

        service = TVDataService(fetch=flaky)
        first = await service.get_stats("GME")
        assert first is not None
        service._stats_cache["GME"].fetched_at = 0  # force expiry
        assert await service.get_stats("GME") is first


class TestRegime:
    async def test_counts_both_thresholds(self):
        fetch = Recorder(
            [
                {"totalCount": 7, "data": []},
                {"totalCount": 2, "data": []},
            ]
        )
        service = TVDataService(fetch=fetch)
        regime = await service.market_regime()
        assert {regime.up_50_count, regime.up_100_count} == {7, 2}
