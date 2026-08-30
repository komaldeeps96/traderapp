"""Ratios and valuation, derived from the statements.

Nothing here reads XBRL. It consumes what `financials.build_statements`
already resolved, so a concept chain or a derived quarter is fixed in one
place and every ratio built on it follows.

Two rules run through the whole file.

**A ratio is only as good as both its sides.** Every one is computed from the
same period on both numerator and denominator, and returns nothing at all if
either side is missing — a margin against a blank revenue is not a small
number, it is not a number.

**Division by a negative denominator is refused, not reported.** A price/
earnings on a loss, a debt/equity on negative book value, a coverage ratio on
negative operating income: each is arithmetically fine and financially
meaningless, and printing "-14.2x" invites it to be read as cheap.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .financials import build_statements

# Four quarters make a trailing year. Fewer than four is not a year, and
# annualising two quarters is a guess the terminal does not make.
TTM_QUARTERS = 4


@dataclass(frozen=True, slots=True)
class MetricSpec:
    key: str
    label: str
    # "percent", "ratio", "multiple" or "money" — how the frontend reads it.
    unit: str
    group: str


def _safe_divide(top: float | None, bottom: float | None, *, positive_only: bool) -> float | None:
    if top is None or bottom is None:
        return None
    if bottom == 0 or (positive_only and bottom < 0):
        return None
    return top / bottom


def _growth(series: Sequence[float | None], index: int) -> float | None:
    """Change against the same period a year earlier.

    Periods run newest first, so the comparison is the *next* entry along.
    Growth from a negative base is refused: revenue rising from -2 to 1 is
    not "150% growth", it is a sign change.
    """
    if index + 1 >= len(series):
        return None
    now, before = series[index], series[index + 1]
    if now is None or before is None or before <= 0:
        return None
    return (now - before) / before


PROFITABILITY: tuple[MetricSpec, ...] = (
    MetricSpec("gross_margin", "Gross margin", "percent", "Profitability"),
    MetricSpec("operating_margin", "Operating margin", "percent", "Profitability"),
    MetricSpec("net_margin", "Net margin", "percent", "Profitability"),
    MetricSpec("return_on_equity", "Return on equity", "percent", "Profitability"),
    MetricSpec("return_on_assets", "Return on assets", "percent", "Profitability"),
)

GROWTH: tuple[MetricSpec, ...] = (
    MetricSpec("revenue_growth", "Revenue growth", "percent", "Growth"),
    MetricSpec("net_income_growth", "Net income growth", "percent", "Growth"),
    MetricSpec("operating_income_growth", "Operating income growth", "percent", "Growth"),
)

BALANCE: tuple[MetricSpec, ...] = (
    MetricSpec("current_ratio", "Current ratio", "ratio", "Balance sheet"),
    MetricSpec("debt_to_equity", "Debt / equity", "ratio", "Balance sheet"),
    MetricSpec("interest_coverage", "Interest coverage", "multiple", "Balance sheet"),
    MetricSpec("net_cash", "Net cash", "money", "Balance sheet"),
)

CASH: tuple[MetricSpec, ...] = (
    MetricSpec("free_cash_flow", "Free cash flow", "money", "Cash"),
    MetricSpec("fcf_margin", "FCF margin", "percent", "Cash"),
    MetricSpec("capex_intensity", "Capex / revenue", "percent", "Cash"),
)

METRIC_GROUPS: tuple[tuple[str, tuple[MetricSpec, ...]], ...] = (
    ("Profitability", PROFITABILITY),
    ("Growth", GROWTH),
    ("Balance sheet", BALANCE),
    ("Cash", CASH),
)


def _per_period(values: dict[str, list[float | None]], count: int) -> dict[str, list[float | None]]:
    """Every ratio, one list per key, aligned with the period axis."""

    def col(key: str, index: int) -> float | None:
        series = values.get(key)
        return series[index] if series and index < len(series) else None

    out: dict[str, list[float | None]] = {}
    for index in range(count):
        revenue = col("revenue", index)
        operating = col("operating_income", index)
        capex = col("capex", index)
        cash_flow = col("operating_cash_flow", index)
        cash = col("cash", index)
        debt = col("long_term_debt", index)
        free_cash = None if cash_flow is None or capex is None else cash_flow - capex

        computed: dict[str, float | None] = {
            "gross_margin": _safe_divide(col("gross_profit", index), revenue, positive_only=True),
            "operating_margin": _safe_divide(operating, revenue, positive_only=True),
            "net_margin": _safe_divide(col("net_income", index), revenue, positive_only=True),
            "return_on_equity": _safe_divide(
                col("net_income", index), col("equity", index), positive_only=True
            ),
            "return_on_assets": _safe_divide(
                col("net_income", index), col("total_assets", index), positive_only=True
            ),
            "revenue_growth": _growth(values.get("revenue", []), index),
            "net_income_growth": _growth(values.get("net_income", []), index),
            "operating_income_growth": _growth(values.get("operating_income", []), index),
            "current_ratio": _safe_divide(
                col("current_assets", index), col("current_liabilities", index), positive_only=True
            ),
            "debt_to_equity": _safe_divide(debt, col("equity", index), positive_only=True),
            "interest_coverage": _safe_divide(
                operating, col("interest_expense", index), positive_only=True
            ),
            "net_cash": None if cash is None else cash - (debt or 0.0),
            "free_cash_flow": free_cash,
            "fcf_margin": _safe_divide(free_cash, revenue, positive_only=True),
            "capex_intensity": _safe_divide(capex, revenue, positive_only=True),
        }
        for key, value in computed.items():
            out.setdefault(key, []).append(value)
    return out


def _trailing(values: dict[str, list[float | None]], key: str, annual: bool) -> float | None:
    """A year of a flow: the latest year, or the last four quarters.

    Three quarters and a gap is not a year, so a missing quarter refuses the
    whole figure rather than quietly understating it — which on a valuation
    multiple would read as *cheaper* than the company is.
    """
    series = values.get(key) or []
    if not series:
        return None
    if annual:
        return series[0]
    if len(series) < TTM_QUARTERS:
        return None
    window = series[:TTM_QUARTERS]
    return None if any(value is None for value in window) else sum(window)  # type: ignore[arg-type]


def build_metrics(
    facts: dict | None,
    annual: bool,
    limit: int = 8,
    market_cap: float | None = None,
) -> dict:
    """Ratios per period, plus valuation against the current market cap."""
    statements = build_statements(facts, annual=annual, limit=limit)
    values: dict[str, list[float | None]] = {
        line["key"]: line["values"]
        for statement in statements["statements"]
        for line in statement["lines"]
    }
    periods = statements["periods"]
    rows = _per_period(values, len(periods))

    return {
        "periods": periods,
        "groups": [
            {
                "label": label,
                "metrics": [
                    {
                        "key": spec.key,
                        "label": spec.label,
                        "unit": spec.unit,
                        "values": [
                            None if value is None else round(value, 6)
                            for value in rows.get(spec.key, [])
                        ],
                    }
                    for spec in specs
                    if any(value is not None for value in rows.get(spec.key, []))
                ],
            }
            for label, specs in METRIC_GROUPS
            if any(any(value is not None for value in rows.get(s.key, [])) for s in specs)
        ],
        "valuation": _valuation(values, annual=annual, market_cap=market_cap),
    }


def _valuation(
    values: dict[str, list[float | None]], *, annual: bool, market_cap: float | None
) -> dict:
    """Multiples against what the market is asking today.

    Market cap comes from the quote side rather than the filings: a book
    value is as of a quarter end, and dividing today's price by a figure
    three months stale is the whole point of the exercise.
    """
    revenue = _trailing(values, "revenue", annual)
    earnings = _trailing(values, "net_income", annual)
    cash_flow = _trailing(values, "operating_cash_flow", annual)
    capex = _trailing(values, "capex", annual)
    free_cash = None if cash_flow is None or capex is None else cash_flow - capex

    equity = (values.get("equity") or [None])[0]
    cash = (values.get("cash") or [None])[0]
    debt = (values.get("long_term_debt") or [None])[0]
    enterprise = None if market_cap is None else market_cap + (debt or 0.0) - (cash or 0.0)

    return {
        "market_cap": market_cap,
        "enterprise_value": enterprise,
        "basis": "annual" if annual else "trailing twelve months",
        "multiples": [
            {
                "key": "pe",
                "label": "P/E",
                "value": _safe_divide(market_cap, earnings, positive_only=True),
            },
            {
                "key": "ps",
                "label": "P/S",
                "value": _safe_divide(market_cap, revenue, positive_only=True),
            },
            {
                "key": "pb",
                "label": "P/B",
                "value": _safe_divide(market_cap, equity, positive_only=True),
            },
            {
                "key": "p_fcf",
                "label": "P/FCF",
                "value": _safe_divide(market_cap, free_cash, positive_only=True),
            },
            {
                "key": "ev_sales",
                "label": "EV/Sales",
                "value": _safe_divide(enterprise, revenue, positive_only=True),
            },
        ],
    }
