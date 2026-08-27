"""The reverse-split cache: parsing, recency, and the cached miss."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.corporate_actions import ReverseSplitService, _latest, _parse


class TestParse:
    def test_a_well_formed_split(self):
        split = _parse({"old_rate": 10, "new_rate": 1, "ex_date": "2026-07-01"})
        assert split is not None
        assert split.ratio == pytest.approx(10.0)
        assert split.ex_date == date(2026, 7, 1)

    def test_process_date_backs_up_a_missing_ex_date(self):
        split = _parse({"old_rate": 4, "new_rate": 1, "process_date": "2026-07-02"})
        assert split is not None
        assert split.ex_date == date(2026, 7, 2)

    @pytest.mark.parametrize(
        "row",
        [
            {"old_rate": 0, "new_rate": 1, "ex_date": "2026-07-01"},
            {"old_rate": 10, "new_rate": 0, "ex_date": "2026-07-01"},
            {"old_rate": 10, "new_rate": 1},
            {"old_rate": "x", "new_rate": 1, "ex_date": "2026-07-01"},
            {"old_rate": 10, "new_rate": 1, "ex_date": "not a date"},
            {},
        ],
    )
    def test_malformed_rows_are_dropped(self, row):
        assert _parse(row) is None

    def test_latest_wins(self):
        rows = [
            {"old_rate": 5, "new_rate": 1, "ex_date": "2026-01-01"},
            {"old_rate": 12, "new_rate": 1, "ex_date": "2026-07-01"},
            {"old_rate": 8, "new_rate": 1, "ex_date": "2025-11-01"},
        ]
        assert _latest(rows).ratio == pytest.approx(12.0)


class TestService:
    async def test_prefetch_then_peek(self):
        async def fetch(symbol, start):
            return [{"old_rate": 10, "new_rate": 1, "ex_date": "2026-07-01"}]

        service = ReverseSplitService(fetch)
        assert service.peek("FGI") is None
        await service.prefetch("FGI")
        assert service.peek("FGI").ratio == pytest.approx(10.0)

    async def test_an_empty_answer_is_cached(self):
        calls = []

        async def fetch(symbol, start):
            calls.append(symbol)
            return []

        service = ReverseSplitService(fetch)
        await service.prefetch("FGI")
        await service.prefetch("FGI")
        assert service.peek("FGI") is None
        assert calls == ["FGI"]

    async def test_a_failed_fetch_leaves_no_cache_entry(self):
        async def fetch(symbol, start):
            raise RuntimeError("api down")

        service = ReverseSplitService(fetch)
        await service.prefetch("FGI")
        assert service.peek("FGI") is None
        # Not cached: the next prefetch tries again rather than trusting
        # a miss that was really an outage.
        assert "FGI" not in service._cache
