"""In-memory bar storage, keyed by symbol and base timeframe.

Only base timeframes (``1m`` and ``1d``) are stored. Derived timeframes are
resampled on demand so there is exactly one copy of the truth per symbol and
no chance of two timeframes drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.bars import Bar, merge_bars
from ..domain.timeframes import Timeframe

Key = tuple[str, Timeframe]


@dataclass
class SymbolData:
    bars: dict[Timeframe, list[Bar]] = field(default_factory=dict)
    loaded_at: float = 0.0


class BarStore:
    def __init__(self, max_bars: int = 20_000):
        self._max_bars = max_bars
        self._data: dict[str, SymbolData] = {}

    # ── reads ──────────────────────────────────────────────────────────

    def get(self, symbol: str, timeframe: Timeframe) -> list[Bar]:
        """Bars for a base timeframe. Returns the live list, not a copy."""
        entry = self._data.get(symbol)
        if entry is None:
            return []
        return entry.bars.get(timeframe, [])

    def has(self, symbol: str, timeframe: Timeframe) -> bool:
        return bool(self.get(symbol, timeframe))

    @property
    def symbols(self) -> list[str]:
        return list(self._data)

    def loaded_at(self, symbol: str) -> float:
        entry = self._data.get(symbol)
        return entry.loaded_at if entry else 0.0

    # ── writes ─────────────────────────────────────────────────────────

    def replace(self, symbol: str, timeframe: Timeframe, bars: list[Bar], *, loaded_at: float = 0.0) -> None:
        entry = self._data.setdefault(symbol, SymbolData())
        entry.bars[timeframe] = self._trim(sorted(bars, key=lambda bar: bar.time))
        if loaded_at:
            entry.loaded_at = loaded_at

    def merge(self, symbol: str, timeframe: Timeframe, incoming: list[Bar]) -> None:
        """Merge bars in, with ``incoming`` winning on duplicate timestamps."""
        existing = self.get(symbol, timeframe)
        merged = merge_bars(incoming, existing) if existing else sorted(incoming, key=lambda b: b.time)
        entry = self._data.setdefault(symbol, SymbolData())
        entry.bars[timeframe] = self._trim(merged)

    def upsert(self, symbol: str, timeframe: Timeframe, bar: Bar) -> bool:
        """Append or replace a single bar. Returns True when it is new.

        The common case — an update to the newest bar — is O(1).
        """
        entry = self._data.setdefault(symbol, SymbolData())
        bars = entry.bars.setdefault(timeframe, [])

        if not bars or bar.time > bars[-1].time:
            bars.append(bar)
            if len(bars) > self._max_bars:
                del bars[: len(bars) - self._max_bars]
            return True

        if bar.time == bars[-1].time:
            bars[-1] = bar
            return False

        # Late arrival for an older period: locate and replace, or insert.
        lo, hi = 0, len(bars)
        while lo < hi:
            mid = (lo + hi) // 2
            if bars[mid].time < bar.time:
                lo = mid + 1
            else:
                hi = mid
        if lo < len(bars) and bars[lo].time == bar.time:
            bars[lo] = bar
            return False
        bars.insert(lo, bar)
        return True

    def clear(self, symbol: str) -> None:
        self._data.pop(symbol, None)

    def clear_all(self) -> None:
        self._data.clear()

    def _trim(self, bars: list[Bar]) -> list[Bar]:
        return bars[-self._max_bars :] if len(bars) > self._max_bars else bars
