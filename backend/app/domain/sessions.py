"""US equity trading sessions, in New York wall-clock time.

Session boundaries drive two visible features: the shaded extended-hours
background on intraday charts, and the pre-market high/low levels.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from enum import Enum

from ..core.clock import NY_TZ, to_ny

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


def prior_session_open(reference: datetime, sessions: int = 1) -> datetime:
    """04:00 NY on the trading day ``sessions`` before the current one.

    "The current one" is the session ``reference`` sits in, and before 04:00
    that is still yesterday's — at 02:00 Thursday nothing has traded today,
    so one session back is Tuesday, not Wednesday.

    Weekends are stepped over. Market holidays are not, for the same reason
    ``session_of`` does not model them: the providers return no bars on those
    days, so a holiday costs the window one session of depth and nothing
    else.
    """
    ny = to_ny(reference.timestamp())
    day = ny.date()
    if ny.hour < PREMARKET_OPEN_HOUR:
        day -= timedelta(days=1)
    day = _back_to_weekday(day)
    for _ in range(max(sessions, 0)):
        day = _back_to_weekday(day - timedelta(days=1))
    # The session hours are floats because 09:30 is one of them; take the
    # minutes off this one too rather than truncating a half hour away if
    # the pre-market open ever moves.
    hour, minute = divmod(round(PREMARKET_OPEN_HOUR * 60), 60)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY_TZ).astimezone(UTC)


def _back_to_weekday(day: date) -> date:
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day
