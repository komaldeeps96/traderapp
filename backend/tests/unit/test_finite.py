"""The NaN guard.

Every screener row arrives through pandas, which fills a missing cell with
NaN. `isinstance(nan, float)` is True, so a plain type check lets it through,
and NaN then fails silently rather than loudly: every comparison against it
is False, so a row carrying one passes a filter *because* it failed the test.

This is a real defect that shipped for about an hour. It ranked Apple first
of thirty-one on price-to-book — at 43x against a peer median of 2x —
because three peers reported no book value at all.
"""

from __future__ import annotations

import math

import pytest

from app.domain.screener import finite
from app.services.peers import rank
from app.services.swing import SCREENS_BY_ID, _passes


class TestFinite:
    def test_passes_a_real_number(self):
        assert finite(1.5) == 1.5
        assert finite(3) == 3.0

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_rejects_what_is_not_a_number(self, value):
        assert finite(value) is None

    @pytest.mark.parametrize("value", [None, "12", "", [], {}])
    def test_rejects_what_is_not_numeric(self, value):
        assert finite(value) is None

    def test_rejects_a_bool(self):
        """True is an int in Python, and a market cap of 1.0 is not a fact."""
        assert finite(True) is None
        assert finite(False) is None


class TestNanCannotRank:
    def _rows(self, *values):
        return [{"symbol": f"S{index}", "price_book": value} for index, value in enumerate(values)]

    @staticmethod
    def _book(rows, symbol):
        return next(entry for entry in rank(rows, symbol) if entry["key"] == "price_book")

    def test_a_missing_peer_does_not_move_the_ranking(self):
        clean = self._rows(1.0, 2.0, 43.0)
        clean[2]["symbol"] = "ME"
        without = self._book(clean, "ME")

        dirty = self._rows(1.0, 2.0, 43.0, None)
        dirty[2]["symbol"] = "ME"
        with_gap = self._book(dirty, "ME")

        # The company with no book value is left out, not counted as zero and
        # not allowed to shuffle everyone else.
        assert without["position"] == with_gap["position"] == 3
        assert with_gap["total"] == 3

    def test_the_subject_without_a_value_is_unranked(self):
        rows = self._rows(1.0, 2.0, None)
        rows[2]["symbol"] = "ME"
        entry = self._book(rows, "ME")
        assert entry["position"] is None
        assert entry["value"] is None

    def test_a_measure_with_one_reporter_is_not_a_ranking(self):
        """A rank of "first of one" is not information."""
        rows = self._rows(5.0, None, None)
        rows[0]["symbol"] = "ME"
        entry = self._book(rows, "ME")
        assert entry["position"] is None


class TestNanCannotPassAFilter:
    def test_a_row_with_no_high_is_rejected(self):
        """Every comparison against NaN is False.

        So `off_high < -10` is False for a missing high, and the row passes
        the "within 10% of the high" test by failing it.
        """
        screen = SCREENS_BY_ID["trend"]
        assert _passes(screen, {"off_high": -5.0}) is True
        assert _passes(screen, {"off_high": None}) is False
        assert _passes(screen, {"off_high": math.nan}) is False

    def test_a_row_with_no_volume_is_rejected_by_the_breakout_screen(self):
        screen = SCREENS_BY_ID["breakout"]
        assert _passes(screen, {"off_high": -1.0, "rvol": 2.0}) is True
        assert _passes(screen, {"off_high": -1.0, "rvol": math.nan}) is False
