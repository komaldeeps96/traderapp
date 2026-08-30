"""TradingView reference-data domain types.

Two things TradingView supplies that no brokerage feed here does: the
market-regime counts, and the per-symbol reference numbers — float and market
cap — that IBKR withholds without a fundamentals entitlement.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field


def finite(value: object) -> float | None:
    """A real number, or nothing at all.

    Every screener row arrives through pandas, which fills a missing cell
    with NaN — and `isinstance(nan, float)` is True, so a plain type check
    lets it straight through. NaN then poisons whatever it touches, and
    silently: every comparison against it is False, so a row carrying one
    passes a filter *because* it failed the test, and sorting a list with a
    few in it puts everything in an arbitrary order.

    That is not hypothetical. It ranked Apple first of thirty-one on
    price-to-book, at 43x against a peer median of 2x, because three peers
    reported no book value.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


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
    # Split-adjusted; after a heavy reverse split this can sit absurdly far
    # above price, which is itself information about the chart's history.
    all_time_high: float | None = None

    # ── the slow half ──────────────────────────────────────────────────
    #
    # Ratios and statements, for the fundamentals panel's lower section.
    # Deliberately separate from the fields above: those decide whether a
    # trade is possible at all — float, rotation, the all-time high — and
    # these never do. A P/E ratio has stopped no trade in this workflow.
    # They ride the same single query, so they cost nothing to carry.
    industry: str = ""
    country: str = ""
    employees: float | None = None
    price_earnings: float | None = None
    eps_ttm: float | None = None
    revenue_ttm: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_income: float | None = None
    total_debt: float | None = None
    total_cash: float | None = None
    free_cash_flow: float | None = None
    ebitda: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    enterprise_value: float | None = None
    return_on_equity: float | None = None
    price_to_book: float | None = None
    price_to_sales: float | None = None
    beta: float | None = None
    perf_ytd: float | None = None
    # Epoch seconds of the next scheduled report — a date to avoid, or to
    # trade, but never to be surprised by.
    earnings_next: float | None = None

    fetched_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)
