"""Time helpers.

Everything inside the backend is UTC epoch seconds. Conversion to New York
wall-clock time happens only where market sessions are decided.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")


def now() -> datetime:
    return datetime.now(UTC)


def now_epoch() -> float:
    return now().timestamp()


def to_utc(dt: datetime) -> datetime:
    """Attach UTC to a naive datetime, or convert an aware one."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_ny(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC).astimezone(NY_TZ)


def parse_rfc3339(value: str) -> datetime:
    """Parse an RFC-3339 timestamp, tolerating nanosecond precision.

    Alpaca sends up to 9 fractional digits; ``datetime`` accepts at most 6.
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    if "." in text:
        head, _, tail = text.partition(".")
        digits = ""
        for char in tail:
            if char.isdigit():
                digits += char
            else:
                break
        remainder = tail[len(digits) :]
        text = f"{head}.{digits[:6]:0<6}{remainder}" if digits else head + remainder

    return to_utc(datetime.fromisoformat(text))


def rfc3339(dt: datetime) -> str:
    """Format for Alpaca query parameters, which reject fractional seconds."""
    return to_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")
