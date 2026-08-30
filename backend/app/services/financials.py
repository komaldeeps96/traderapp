"""Financial statements, built from EDGAR ``companyfacts``.

Three traps shape this module, and all three were found by reading real
filings rather than reasoning about the schema:

**``fy`` and ``fp`` describe the filing, not the fact.** Apple's FY2016
revenue appears carrying ``fy: 2018, fp: FY`` because the FY2018 10-K
restated it as a comparative. Keying on those fields silently files six
years of history under one year. A fact's period is ``start``–``end``, and
nothing else.

**Cumulative facts share the shape of quarterly ones.** A 10-Q reports the
quarter *and* the year to date, so a single concept carries 3-, 6-, 9- and
12-month durations in one list. Taking them all makes a quarterly series
that triples every autumn. Only the duration in days separates them.

**Concepts fragment mid-history.** ASC 606 stopped Apple's ``Revenues`` in
2018 and continued it under ``RevenueFromContractWithCustomerExcludingAssessedTax``.
Picking the first concept that returns anything gives a series that ends in
2018; the chains below are merged period by period instead, with earlier
entries winning where both report.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

# A duration this long is a year, this short is a quarter, and anything
# between the two is a year-to-date cumulative that must not enter a series.
ANNUAL_DAYS = (340, 400)
QUARTER_DAYS = (80, 100)

# Fiscal calendars are counted in weeks, so a "quarter to end-April" can close
# on 3 May and a fiscal year on 27 September. Reading the month off the end
# date directly puts those in the wrong quarter, so it is read a fortnight
# earlier, which lands every drifting close back inside its own month.
_MONTH_ANCHOR = timedelta(days=15)

Chain = tuple[tuple[str, str], ...]


def _us(*concepts: str) -> Chain:
    return tuple(("us-gaap", concept) for concept in concepts)


@dataclass(frozen=True, slots=True)
class LineSpec:
    key: str
    label: str
    concepts: Chain
    unit: str = "USD"
    # A balance is reported at an instant; everything else spans a period.
    instant: bool = False
    # Whether the quarters of a year sum to the year. True of every flow —
    # revenue, expenses, cash moved. False of a weighted average or a ratio,
    # which is why share counts and EPS are never derived by subtraction:
    # a nine-month average share count taken from a twelve-month one is a
    # negative number of shares, which is what this flag exists to prevent.
    additive: bool = True


INCOME_STATEMENT: tuple[LineSpec, ...] = (
    LineSpec(
        "revenue",
        "Revenue",
        _us(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
        ),
    ),
    LineSpec(
        "cost_of_revenue",
        "Cost of revenue",
        _us("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
    ),
    LineSpec("gross_profit", "Gross profit", _us("GrossProfit")),
    LineSpec("research", "R&D", _us("ResearchAndDevelopmentExpense")),
    LineSpec(
        "selling_admin",
        "SG&A",
        _us(
            "SellingGeneralAndAdministrativeExpense",
            "GeneralAndAdministrativeExpense",
        ),
    ),
    LineSpec(
        "operating_expenses", "Operating expenses", _us("OperatingExpenses", "CostsAndExpenses")
    ),
    LineSpec("operating_income", "Operating income", _us("OperatingIncomeLoss")),
    LineSpec(
        "interest_expense",
        "Interest expense",
        _us("InterestExpense", "InterestExpenseNonoperating"),
    ),
    LineSpec(
        "pretax_income",
        "Pre-tax income",
        _us(
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ),
    ),
    LineSpec("income_tax", "Income tax", _us("IncomeTaxExpenseBenefit")),
    LineSpec("net_income", "Net income", _us("NetIncomeLoss", "ProfitLoss")),
    LineSpec(
        "eps_basic",
        "EPS, basic",
        _us("EarningsPerShareBasic"),
        unit="USD/shares",
        additive=False,
    ),
    LineSpec(
        "eps_diluted",
        "EPS, diluted",
        _us("EarningsPerShareDiluted"),
        unit="USD/shares",
        additive=False,
    ),
    LineSpec(
        "shares_diluted",
        "Diluted shares",
        _us("WeightedAverageNumberOfDilutedSharesOutstanding"),
        unit="shares",
        additive=False,
    ),
)

BALANCE_SHEET: tuple[LineSpec, ...] = (
    LineSpec(
        "cash", "Cash and equivalents", _us("CashAndCashEquivalentsAtCarryingValue"), instant=True
    ),
    LineSpec(
        "short_term_investments",
        "Short-term investments",
        _us(
            "ShortTermInvestments",
            "MarketableSecuritiesCurrent",
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
            "OtherShortTermInvestments",
        ),
        instant=True,
    ),
    LineSpec("receivables", "Receivables", _us("AccountsReceivableNetCurrent"), instant=True),
    LineSpec("inventory", "Inventory", _us("InventoryNet"), instant=True),
    LineSpec("current_assets", "Current assets", _us("AssetsCurrent"), instant=True),
    LineSpec("total_assets", "Total assets", _us("Assets"), instant=True),
    LineSpec("current_liabilities", "Current liabilities", _us("LiabilitiesCurrent"), instant=True),
    LineSpec(
        "long_term_debt",
        "Long-term debt",
        _us("LongTermDebtNoncurrent", "LongTermDebt"),
        instant=True,
    ),
    LineSpec("total_liabilities", "Total liabilities", _us("Liabilities"), instant=True),
    LineSpec(
        "equity",
        "Shareholders' equity",
        _us(
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        instant=True,
    ),
)

CASH_FLOW: tuple[LineSpec, ...] = (
    LineSpec(
        "operating_cash_flow",
        "Operating cash flow",
        _us(
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ),
    ),
    LineSpec("capex", "Capital expenditure", _us("PaymentsToAcquirePropertyPlantAndEquipment")),
    LineSpec("investing", "Investing cash flow", _us("NetCashProvidedByUsedInInvestingActivities")),
    LineSpec("financing", "Financing cash flow", _us("NetCashProvidedByUsedInFinancingActivities")),
    LineSpec(
        "dividends",
        "Dividends paid",
        _us("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"),
    ),
    LineSpec("buybacks", "Share repurchases", _us("PaymentsForRepurchaseOfCommonStock")),
)

STATEMENTS: tuple[tuple[str, str, tuple[LineSpec, ...]], ...] = (
    ("income", "Income statement", INCOME_STATEMENT),
    ("balance", "Balance sheet", BALANCE_SHEET),
    ("cash_flow", "Cash flow", CASH_FLOW),
)


@dataclass(frozen=True, slots=True)
class Fact:
    """One reported number, reduced to the period it actually covers."""

    end: date
    start: date | None
    value: float
    form: str
    filed: date | None

    @property
    def days(self) -> int | None:
        return (self.end - self.start).days if self.start else None


def _to_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _facts_for(facts: dict | None, taxonomy: str, concept: str, unit: str) -> list[Fact]:
    """Every fact reported for one concept, in one unit.

    The unit is named rather than merged: EPS is quoted in USD/shares and
    share counts in shares, and pouring those into the same list beside the
    dollar figures produces a line that mixes 0.97 with 15 billion.
    """
    if not isinstance(facts, dict):
        return []
    concepts = (facts.get("facts") or {}).get(taxonomy) or {}
    entries = ((concepts.get(concept) or {}).get("units") or {}).get(unit)
    if not isinstance(entries, list):
        return []

    out: list[Fact] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        end = _to_date(entry.get("end"))
        value = entry.get("val")
        if end is None or not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        out.append(
            Fact(
                end=end,
                start=_to_date(entry.get("start")),
                value=float(value),
                form=str(entry.get("form") or ""),
                filed=_to_date(entry.get("filed")),
            )
        )
    return out


def _covers(fact: Fact, instant: bool, annual: bool) -> bool:
    """Whether a fact is the period this series is built from.

    An instant series wants facts with no ``start`` at all. A duration series
    wants only the exact span asked for — the year-to-date cumulatives a 10-Q
    reports alongside its quarter are the reason this is a range test and not
    just "has a start".
    """
    if instant:
        return fact.start is None
    if fact.days is None:
        return False
    low, high = ANNUAL_DAYS if annual else QUARTER_DAYS
    return low <= fact.days <= high


def _anchor_month(end: date) -> int:
    return (end - _MONTH_ANCHOR).month


def fiscal_year_of(end: date) -> int:
    """The year a fiscal year *ending* on ``end`` is named for.

    The calendar year it closes in, which is a convention rather than a fact.
    Companies sharing a January year-end do not agree with each other: the
    year ending January 2026 is "FY2026" to Walmart and Salesforce and
    "fiscal 2025" to Target and Gap. The filings do not settle it either —
    the ``fy`` field is the filing's own focus, and it contradicts itself
    (Salesforce tags two different year-ends as 2025).

    So the label is a convention and the *end date* is the fact. Every period
    carries its end alongside the label for exactly that reason.
    """
    return end.year


def _period_key(end: date, annual: bool, year_end_month: int | None) -> str:
    if annual:
        return f"FY{fiscal_year_of(end)}"
    if year_end_month is None:
        return end.isoformat()

    month = _anchor_month(end)
    # A quarter belongs to the fiscal year that closes *after* it, so the
    # March quarter of a September-year-end company is FY of that same year,
    # while the May quarter of a January-year-end retailer belongs to the
    # year that ends the following January.
    year_end = date(end.year if month <= year_end_month else end.year + 1, year_end_month, 15)
    # Counted forward from the month the fiscal year closes, so Apple's
    # December quarter is Q1 — the company's own numbering, not the calendar's.
    quarter = ((month - year_end_month - 1) % 12) // 3 + 1
    return f"FY{fiscal_year_of(year_end)} Q{quarter}"


def _pick(facts: list[Fact], instant: bool, annual: bool) -> dict[date, Fact]:
    """One fact per period end, preferring the most recently filed.

    The same quarter is reported again by every later filing that shows it as
    a comparative, and restated where the company revised it. The newest
    statement of a period is the one to believe.
    """
    best: dict[date, Fact] = {}
    for fact in facts:
        if not _covers(fact, instant, annual):
            continue
        held = best.get(fact.end)
        if held is None or (fact.filed or date.min) > (held.filed or date.min):
            best[fact.end] = fact
    return best


def _derive_quarters(facts: list[Fact]) -> dict[date, Fact]:
    """The quarters a company never reported on their own.

    Two holes in a quarterly series come from how the forms work, not from
    missing data. A 10-Q states cash flow for the year *to date* rather than
    for the quarter, so a three-month cash flow fact often does not exist at
    all. And no 10-Q is filed for the fourth quarter — the 10-K covers it —
    so the last quarter of every year is absent from every line.

    Both fall out of the same arithmetic: within one fiscal year the
    cumulative figures all share a ``start``, so consecutive differences are
    the quarters, and the year minus the nine months is the fourth.
    """
    by_start: dict[date, dict[date, Fact]] = {}
    for fact in facts:
        if fact.start is None or fact.days is None or fact.days < QUARTER_DAYS[0]:
            continue
        held = by_start.setdefault(fact.start, {}).get(fact.end)
        if held is None or (fact.filed or date.min) > (held.filed or date.min):
            by_start[fact.start][fact.end] = fact

    out: dict[date, Fact] = {}
    for group in by_start.values():
        previous: Fact | None = None
        for end in sorted(group):
            fact = group[end]
            if previous is None:
                if QUARTER_DAYS[0] <= (fact.days or 0) <= QUARTER_DAYS[1]:
                    out[end] = fact
            elif QUARTER_DAYS[0] <= (end - previous.end).days <= QUARTER_DAYS[1]:
                out[end] = replace(fact, value=fact.value - previous.value, start=previous.end)
            previous = fact
    return out


def _year_end_month(facts: dict | None) -> int | None:
    """The month the fiscal year closes, read off the annual filings."""
    for taxonomy, concept in INCOME_STATEMENT[0].concepts + BALANCE_SHEET[5].concepts:
        annual = _pick(_facts_for(facts, taxonomy, concept, "USD"), instant=False, annual=True)
        if annual:
            return _anchor_month(max(annual))
    return None


def build_statements(facts: dict | None, annual: bool, limit: int = 8) -> dict:
    """Every statement line, over the most recent ``limit`` periods.

    Chains are merged period by period rather than resolved to a single
    concept: a company that changed concepts mid-history reports each half
    under a different name, and picking one name returns half a series.
    """
    year_end_month = None if annual else _year_end_month(facts)

    lines: list[dict] = []
    ends: set[date] = set()
    for statement_key, statement_label, specs in STATEMENTS:
        for spec in specs:
            merged: dict[date, Fact] = {}
            used: list[str] = []
            for taxonomy, concept in spec.concepts:
                reported = _facts_for(facts, taxonomy, concept, spec.unit)
                found = _pick(reported, instant=spec.instant, annual=annual)
                if not annual and not spec.instant and spec.additive:
                    # What the company stated wins; the arithmetic only fills
                    # the quarters no form ever carried.
                    found = {**_derive_quarters(reported), **found}
                if not found:
                    continue
                # Earlier in the chain wins: the first name is the one the
                # company reports today, and a later name only fills the
                # stretch of history the first one does not reach.
                new = {end: fact for end, fact in found.items() if end not in merged}
                if new:
                    merged.update(new)
                    used.append(concept)
            if not merged:
                continue
            # Only durations set the axis. A balance sheet is filed at every
            # quarter end, so letting instants in would put three extra
            # columns between one annual close and the next, each holding a
            # balance and nothing else.
            if not spec.instant:
                ends.update(merged)
            lines.append(
                {
                    "statement": statement_key,
                    "statement_label": statement_label,
                    "key": spec.key,
                    "label": spec.label,
                    "unit": spec.unit,
                    "concepts": used,
                    "_values": merged,
                }
            )

    periods = sorted(ends, reverse=True)[:limit]
    keys = [_period_key(end, annual, year_end_month) for end in periods]

    return {
        "periods": [
            {
                "key": key,
                "end": end.isoformat(),
                "fiscal_year": fiscal_year_of(end),
            }
            for key, end in zip(keys, periods, strict=True)
        ],
        "statements": [
            {
                "key": statement_key,
                "label": statement_label,
                "lines": [
                    {
                        "key": line["key"],
                        "label": line["label"],
                        "unit": line["unit"],
                        "concepts": line["concepts"],
                        "values": [
                            (
                                round(fact.value, 4)
                                if (fact := line["_values"].get(end)) is not None
                                else None
                            )
                            for end in periods
                        ],
                    }
                    for line in lines
                    if line["statement"] == statement_key
                ],
            }
            for statement_key, statement_label, _ in STATEMENTS
            if any(line["statement"] == statement_key for line in lines)
        ],
    }
