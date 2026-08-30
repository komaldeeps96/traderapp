"""Swing screens.

The service is mostly a filter, and the filter is the part worth testing:
TradingView cannot compare one column against another, so "within 10% of the
52-week high" and "back at the 50-day" are applied here, on rows that have
already come back. Getting a sign wrong in that arithmetic silently inverts a
setup — a pullback screen that returns breakouts.
"""

from __future__ import annotations

import pytest

from app.services.swing import (
    COLUMNS,
    SCREENS_BY_ID,
    SwingService,
    _percent_off_high,
    _shape,
)


def row(**overrides) -> list:
    """One TradingView row, in the column order the service selects."""
    values = {
        "name": "AAA",
        "description": "Alpha Inc.",
        "close": 100.0,
        "change": 1.0,
        "relative_volume_10d_calc": 1.0,
        "market_cap_basic": 5_000_000_000.0,
        "average_volume_10d_calc": 2_000_000.0,
        "Perf.W": 1.0,
        "Perf.1M": 5.0,
        "Perf.3M": 20.0,
        "SMA50": 95.0,
        "SMA200": 80.0,
        "price_52_week_high": 105.0,
        "ADR": 3.0,
        "sector": "Technology",
        "earnings_release_next_date": None,
    }
    values.update(overrides)
    return [values[name] for name in COLUMNS]


def service(rows: list[list]) -> SwingService:
    async def fetch(_query):
        return rows

    return SwingService(fetch=fetch)


class TestDerivedFields:
    def test_distance_below_the_high_is_negative(self):
        """Sign matters: every proximity test below is written against it."""
        assert _percent_off_high(90.0, 100.0) == pytest.approx(-10.0)

    def test_at_the_high_is_zero(self):
        assert _percent_off_high(100.0, 100.0) == 0.0

    def test_a_missing_high_is_not_a_distance(self):
        assert _percent_off_high(90.0, None) is None
        assert _percent_off_high(90.0, 0.0) is None

    def test_shaping_carries_the_derived_columns(self):
        shaped = _shape([row(close=95.0, price_52_week_high=100.0, SMA50=95.0)])[0]
        assert shaped["symbol"] == "AAA"
        assert shaped["off_high"] == pytest.approx(-5.0)
        assert shaped["distance_to_sma50"] == pytest.approx(0.0)

    def test_a_row_with_no_symbol_is_dropped(self):
        assert _shape([row(name="")]) == []


class TestScreens:
    async def test_trend_keeps_what_is_near_the_high(self):
        rows = [
            row(name="NEAR", close=100.0, price_52_week_high=104.0),
            row(name="FAR", close=100.0, price_52_week_high=140.0),
        ]
        found = await service(rows).rows("trend")
        assert [entry["symbol"] for entry in found] == ["NEAR"]

    async def test_breakout_needs_volume_as_well_as_price(self):
        rows = [
            row(
                name="QUIET",
                close=100.0,
                price_52_week_high=101.0,
                **{"relative_volume_10d_calc": 0.8},
            ),
            row(
                name="LOUD",
                close=100.0,
                price_52_week_high=101.0,
                **{"relative_volume_10d_calc": 2.2},
            ),
        ]
        found = await service(rows).rows("breakout")
        assert [entry["symbol"] for entry in found] == ["LOUD"]

    async def test_pullback_excludes_a_stock_at_its_high(self):
        """The one that inverts if a sign is wrong.

        A pullback wants distance from the high, so anything sitting on it
        must be rejected — otherwise the screen quietly returns breakouts.
        """
        rows = [
            row(name="ATHIGH", close=100.0, price_52_week_high=100.0, SMA50=99.0),
            row(name="BACKAT50", close=90.0, price_52_week_high=100.0, SMA50=89.0),
        ]
        found = await service(rows).rows("pullback")
        assert [entry["symbol"] for entry in found] == ["BACKAT50"]

    async def test_pullback_excludes_a_stock_far_from_the_fifty(self):
        rows = [row(name="EXTENDED", close=90.0, price_52_week_high=100.0, SMA50=70.0)]
        assert await service(rows).rows("pullback") == []

    async def test_pullback_excludes_a_collapse(self):
        """25% off the high is a pullback; 60% off is a different trade."""
        rows = [row(name="BROKEN", close=40.0, price_52_week_high=100.0, SMA50=40.0)]
        assert await service(rows).rows("pullback") == []

    async def test_momentum_applies_no_proximity_test(self):
        rows = [row(name="ANY", close=100.0, price_52_week_high=400.0)]
        found = await service(rows).rows("momentum")
        assert [entry["symbol"] for entry in found] == ["ANY"]

    async def test_an_unknown_screen_is_empty_rather_than_an_error(self):
        assert await service([row()]).rows("no_such_screen") == []


class TestConfig:
    async def test_rows_are_capped_by_the_configured_count(self):
        many = [row(name=f"S{index}") for index in range(40)]
        swing = service(many)
        swing.configure(rows=5)
        assert len(await swing.rows("momentum")) == 5

    def test_a_hand_edited_config_cannot_break_a_screen(self):
        swing = service([])
        swing.adopt_config({"rows": "lots", "min_market_cap": -5, "unknown": 1})
        # The bad values are ignored and the defaults stand.
        assert swing.config.rows > 0
        assert swing.config.min_market_cap > 0

    def test_the_row_cap_is_bounded(self):
        swing = service([])
        swing.configure(rows=9999)
        assert swing.config.rows <= 50

    async def test_changing_the_config_drops_the_cache(self):
        calls = 0

        async def fetch(_query):
            nonlocal calls
            calls += 1
            return [row()]

        swing = SwingService(fetch=fetch)
        await swing.rows("momentum")
        await swing.rows("momentum")
        assert calls == 1  # second read came from the cache

        swing.configure(min_market_cap=1_000_000_000)
        await swing.rows("momentum")
        assert calls == 2


class TestFailure:
    async def test_a_failed_screen_says_so_rather_than_looking_empty(self):
        """An empty screen and a broken one must not look the same.

        "Nothing qualifies today" is a real market state and a useful one;
        showing it when TradingView simply refused is a lie.
        """

        async def fetch(_query):
            raise RuntimeError("tradingview said no")

        swing = SwingService(fetch=fetch)
        assert await swing.rows("momentum") == []
        assert swing.note is not None

    async def test_a_failure_keeps_the_last_good_rows(self):
        state = {"fail": False}

        async def fetch(_query):
            if state["fail"]:
                raise RuntimeError("tradingview said no")
            return [row(name="KEPT")]

        swing = SwingService(fetch=fetch)
        await swing.rows("momentum")
        state["fail"] = True
        swing._cache.clear()  # force a refetch
        swing._cache["momentum"] = (0.0, [{"symbol": "KEPT"}])
        assert await swing.rows("momentum") == [{"symbol": "KEPT"}]


class TestCatalogue:
    def test_every_screen_explains_itself(self):
        """A setup nobody can read is a setup nobody will trust."""
        for screen in SCREENS_BY_ID.values():
            assert screen.label and screen.note
            assert screen.note.endswith(".")
