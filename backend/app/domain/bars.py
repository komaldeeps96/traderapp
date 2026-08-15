"""The OHLCV bar.

A plain slotted dataclass rather than a Pydantic model: bars are created in
the tens of thousands per symbol load and are internal to the backend.
Validation happens at the provider boundary, serialisation at the API edge.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(slots=True)
class Bar:
    """One OHLCV bar. ``time`` is the UTC epoch second the period opened."""

    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    trades: float = 0.0

    def merged_with(self, other: "Bar") -> "Bar":
        """Fold a later bar covering the same period into this one."""
        return Bar(
            time=self.time,
            open=self.open,
            high=max(self.high, other.high),
            low=min(self.low, other.low),
            close=other.close,
            volume=self.volume + other.volume,
            trades=self.trades + other.trades,
        )

    def with_time(self, time: int) -> "Bar":
        return replace(self, time=time)

    def to_wire(self) -> dict[str, float]:
        """Short keys mirroring Alpaca's own bar shape, with epoch seconds."""
        return {
            "t": self.time,
            "o": self.open,
            "h": self.high,
            "l": self.low,
            "c": self.close,
            "v": self.volume,
            "n": self.trades,
        }

    @classmethod
    def from_wire(cls, data: dict) -> "Bar":
        return cls(
            time=int(data["t"]),
            open=float(data["o"]),
            high=float(data["h"]),
            low=float(data["l"]),
            close=float(data["c"]),
            volume=float(data.get("v", 0.0)),
            trades=float(data.get("n", 0.0)),
        )


def merge_bars(primary: list[Bar], secondary: list[Bar]) -> list[Bar]:
    """Combine two bar series into one sorted, de-duplicated series.

    Where both cover the same timestamp ``primary`` wins outright — it is not
    averaged or summed. This is how a bar derived from the IBKR base replaces
    the Alpaca bar for the same minute rather than double-counting its volume.
    """
    by_time: dict[int, Bar] = {bar.time: bar for bar in secondary}
    by_time.update({bar.time: bar for bar in primary})
    return [by_time[t] for t in sorted(by_time)]
