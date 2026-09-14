"""The NaN guard.

Every screener row arrives through pandas, which fills a missing cell with
NaN. `isinstance(nan, float)` is True, so a plain type check lets it through,
and every comparison against NaN is False — a row carrying one passes a filter
by failing its test.
"""

from __future__ import annotations

import pytest

from app.domain.screener import finite


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
