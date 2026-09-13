"""Windowed relative volume across a daylight-saving change.

Time of day came from a fixed UTC offset, which put the same wall-clock minute
an hour apart on either side of the change: no prior session lined up, and the
first EDT Monday read blank all day.
"""

from __future__ import annotations

import pytest

from app.domain.bars import Bar
from app.indicators.functions import windowed_rvol
from tests.conftest import ny_epoch

MINUTES = 120


def session(year: int, month: int, day: int, volume: float) -> list[Bar]:
    """Minute bars from a day's 04:00 New York open, constant volume."""
    start = ny_epoch(year, month, day, 4, 0)
    return [
        Bar(time=start + i * 60, open=10, high=10, low=10, close=10, volume=volume, trades=1)
        for i in range(MINUTES)
    ]


# DST began on Sunday 2026-03-08: the Friday before is EST, the Monday after EDT.
FRIDAY_EST = session(2026, 3, 6, 100)
MONDAY_EDT = session(2026, 3, 9, 200)


def test_the_first_edt_monday_compares_against_the_est_friday():
    (value,) = windowed_rvol(MONDAY_EDT[-1:], FRIDAY_EST + MONDAY_EDT)
    assert value == pytest.approx(2.0)


def test_every_bar_of_that_monday_has_a_reading():
    values = windowed_rvol(MONDAY_EDT, FRIDAY_EST + MONDAY_EDT)
    assert all(value == pytest.approx(2.0) for value in values)


def test_the_change_back_to_est_lines_up_too():
    # DST ended on Sunday 2026-11-01.
    friday_edt = session(2026, 10, 30, 100)
    monday_est = session(2026, 11, 2, 300)
    (value,) = windowed_rvol(monday_est[-1:], friday_edt + monday_est)
    assert value == pytest.approx(3.0)
