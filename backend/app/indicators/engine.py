"""Turns bars plus indicator specs into the series the chart draws.

The engine recomputes a whole timeframe at once rather than updating
incrementally. Results are cached per (symbol, timeframe) in the market data
service and shared by every subscriber, so the cost is paid once per data
change regardless of how many clients are watching.
"""

from __future__ import annotations

from ..domain.bars import Bar
from ..domain.sessions import ny_date
from ..domain.timeframes import Timeframe
from .functions import (
    Number,
    compress_steps,
    ema,
    ema_last,
    macd,
    macd_last,
    premarket_bounds,
    premarket_bounds_last,
    EMPTY_SESSION_LEVELS,
    SessionLevels,
    session_level_series,
    session_bounds,
    session_bounds_last,
    session_vwap,
    session_vwap_last,
    sma,
    sma_last,
    to_series,
)
from .levels import DailyLevelIndex, LevelKey
from .spec import IndicatorSpec, IndicatorType

SeriesMap = dict[str, list[tuple[int, float]]]


class IndicatorEngine:
    def __init__(self, specs: list[IndicatorSpec]):
        self._specs = specs
        self._by_timeframe: dict[Timeframe, list[IndicatorSpec]] = {}
        for timeframe in Timeframe:
            self._by_timeframe[timeframe] = [
                spec for spec in specs if spec.applies_to(timeframe)
            ]

    @property
    def specs(self) -> list[IndicatorSpec]:
        return list(self._specs)

    def for_timeframe(self, timeframe: Timeframe) -> list[IndicatorSpec]:
        return list(self._by_timeframe.get(timeframe, []))

    def level_keys_for(self, timeframe: Timeframe) -> set[LevelKey]:
        """Every daily level the given timeframe draws."""
        return {
            spec.level_key
            for spec in self._by_timeframe.get(timeframe, [])
            if spec.type is IndicatorType.DAILY_LEVEL and spec.level_key
        }

    def all_level_keys(self) -> set[LevelKey]:
        return {
            spec.level_key
            for spec in self._specs
            if spec.type is IndicatorType.DAILY_LEVEL and spec.level_key
        }

    def compute(
        self,
        bars: list[Bar],
        timeframe: Timeframe,
        daily_bars: list[Bar] | None = None,
        level_index: DailyLevelIndex | None = None,
        session: SessionLevels = EMPTY_SESSION_LEVELS,
    ) -> SeriesMap:
        """Compute every series active for ``timeframe``.

        Key levels need daily data: pass either a prebuilt ``level_index`` or
        the ``daily_bars`` to build one from. With neither, key levels are
        skipped and the remaining indicators still compute.
        """
        series: SeriesMap = {}
        if not bars:
            return series

        active = [spec for spec in self._by_timeframe.get(timeframe, []) if spec.draws_series]
        if not active:
            return series

        closes = [bar.close for bar in bars]
        # Both of these walk every bar through a timezone conversion, so they
        # are computed at most once per call and shared across indicators.
        premarket_cache: tuple[list[Number], list[Number]] | None = None
        session_cache: tuple[list[Number], list[Number]] | None = None
        days_cache: list | None = None

        if level_index is None:
            level_keys = {
                spec.level_key
                for spec in active
                if spec.type is IndicatorType.DAILY_LEVEL and spec.level_key
            }
            if level_keys and daily_bars:
                level_index = DailyLevelIndex(daily_bars, level_keys)

        for spec in active:
            if spec.type is IndicatorType.EMA:
                span = spec.span_for(timeframe)
                if span:
                    series[spec.id] = to_series(bars, ema(closes, span))

            elif spec.type is IndicatorType.SMA:
                span = spec.span_for(timeframe)
                if span:
                    series[spec.id] = to_series(bars, sma(closes, span))

            elif spec.type is IndicatorType.VWAP:
                # A daily bar spans a whole session, so a session VWAP over
                # daily bars would just retrace the closes.
                if timeframe.is_intraday:
                    series[spec.id] = to_series(bars, session_vwap(bars))

            elif spec.type is IndicatorType.MACD:
                macd_line, signal_line, histogram = macd(
                    closes, spec.fast, spec.slow, spec.signal
                )
                series[spec.id] = to_series(bars, macd_line)
                series[f"{spec.id}_signal"] = to_series(bars, signal_line)
                series[f"{spec.id}_hist"] = to_series(bars, histogram)

            elif spec.type is IndicatorType.PREMARKET:
                if not timeframe.is_intraday:
                    continue
                if premarket_cache is None:
                    premarket_cache = premarket_bounds(bars)
                values = premarket_cache[0] if spec.bound == "high" else premarket_cache[1]
                series[spec.id] = compress_steps(
                    [(bar.time, value) for bar, value in zip(bars, values, strict=True)]
                )

            elif spec.type is IndicatorType.SESSION_BOUND:
                if not timeframe.is_intraday:
                    continue
                if session_cache is None:
                    session_cache = session_bounds(bars)
                values = session_cache[0] if spec.bound == "high" else session_cache[1]
                series[spec.id] = compress_steps(
                    [(bar.time, value) for bar, value in zip(bars, values, strict=True)]
                )

            elif spec.type is IndicatorType.SESSION_LEVEL:
                if not timeframe.is_intraday or not spec.level:
                    continue
                series[spec.id] = compress_steps(
                    [
                        (bar.time, value)
                        for bar, value in zip(
                            bars, session_level_series(bars, session.get(spec.level)), strict=True
                        )
                    ]
                )

            elif spec.type is IndicatorType.DAILY_LEVEL:
                if level_index is None or spec.level_key is None:
                    continue
                if days_cache is None:
                    days_cache = [ny_date(bar.time) for bar in bars]
                series[spec.id] = self._level_series(
                    bars, days_cache, level_index, spec.level_key
                )

        return {key: value for key, value in series.items() if value}

    @staticmethod
    def _level_series(
        bars: list[Bar],
        days: list,
        index: DailyLevelIndex,
        key: LevelKey,
    ) -> list[tuple[int, float]]:
        # One lookup per distinct day rather than per bar.
        per_day = {day: index.value(key, day) for day in set(days)}
        points = [(bar.time, per_day[day]) for bar, day in zip(bars, days, strict=True)]
        return compress_steps(points)

    def latest(
        self,
        bars: list[Bar],
        timeframe: Timeframe,
        level_index: DailyLevelIndex | None = None,
        session: SessionLevels = EMPTY_SESSION_LEVELS,
    ) -> dict[str, float]:
        """Just the current value of each indicator.

        Called once a second per subscribed chart, so it deliberately avoids
        building full series: key levels become a single lookup and the
        session-scoped indicators only walk back to the start of the day.
        """
        if not bars:
            return {}

        active = [spec for spec in self._by_timeframe.get(timeframe, []) if spec.draws_series]
        if not active:
            return {}

        closes = [bar.close for bar in bars]
        last_day = ny_date(bars[-1].time)
        premarket_cache: tuple[Number, Number] | None = None
        session_cache: tuple[Number, Number] | None = None
        values: dict[str, float] = {}

        for spec in active:
            value: Number = None

            if spec.type is IndicatorType.EMA:
                span = spec.span_for(timeframe)
                value = ema_last(closes, span) if span else None

            elif spec.type is IndicatorType.SMA:
                span = spec.span_for(timeframe)
                value = sma_last(closes, span) if span else None

            elif spec.type is IndicatorType.VWAP:
                if timeframe.is_intraday:
                    value = session_vwap_last(bars)

            elif spec.type is IndicatorType.MACD:
                macd_value, signal_value, hist_value = macd_last(
                    closes, spec.fast, spec.slow, spec.signal
                )
                if signal_value is not None:
                    values[f"{spec.id}_signal"] = signal_value
                if hist_value is not None:
                    values[f"{spec.id}_hist"] = hist_value
                value = macd_value

            elif spec.type is IndicatorType.PREMARKET:
                if timeframe.is_intraday:
                    if premarket_cache is None:
                        premarket_cache = premarket_bounds_last(bars)
                    value = premarket_cache[0] if spec.bound == "high" else premarket_cache[1]

            elif spec.type is IndicatorType.SESSION_BOUND:
                if timeframe.is_intraday:
                    if session_cache is None:
                        session_cache = session_bounds_last(bars)
                    value = session_cache[0] if spec.bound == "high" else session_cache[1]

            elif spec.type is IndicatorType.SESSION_LEVEL:
                if timeframe.is_intraday and spec.level:
                    level = session.get(spec.level)
                    if level.known_from is not None and bars and bars[-1].time >= level.known_from:
                        value = level.value

            elif spec.type is IndicatorType.DAILY_LEVEL:
                if level_index is not None and spec.level_key is not None:
                    value = level_index.value(spec.level_key, last_day)

            if value is not None:
                values[spec.id] = value

        return values


def latest_values(series: SeriesMap) -> dict[str, float]:
    """The current value of each already-computed series."""
    return {key: points[-1][1] for key, points in series.items() if points}
