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


def _ny_offset_seconds(epoch: float) -> int:
    """New York's UTC offset at ``epoch``, in seconds (negative, whole hours)."""
    return int(to_ny(epoch).utcoffset().total_seconds())  # type: ignore[union-attr]


def _ny_week_start_epoch(epoch: float) -> int:
    ny = to_ny(epoch)
    monday = ny.date() - timedelta(days=ny.weekday())
    return int(datetime(monday.year, monday.month, monday.day, tzinfo=NY_TZ).timestamp())


def bucket_start(epoch: float, timeframe: Timeframe) -> int:
    """The opening timestamp of the period ``epoch`` falls into.

    Every period aligns to the New York wall clock, which is the clock the
    session runs on. For a size that divides an hour that is the same thing
    as aligning to epoch boundaries — US offsets are whole hours — so those
    keep the integer division and the timezone lookup it saves, over the
    thousands of bars a resample walks.

    Four-hour bars are the case that needs the wall clock spelled out. Epoch
    boundaries would put them at 04:00 New York through the summer and 03:00
    through the winter, so the bar that opens the pre-market would move twice
    a year. Anchored to the local day they always run 00:00/04:00/08:00/
    12:00/16:00/20:00 — pre-market, the open, midday, the close, and the
    after-hours session, each in its own bar.

    Daily and weekly periods anchor to New York midnight for the same
    reason: a bar is never split across the 00:00 UTC boundary, which falls
    mid-after-hours.
    """
    if timeframe is Timeframe.D1:
        return _ny_midnight_epoch(epoch)
    if timeframe is Timeframe.W1:
        return _ny_week_start_epoch(epoch)
    size = timeframe.seconds
    if 3600 % size == 0:
        return int(epoch) // size * size
    offset = _ny_offset_seconds(epoch)
    local = int(epoch) + offset
    return local // size * size - offset


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
