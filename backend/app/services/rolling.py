"""A rolling comparison against "a window ago".

Both scanner signals — rank velocity and trade-rate acceleration — measure
now against then, and the "then" is the fiddly part. Keeping it in one place
means the discipline is written once and tested once.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class WindowedHistory(Generic[T]):
    """Snapshots of some per-symbol state, with a baseline a window back."""

    def __init__(self, window_seconds: float, *, clock: Callable[[], float]) -> None:
        self._window = window_seconds
        self._clock = clock
        self._snapshots: deque[tuple[float, T]] = deque()

    def clear(self) -> None:
        self._snapshots.clear()

    def push(self, payload: T) -> T | None:
        """Record the present, and return the state a window ago.

        ``None`` while the window is still filling — no baseline, no claim.
        """
        now = self._clock()
        cutoff = now - self._window

        # Keep exactly one snapshot at or before the cutoff. Dropping every
        # expired snapshot instead would leave the youngest survivor as the
        # baseline, silently shrinking the window to the sampling interval
        # and turning the measurement into noise.
        while len(self._snapshots) >= 2 and self._snapshots[1][0] <= cutoff:
            self._snapshots.popleft()

        baseline = (
            self._snapshots[0][1]
            if self._snapshots and self._snapshots[0][0] <= cutoff
            else None
        )
        self._snapshots.append((now, payload))
        return baseline
