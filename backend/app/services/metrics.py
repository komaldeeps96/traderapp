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
    MetricSpec("debt_to_equity", "Long-term debt / equity", "ratio", "Balance sheet"),
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
        # Long-term debt only, and the label says so. Summing this with the
        # short-term line to reach "total debt" was tried and measured worse:
        # `LongTermDebt` already includes the current portion for some filers
        # and `LongTermDebtNoncurrent` does not, so adding double-counts
        # Apple (1.23 against a quoted 0.78) while still understating
        # Microsoft. Reconciling the two needs work this has not had.
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


def _line_values(statements: dict | None) -> dict[str, list[float | None]]:
    if not statements:
        return {}
    return {
        line["key"]: line["values"]
        for statement in statements["statements"]
        for line in statement["lines"]
    }


def build_metrics(
    facts: dict | None,
    annual: bool,
    limit: int = 8,
    market_cap: float | None = None,
    statements: dict | None = None,
    trailing: dict | None = None,
) -> dict:
    """Ratios per period, plus valuation against the current market cap.

    A caller that has already built and converted the statements passes them
    in, so a foreign filer is not parsed twice and — more to the point — is
    not converted twice.

    `trailing` is the *quarterly* set, and it is what the multiples are built
    from whenever it is complete enough. Every other screen quotes a trailing
    twelve months, and a fiscal-year P/E disagrees with all of them: Apple's
    was 41.65 against the 36.65 the market was quoting, and Crocs' operating
    margin read 3.70% on a fiscal year carrying a goodwill impairment against
    24.22% on the twelve months actually behind it.
    """
    if statements is None:
        statements = build_statements(facts, annual=annual, limit=limit)
    currency = statements.get("currency", "USD")
    values = _line_values(statements)
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
        "currency": currency,
        "symbol_prefix": statements.get("symbol_prefix", "$"),
        "valuation": _valuation_on_best_basis(
            values, trailing, annual=annual, market_cap=market_cap, currency=currency
        ),
    }


def _valuation_on_best_basis(
    own_values: dict[str, list[float | None]],
    trailing: dict | None,
    *,
    annual: bool,
    market_cap: float | None,
    currency: str,
) -> dict:
    """Multiples on a trailing twelve months where the quarters allow it.

    They do not always: a foreign private issuer files no 10-Q, so there are
    no quarters to trail and the fiscal year is the only basis there is. The
    strip says which was used rather than leaving it to be inferred.

    With no quarterly set supplied at all, the caller's own basis stands — a
    caller asking for quarterly figures and getting an annual valuation would
    be a surprise, not a default.
    """
    trailing_values = _line_values(trailing)
    if trailing_values and _trailing(trailing_values, "revenue", annual=False) is not None:
        return _valuation(trailing_values, annual=False, market_cap=market_cap, currency=currency)
    return _valuation(own_values, annual=annual, market_cap=market_cap, currency=currency)


def _valuation(
    values: dict[str, list[float | None]],
    *,
    annual: bool,
    market_cap: float | None,
    currency: str = "USD",
) -> dict:
    """Multiples against what the market is asking today.

    Market cap comes from the quote side rather than the filings: a book
    value is as of a quarter end, and dividing today's price by a figure
    three months stale is the whole point of the exercise.

    That is also why a foreign private issuer gets no multiples. Market cap
    for a US listing is quoted in USD while the statements behind it are in
    the filer's own currency, so every multiple would be wrong by the
    exchange rate — and wrong quietly, since a P/E of 12 where the truth is
    17 looks like nothing at all. Converting needs an FX rate the terminal
    does not have, so it declines and says why.
    """
    mismatched = currency != "USD" and market_cap is not None
    revenue = _trailing(values, "revenue", annual)
    earnings = _trailing(values, "net_income", annual)
    cash_flow = _trailing(values, "operating_cash_flow", annual)
    capex = _trailing(values, "capex", annual)
    free_cash = None if cash_flow is None or capex is None else cash_flow - capex

    equity = (values.get("equity") or [None])[0]
    cash = (values.get("cash") or [None])[0]
    debt = (values.get("long_term_debt") or [None])[0]
    enterprise = None if market_cap is None else market_cap + (debt or 0.0) - (cash or 0.0)

    if mismatched:
        return {
            "market_cap": market_cap,
            "enterprise_value": None,
            "basis": "annual" if annual else "trailing twelve months",
            "note": (
                f"Statements are in {currency} and the market cap is in USD; "
                "multiples would be wrong by the exchange rate."
            ),
            "multiples": [
                {"key": key, "label": label, "value": None}
                for key, label in (
                    ("pe", "P/E"),
                    ("ps", "P/S"),
                    ("pb", "P/B"),
                    ("p_fcf", "P/FCF"),
                    ("ev_sales", "EV/Sales"),
                )
            ],
        }

    return {
        "market_cap": market_cap,
        "enterprise_value": enterprise,
        "basis": "annual" if annual else "trailing twelve months",
        "note": None,
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
