"""US equity trading sessions, in New York wall-clock time.

Session boundaries drive two visible features: the shaded extended-hours
background on intraday charts, and the pre-market high/low levels.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from ..core.clock import to_ny

PREMARKET_OPEN_HOUR = 4.0  # 04:00 NY
REGULAR_OPEN_HOUR = 9.5  # 09:30 NY
REGULAR_CLOSE_HOUR = 16.0  # 16:00 NY
AFTERHOURS_CLOSE_HOUR = 20.0  # 20:00 NY


class Session(str, Enum):
    CLOSED = "closed"
    PREMARKET = "premarket"
    REGULAR = "regular"
    AFTERHOURS = "afterhours"


def ny_date(epoch: float) -> date:
    return to_ny(epoch).date()


def session_of(epoch: float) -> Session:
    """Classify a timestamp. Weekends are always ``CLOSED``.

    Market holidays are not modelled — the providers simply return no bars on
    those days, so no bar is ever classified against one.
    """
    ny = to_ny(epoch)
    if ny.weekday() >= 5:
        return Session.CLOSED

    hour = ny.hour + ny.minute / 60.0 + ny.second / 3600.0
    if PREMARKET_OPEN_HOUR <= hour < REGULAR_OPEN_HOUR:
        return Session.PREMARKET
    if REGULAR_OPEN_HOUR <= hour < REGULAR_CLOSE_HOUR:
        return Session.REGULAR
    if REGULAR_CLOSE_HOUR <= hour < AFTERHOURS_CLOSE_HOUR:
        return Session.AFTERHOURS
    return Session.CLOSED


def is_extended_hours(epoch: float) -> bool:
    """True for pre-market and after-hours, which the chart tints."""
    return session_of(epoch) in (Session.PREMARKET, Session.AFTERHOURS)
