"""Daily key levels projected onto an intraday chart.

All levels for a given day are derived from daily bars that closed *strictly
before* that day. That rule is what keeps them stable: a "prev day close" or a
"52-week high" drawn on today's 1-minute chart must not move as today trades,
otherwise the level repaints under the trader.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..domain.bars import Bar
from ..domain.sessions import ny_date
from .functions import Number, ema, rolling_max, rolling_min, sma


@dataclass(frozen=True, slots=True)
class LevelKey:
    """Identifies one daily level, e.g. ``sma`` over 20 bars."""

    kind: str
    span: int = 0

    def __str__(self) -> str:
        return f"{self.kind}:{self.span}" if self.span else self.kind


# Level kinds that take a span.
SPAN_KINDS = frozenset({"sma", "ema", "high", "low"})
# Level kinds derived from the previous completed calendar period.
PERIOD_KINDS = frozenset(
    {
        "prev_day_high",
        "prev_day_low",
        "prev_day_close",
        "prev_week_high",
        "prev_week_low",
        "prev_week_close",
        "prev_month_high",
        "prev_month_low",
        "prev_month_close",
        "prev_quarter_high",
        "prev_quarter_low",
        "prev_quarter_close",
        "prev_year_high",
        "prev_year_low",
        "prev_year_close",
    }
)


def _week_bucket(day: date) -> tuple[int, int]:
    iso = day.isocalendar()
    return (iso.year, iso.week)


def _month_bucket(day: date) -> tuple[int, int]:
    return (day.year, day.month)


def _quarter_bucket(day: date) -> tuple[int, int]:
    return (day.year, (day.month - 1) // 3 + 1)


def _year_bucket(day: date) -> tuple[int, int]:
    # A one-tuple would order fine, but keeping the shape uniform lets
    # _previous_bucket compare every period the same way.
    return (day.year, 0)


# Longest first: "prev_month_" must not be matched by a shorter prefix, and
# the field is always the last underscore-separated word.
_PERIOD_BUCKETS = (
    ("prev_week_", _week_bucket),
    ("prev_month_", _month_bucket),
    ("prev_quarter_", _quarter_bucket),
    ("prev_year_", _year_bucket),
)


@dataclass(slots=True)
class _Aggregate:
    high: float
    low: float
    close: float


class DailyLevelIndex:
    """Answers "what were the daily levels as of date D?".

    Built once per symbol load from the daily bar series, then queried for
    each distinct day present on the intraday chart — a handful of lookups,
    not one per bar.
    """

    def __init__(self, daily_bars: list[Bar], spans: set[LevelKey] | None = None):
        self._dates: list[date] = [ny_date(bar.time) for bar in daily_bars]
        self._closes = [bar.close for bar in daily_bars]
        self._highs = [bar.high for bar in daily_bars]
        self._lows = [bar.low for bar in daily_bars]
        self._rolling: dict[LevelKey, list[Number]] = {}
        self._build_rolling(spans or set())
        self._periods = {
            prefix: self._build_period(bucket_of) for prefix, bucket_of in _PERIOD_BUCKETS
        }

    def _build_rolling(self, keys: set[LevelKey]) -> None:
        for key in keys:
            if key.kind not in SPAN_KINDS or key.span <= 0:
                continue
            if key.kind == "sma":
                self._rolling[key] = sma(self._closes, key.span)
            elif key.kind == "ema":
                self._rolling[key] = ema(self._closes, key.span)
            elif key.kind == "high":
                self._rolling[key] = rolling_max(self._highs, key.span)
            elif key.kind == "low":
                self._rolling[key] = rolling_min(self._lows, key.span)

    def _build_period(self, bucket_of) -> dict[object, _Aggregate]:
        buckets: dict[object, _Aggregate] = {}
        for i, day in enumerate(self._dates):
            key = bucket_of(day)
            agg = buckets.get(key)
            if agg is None:
                buckets[key] = _Aggregate(self._highs[i], self._lows[i], self._closes[i])
            else:
                agg.high = max(agg.high, self._highs[i])
                agg.low = min(agg.low, self._lows[i])
                agg.close = self._closes[i]
        return buckets

    def _last_index_before(self, day: date) -> int:
        """Index of the newest daily bar that closed before ``day``."""
        lo, hi = 0, len(self._dates)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._dates[mid] < day:
                lo = mid + 1
            else:
                hi = mid
        return lo - 1

    def _previous_bucket(self, buckets: dict[object, _Aggregate], current) -> _Aggregate | None:
        earlier = [key for key in buckets if key < current]
        if not earlier:
            return None
        return buckets[max(earlier)]

    def value(self, key: LevelKey, day: date) -> Number:
        """The value of ``key`` in effect on ``day``."""
        if key.kind in SPAN_KINDS:
            index = self._last_index_before(day)
            if index < 0:
                return None
            series = self._rolling.get(key)
            return series[index] if series else None

        if key.kind.startswith("prev_day_"):
            index = self._last_index_before(day)
            if index < 0:
                return None
            field = key.kind.removeprefix("prev_day_")
            return {"high": self._highs, "low": self._lows, "close": self._closes}[field][index]

        for prefix, bucket_of in _PERIOD_BUCKETS:
            if not key.kind.startswith(prefix):
                continue
            agg = self._previous_bucket(self._periods[prefix], bucket_of(day))
            if agg is None:
                return None
            field = key.kind.split("_")[-1]
            return {"high": agg.high, "low": agg.low, "close": agg.close}[field]

        return None

    def values_for_days(
        self, keys: list[LevelKey], days: list[date]
    ) -> dict[LevelKey, dict[date, Number]]:
        return {key: {day: self.value(key, day) for day in days} for key in keys}


def parse_level_key(raw: str) -> LevelKey:
    """Parse ``"sma:20"`` / ``"prev_week_close"`` into a :class:`LevelKey`."""
    text = raw.strip().lower()
    if ":" in text:
        kind, _, span = text.partition(":")
        if kind not in SPAN_KINDS:
            raise ValueError(f"Unknown spanned level kind {kind!r}")
        if not span.isdigit() or int(span) <= 0:
            raise ValueError(f"Level {raw!r} needs a positive span")
        return LevelKey(kind, int(span))

    if text not in PERIOD_KINDS:
        raise ValueError(f"Unknown level {raw!r}")
    return LevelKey(text)
