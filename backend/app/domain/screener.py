"""TradingView reference-data domain types.

Two things TradingView supplies that no brokerage feed here does: the
market-regime counts, and the per-symbol reference numbers — float and market
cap — that IBKR withholds without a fundamentals entitlement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class MarketRegime:
    """Cross-sectional temperature: how many names are running today.

    Zero stocks up 100%+ is itself a signal that the tape is cold.
    """

    up_50_count: int = 0
    up_100_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class RegimeState:
    regime: MarketRegime = field(default_factory=MarketRegime)
    running: bool = False
    error: str | None = None


@dataclass(slots=True)
class SymbolStats:
    """Reference numbers for one symbol, straight from TradingView."""

    symbol: str
    description: str = ""
    exchange: str = ""
    sector: str = ""
    float_shares: float | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    avg_vol_10d: float | None = None
    premarket_volume: float | None = None
    premarket_change: float | None = None
    fetched_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)
