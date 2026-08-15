"""Deriving higher timeframes from base bars.

Only ``10s``, ``1m`` and ``1d`` are fetched upstream. Every other timeframe
is folded out of one of those here, which keeps the provider layer small and
makes each derived timeframe a pure function that can be tested against
hand-built bars.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..core.clock import NY_TZ, to_ny
from ..domain.bars import Bar
from ..domain.timeframes import Timeframe


def _ny_midnight_epoch(epoch: float) -> int:
    ny = to_ny(epoch)
    return int(datetime(ny.year, ny.month, ny.day, tzinfo=NY_TZ).timestamp())


def _ny_week_start_epoch(epoch: float) -> int:
    ny = to_ny(epoch)
    monday = ny.date() - timedelta(days=ny.weekday())
    return int(datetime(monday.year, monday.month, monday.day, tzinfo=NY_TZ).timestamp())


def bucket_start(epoch: float, timeframe: Timeframe) -> int:
    """The opening timestamp of the period ``epoch`` falls into.

    Intraday periods align to epoch boundaries, which lines up with New York
    wall-clock minutes and hours because US market offsets are whole hours.
    Daily and weekly periods align to New York midnight instead, so a bar is
    never split across the 00:00 UTC boundary that falls mid-after-hours.
    """
    if timeframe is Timeframe.D1:
        return _ny_midnight_epoch(epoch)
    if timeframe is Timeframe.W1:
        return _ny_week_start_epoch(epoch)
    size = timeframe.seconds
    return int(epoch) // size * size


def resample(bars: list[Bar], target: Timeframe) -> list[Bar]:
    """Fold ``bars`` up into ``target`` periods.

    Input must be sorted ascending; open comes from the first bar of a period
    and close from the last, so ordering is load-bearing.
    """
    if not bars:
        return []

    buckets: dict[int, Bar] = {}
    for bar in bars:
        start = bucket_start(bar.time, target)
        existing = buckets.get(start)
        if existing is None:
            buckets[start] = Bar(
                time=start,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                trades=bar.trades,
            )
        else:
            existing.high = max(existing.high, bar.high)
            existing.low = min(existing.low, bar.low)
            existing.close = bar.close
            existing.volume += bar.volume
            existing.trades += bar.trades

    return [buckets[start] for start in sorted(buckets)]


def derive(base_bars: list[Bar], target: Timeframe) -> list[Bar]:
    """Return ``target`` bars, resampling only when it is not a base timeframe."""
    if target.is_base:
        return list(base_bars)
    return resample(base_bars, target)
