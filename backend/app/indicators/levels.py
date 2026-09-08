"""Daily key levels projected onto an intraday chart.

All levels for a given day are derived from daily bars that closed *strictly
before* that day. That rule is what keeps them stable: a "prev day close" or a
"52-week high" drawn on today's 1-minute chart must not move as today trades,
otherwise the level repaints under the trader.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import deque
from dataclasses import dataclass
from datetime import date, timedelta

from ..domain.bars import Bar
from ..domain.sessions import ny_date
from .functions import Number, ema, rolling_max, rolling_min, sma


@dataclass(frozen=True, slots=True)
class LevelKey:
    """Identifies one daily level, e.g. ``sma`` over 20 bars.

    ``weeks`` switches the span from a count of bars to a span of calendar
    time. A moving average is a bar count by nature — twenty closes averaged
    — but a "52-week high" is a claim about the calendar, and 252 bars is
    only an approximation of it. The two disagree at the edge, which is
    exactly where a yearly extreme tends to sit.
    """

    kind: str
    span: int = 0
    weeks: bool = False

    def __str__(self) -> str:
        if not self.span:
            return self.kind
        return f"{self.kind}:{self.span}{'w' if self.weeks else ''}"


# Level kinds that take a span.
SPAN_KINDS = frozenset({"sma", "ema", "high", "low"})
# Of those, the ones a calendar span makes sense for. Averaging "the last
# 52 weeks of closes" is a different and stranger thing than the highest
# price in that time, so the suffix is only allowed where it means something.
CALENDAR_KINDS = frozenset({"high", "low"})
# Level kinds derived from the *current* calendar period rather than a
# completed one. Still bounded by the previous close, so it does not repaint:
# a year-to-date high is the highest price this year up to yesterday.
CURRENT_KINDS = frozenset({"ytd_high"})
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


# Every kind that names a period instead of taking a span.
BARE_KINDS = PERIOD_KINDS | CURRENT_KINDS


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
        self._index_cache: dict[date, int] = {}
        self._build_rolling(spans or set())
        self._periods = {
            prefix: self._build_period(bucket_of) for prefix, bucket_of in _PERIOD_BUCKETS
        }
        self._ytd_high = _running_year_max(self._highs, self._dates)
        # Sorted once so `_previous_bucket` can bisect instead of scan.
        self._period_keys = {prefix: sorted(buckets) for prefix, buckets in self._periods.items()}

    def _build_rolling(self, keys: set[LevelKey]) -> None:
        for key in keys:
            if key.kind not in SPAN_KINDS or key.span <= 0:
                continue
            if key.kind == "sma":
                self._rolling[key] = sma(self._closes, key.span)
            elif key.kind == "ema":
                self._rolling[key] = ema(self._closes, key.span)
            elif key.kind == "high":
                self._rolling[key] = self._extreme(self._highs, key, highest=True)
            elif key.kind == "low":
                self._rolling[key] = self._extreme(self._lows, key, highest=False)

    def _extreme(self, values: list[float], key: LevelKey, *, highest: bool) -> list[Number]:
        if not key.weeks:
            return rolling_max(values, key.span) if highest else rolling_min(values, key.span)
        return _calendar_extreme(values, self._dates, key.span, highest=highest)

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
        """Index of the newest daily bar that closed before ``day``.

        Memoised because the answer depends only on the day, while every
        span and prev-day level asks it again for the same day — some thirty
        identical binary searches per bar on a daily chart. The index is
        rebuilt whenever the daily bars change, so the cache cannot go stale.
        """
        hit = self._index_cache.get(day)
        if hit is not None:
            return hit
        lo, hi = 0, len(self._dates)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._dates[mid] < day:
                lo = mid + 1
            else:
                hi = mid
        self._index_cache[day] = lo - 1
        return lo - 1

    def _previous_bucket(self, prefix: str, current) -> _Aggregate | None:
        """The newest completed bucket strictly before ``current``.

        This looked like a handful of calls when levels only ever landed on
        intraday charts, where 2,000 bars span a week of distinct days. On a
        daily chart every bar is its own day, so it runs once per bar per
        level, and scanning every bucket made the snapshot quadratic in the
        length of history.
        """
        keys = self._period_keys[prefix]
        position = bisect_left(keys, current)
        if position == 0:
            return None
        return self._periods[prefix][keys[position - 1]]

    # One return per level family. A lookup table would collapse them into a
    # single expression and hide which family answered.
    def value(self, key: LevelKey, day: date) -> Number:  # noqa: PLR0911
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

        if key.kind == "ytd_high":
            index = self._last_index_before(day)
            # In the first days of January the newest completed bar belongs
            # to last year, and its running max is last year's high — a
            # different level, and one already drawn as Prev Year High.
            if index < 0 or self._dates[index].year != day.year:
                return None
            return self._ytd_high[index]

        for prefix, bucket_of in _PERIOD_BUCKETS:
            if not key.kind.startswith(prefix):
                continue
            agg = self._previous_bucket(prefix, bucket_of(day))
            if agg is None:
                return None
            field = key.kind.split("_")[-1]
            return {"high": agg.high, "low": agg.low, "close": agg.close}[field]

        return None


def parse_level_key(raw: str) -> LevelKey:
    """Parse ``"sma:20"``, ``"high:52w"`` or ``"prev_week_close"``.

    A bare number is a count of bars; a ``w`` suffix is calendar weeks.
    """
    text = raw.strip().lower()
    if ":" in text:
        kind, _, span = text.partition(":")
        if kind not in SPAN_KINDS:
            raise ValueError(f"Unknown spanned level kind {kind!r}")
        weeks = span.endswith("w")
        if weeks:
            span = span[:-1]
            if kind not in CALENDAR_KINDS:
                raise ValueError(f"Level {raw!r} cannot span calendar weeks")
        if not span.isdigit() or int(span) <= 0:
            raise ValueError(f"Level {raw!r} needs a positive span")
        return LevelKey(kind, int(span), weeks=weeks)

    if text not in BARE_KINDS:
        raise ValueError(f"Unknown level {raw!r}")
    return LevelKey(text)


def _running_year_max(values: list[float], dates: list[date]) -> list[float]:
    """The highest value so far in each bar's own calendar year.

    Reset on 1 January rather than rolled over a window: unlike the 52-week
    high beside it, this level is anchored, so it only moves when the year
    makes a new high. Early in the year the two sit far apart and by December
    they nearly agree, and that gap is how much of the yearly range this
    year's move accounts for.
    """
    out: list[float] = []
    year: int | None = None
    best = 0.0
    for value, day in zip(values, dates, strict=True):
        best = value if day.year != year else max(best, value)
        year = day.year
        out.append(best)
    return out


def _calendar_extreme(
    values: list[float], dates: list[date], weeks: int, *, highest: bool
) -> list[Number]:
    """The extreme over a span of calendar time rather than a count of bars.

    A monotonic deque, so this stays linear over the forty years of daily
    history the terminal loads.

    The window is open at the far end: a bar exactly `weeks` old has fallen
    out. That is what makes this differ from the bar count it replaces —
    Celularity's high was dated 366 days back, inside a 252-bar window and
    outside a 52-week one, and the label says weeks.

    **Not weekly resampling**, which is the obvious alternative and is wrong
    for a level. Fifty-two weekly bars span 357 days on a Monday and 361 on a
    Friday, because the newest bar is a partial week — so an old extreme
    expires up to a week early and the level drops in Monday steps rather
    than decaying by the day. Measured on Celularity: for four consecutive
    days in August 2026 the weekly method read 3.1539 while the highest print
    of the preceding fifty-two weeks was still 4.0098.

    The two answer different questions. "The highest of the last 52 weekly
    candles" is what a weekly chart shows; "the highest price in the last 52
    weeks" is what a level labelled 52W means, and it is this one.
    """
    window = timedelta(weeks=weeks)
    out: list[Number] = []
    inside: deque[int] = deque()
    for index, day in enumerate(dates):
        while inside and (
            values[inside[-1]] <= values[index] if highest else values[inside[-1]] >= values[index]
        ):
            inside.pop()
        inside.append(index)
        cutoff = day - window
        while inside and dates[inside[0]] <= cutoff:
            inside.popleft()
        out.append(values[inside[0]])
    return out
