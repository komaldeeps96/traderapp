"""The pullback measure: leg detection and each way of answering None."""

from __future__ import annotations

import pytest

from app.domain.bars import Bar
from app.services.pullback import MIN_LEG_PERCENT, measure


def bars_from(prices: list[float], volumes: list[float] | None = None) -> list[Bar]:
    """One bar per price; high==low==close==price keeps the geometry exact."""
    volumes = volumes or [100.0] * len(prices)
    return [
        Bar(
            time=1_700_000_000 + i * 60,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=volume,
            trades=1.0,
        )
        for i, (price, volume) in enumerate(zip(prices, volumes, strict=True))
    ]


class TestNoMeasurement:
    def test_too_few_bars(self):
        assert measure(bars_from([10.0, 10.5])) is None

    def test_flat_tape_has_no_leg(self):
        assert measure(bars_from([10.0] * 30)) is None

    def test_a_leg_below_the_floor_is_chop(self):
        # 2% < MIN_LEG_PERCENT: not a leg worth measuring against.
        assert MIN_LEG_PERCENT > 2.0
        assert measure(bars_from([10.0, 10.1, 10.2, 10.1])) is None

    def test_price_at_the_high_has_nothing_pulled_back(self):
        assert measure(bars_from([10.0, 10.5, 11.0, 11.5])) is None

    def test_a_fully_retraced_leg_is_gone(self):
        # Runs 10 -> 12, then closes below the 10 trough: not a pullback.
        assert measure(bars_from([10.0, 11.0, 12.0, 11.0, 9.5])) is None


class TestMeasurement:
    def test_depth_is_the_share_of_the_leg_given_back(self):
        # Leg 10 -> 12 (20%), close 11.5: gave back 0.5 of 2.0 = 25%.
        result = measure(bars_from([10.0, 11.0, 12.0, 11.7, 11.5]))
        assert result is not None
        assert result.depth_percent == pytest.approx(25.0)
        assert result.leg_percent == pytest.approx(20.0)
        assert result.bars_since_high == 2

    def test_volume_ratio_compares_pullback_to_rally(self):
        result = measure(
            bars_from(
                [10.0, 11.0, 12.0, 11.7, 11.5],
                volumes=[1000, 1000, 1000, 400, 400],
            )
        )
        assert result is not None
        assert result.volume_ratio == pytest.approx(0.4)

    def test_a_silent_rally_yields_no_ratio(self):
        result = measure(bars_from([10.0, 11.0, 12.0, 11.5], volumes=[0, 0, 0, 500]))
        assert result is not None
        assert result.volume_ratio is None

    def test_equal_highs_measure_from_the_latest_test(self):
        """bars_since_high reports freshness of the most recent touch."""
        result = measure(bars_from([10.0, 12.0, 11.0, 12.0, 11.5]))
        assert result is not None
        assert result.bars_since_high == 1

    def test_the_leg_is_the_current_one_not_the_morning(self):
        """Only the trailing window defines the leg."""
        # An old spike to 20 outside the 60-bar window must not shadow
        # the live 10 -> 12 leg.
        old = [20.0] + [10.0] * 60
        result = measure(bars_from([*old, 11.0, 12.0, 11.5]))
        assert result is not None
        assert result.leg_percent == pytest.approx(20.0)
