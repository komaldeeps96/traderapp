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

# What a line is measured in. The literal unit key depends on the company:
# a Canadian issuer reports money in CAD and earnings per share in
# "CAD/shares", so the kind is declared here and resolved per filer.
USD_CODE = "USD"
MONEY = "money"
PER_SHARE = "per_share"
SHARES = "shares"

# Currencies whose symbol is a dollar sign. The statement header states the
# ISO code, so this only decides what the cells are prefixed with.
_DOLLARS = frozenset({"USD", "CAD", "AUD", "NZD", "HKD", "SGD"})

# Concepts probed to find out what a company reports in. Cheap and reliable:
# every filer states its total assets.
_CURRENCY_PROBES: Chain = (
    ("us-gaap", "Assets"),
    ("ifrs-full", "Assets"),
    ("us-gaap", "Revenues"),
    ("ifrs-full", "Revenue"),
)


def _us(*concepts: str) -> Chain:
    return tuple(("us-gaap", concept) for concept in concepts)


def _ifrs(*concepts: str) -> Chain:
    """The IFRS equivalents, for foreign private issuers.

    A company filing a 40-F or 20-F tags under `ifrs-full`, not `us-gaap`,
    and its facts sit in the same free `companyfacts` payload the terminal
    already fetches. Appending them to a chain rather than branching means a
    filer that *switched* taxonomies — Canopy Growth carries both — gets one
    continuous series, exactly as the ASC 606 break is handled.
    """
    return tuple(("ifrs-full", concept) for concept in concepts)


def reporting_currency(facts: dict | None) -> str:
    """The currency a company states its statements in.

    US GAAP filers are USD almost without exception; a foreign private
    issuer is whatever it reports in, commonly CAD. Read rather than assumed,
    because dividing a USD market cap by CAD earnings produces a P/E that is
    wrong by the exchange rate and looks entirely reasonable.
    """
    tally: dict[str, int] = {}
    for taxonomy, concept in _CURRENCY_PROBES:
        if not isinstance(facts, dict):
            break
        concepts = (facts.get("facts") or {}).get(taxonomy) or {}
        units = (concepts.get(concept) or {}).get("units") or {}
        for unit, entries in units.items():
            if len(unit) == 3 and unit.isalpha() and unit.isupper():
                tally[unit] = tally.get(unit, 0) + len(entries or ())
    if not tally:
        return "USD"
    # USD wins a tie: a filer reporting in both is reporting to US investors.
    return max(tally, key=lambda unit: (tally[unit], unit == "USD"))


def currency_symbol(currency: str) -> str:
    if currency in _DOLLARS:
        return "$"
    return {"EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5", "CHF": "CHF ", "ILS": "\u20aa"}.get(
        currency, f"{currency} "
    )


def unit_key(kind: str, currency: str) -> str:
    """The `units` key in companyfacts for one kind of line."""
    if kind == PER_SHARE:
        return f"{currency}/shares"
    if kind == SHARES:
        return "shares"
    return currency


@dataclass(frozen=True, slots=True)
class LineSpec:
    key: str
    label: str
    concepts: Chain
    # One of MONEY / PER_SHARE / SHARES; the literal unit key is resolved
    # against the filer's reporting currency.
    unit: str = MONEY
    # A balance is reported at an instant; everything else spans a period.
    instant: bool = False
    # Whether later concepts in the chain may fill periods the first one
    # does not cover. True almost everywhere — it is what stitches a series
    # across the ASC 606 break. False where the chain's entries are not the
    # same quantity: "shareholders' equity" with and without minority
    # interests are different numbers, and a row that switches between them
    # mid-series is not comparable to itself.
    merge_chain: bool = True
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
        )
        + _ifrs("Revenue", "RevenueFromContractsWithCustomers"),
    ),
    LineSpec(
        "cost_of_revenue",
        "Cost of revenue",
        _us("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold")
        + _ifrs("CostOfSales"),
    ),
    LineSpec("gross_profit", "Gross profit", _us("GrossProfit") + _ifrs("GrossProfit")),
    LineSpec(
        "research",
        "R&D",
        _us("ResearchAndDevelopmentExpense") + _ifrs("ResearchAndDevelopmentExpense"),
    ),
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
    LineSpec(
        "operating_income",
        "Operating income",
        _us("OperatingIncomeLoss") + _ifrs("ProfitLossFromOperatingActivities"),
    ),
    LineSpec(
        "interest_expense",
        "Interest expense",
        _us("InterestExpense", "InterestExpenseNonoperating")
        + _ifrs("InterestExpense", "FinanceCosts"),
    ),
    LineSpec(
        "pretax_income",
        "Pre-tax income",
        _us(
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        )
        + _ifrs("ProfitLossBeforeTax"),
    ),
    LineSpec(
        "income_tax",
        "Income tax",
        _us("IncomeTaxExpenseBenefit") + _ifrs("IncomeTaxExpenseContinuingOperations"),
    ),
    LineSpec(
        "net_income",
        "Net income",
        # Attributable to the parent, first in both taxonomies. "Net income"
        # in every terminal means the owners' share; `ProfitLoss` includes
        # minority interest and is a different, larger number — for SNDL,
        # -96.2M against the -94.8M every other source publishes.
        _us("NetIncomeLoss", "ProfitLoss")
        + _ifrs("ProfitLossAttributableToOwnersOfParent", "ProfitLoss"),
    ),
    LineSpec(
        "eps_basic",
        "EPS, basic",
        _us("EarningsPerShareBasic") + _ifrs("BasicEarningsLossPerShare"),
        unit=PER_SHARE,
        additive=False,
    ),
    LineSpec(
        "eps_diluted",
        "EPS, diluted",
        _us("EarningsPerShareDiluted") + _ifrs("DilutedEarningsLossPerShare"),
        unit=PER_SHARE,
        additive=False,
    ),
    LineSpec(
        "other_income",
        "Other income / expense",
        _us("NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense")
        + _ifrs("OtherOperatingIncomeExpenseNet"),
    ),
    LineSpec(
        "depreciation",
        "Depreciation & amortisation",
        _us("DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet")
        + _ifrs("DepreciationAndAmortisationExpense"),
    ),
    LineSpec(
        "stock_compensation",
        "Stock compensation",
        _us("ShareBasedCompensation") + _ifrs("ShareBasedPaymentsExpense"),
    ),
    LineSpec(
        "comprehensive_income",
        "Comprehensive income",
        _us("ComprehensiveIncomeNetOfTax") + _ifrs("ComprehensiveIncome"),
    ),
    LineSpec(
        "shares_basic",
        "Basic shares",
        _us("WeightedAverageNumberOfSharesOutstandingBasic") + _ifrs("WeightedAverageShares"),
        unit=SHARES,
        additive=False,
    ),
    LineSpec(
        "shares_diluted",
        "Diluted shares",
        _us("WeightedAverageNumberOfDilutedSharesOutstanding")
        + _ifrs("WeightedAverageNumberOfDilutedSharesOutstanding"),
        unit=SHARES,
        additive=False,
    ),
)

BALANCE_SHEET: tuple[LineSpec, ...] = (
    LineSpec(
        "cash",
        "Cash and equivalents",
        _us("CashAndCashEquivalentsAtCarryingValue") + _ifrs("CashAndCashEquivalents"),
        instant=True,
    ),
    LineSpec(
        "short_term_investments",
        "Short-term investments",
        _us(
            "ShortTermInvestments",
            "MarketableSecuritiesCurrent",
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
            "OtherShortTermInvestments",
        )
        + _ifrs("OtherCurrentFinancialAssets"),
        instant=True,
    ),
    LineSpec(
        "receivables",
        "Receivables",
        _us("AccountsReceivableNetCurrent") + _ifrs("TradeAndOtherCurrentReceivables"),
        instant=True,
    ),
    LineSpec("inventory", "Inventory", _us("InventoryNet") + _ifrs("Inventories"), instant=True),
    LineSpec(
        "current_assets",
        "Current assets",
        _us("AssetsCurrent") + _ifrs("CurrentAssets"),
        instant=True,
    ),
    LineSpec(
        "ppe_net",
        "Property, plant & equipment",
        _us("PropertyPlantAndEquipmentNet") + _ifrs("PropertyPlantAndEquipment"),
        instant=True,
    ),
    LineSpec("goodwill", "Goodwill", _us("Goodwill") + _ifrs("Goodwill"), instant=True),
    LineSpec(
        "intangibles",
        "Intangible assets",
        _us("IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet")
        + _ifrs("IntangibleAssetsOtherThanGoodwill"),
        instant=True,
    ),
    LineSpec("total_assets", "Total assets", _us("Assets") + _ifrs("Assets"), instant=True),
    LineSpec(
        "accounts_payable",
        "Accounts payable",
        _us("AccountsPayableCurrent") + _ifrs("TradeAndOtherCurrentPayables"),
        instant=True,
    ),
    LineSpec(
        "deferred_revenue",
        "Deferred revenue",
        _us("ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent")
        + _ifrs("ContractLiabilities"),
        instant=True,
    ),
    LineSpec(
        "short_term_debt",
        "Short-term debt",
        _us("DebtCurrent", "ShortTermBorrowings", "LongTermDebtCurrent")
        + _ifrs("ShorttermBorrowings", "CurrentPortionOfLongtermBorrowings"),
        instant=True,
    ),
    LineSpec(
        "current_liabilities",
        "Current liabilities",
        _us("LiabilitiesCurrent") + _ifrs("CurrentLiabilities"),
        instant=True,
    ),
    LineSpec(
        "long_term_debt",
        "Long-term debt",
        _us("LongTermDebtNoncurrent", "LongTermDebt")
        + _ifrs("NoncurrentPortionOfNoncurrentBorrowings", "Borrowings"),
        instant=True,
    ),
    LineSpec(
        "total_liabilities",
        "Total liabilities",
        _us("Liabilities") + _ifrs("Liabilities"),
        instant=True,
    ),
    LineSpec(
        "operating_lease_liability",
        "Operating lease liability",
        _us("OperatingLeaseLiability", "OperatingLeaseLiabilityNoncurrent")
        + _ifrs("LeaseLiabilities"),
        instant=True,
    ),
    LineSpec(
        "retained_earnings",
        "Retained earnings",
        _us("RetainedEarningsAccumulatedDeficit") + _ifrs("RetainedEarnings"),
        instant=True,
    ),
    LineSpec(
        "accumulated_oci",
        "Accumulated OCI",
        _us("AccumulatedOtherComprehensiveIncomeLossNetOfTax")
        + _ifrs("AccumulatedOtherComprehensiveIncome"),
        instant=True,
    ),
    LineSpec(
        "noncontrolling_interest",
        "Noncontrolling interest",
        _us("MinorityInterest") + _ifrs("NoncontrollingInterests"),
        instant=True,
    ),
    LineSpec(
        "temporary_equity",
        "Redeemable equity",
        # Shares subject to redemption sit between liabilities and equity and
        # belong to neither. Every SPAC-era balance sheet has this, and
        # without it the sheet does not add up.
        _us(
            "TemporaryEquityCarryingAmountAttributableToParent",
            "TemporaryEquityCarryingAmount",
            # Redeemable minority interests are mezzanine too: outside equity,
            # outside liabilities, and exactly the 0.6% by which Canopy
            # Growth's balance sheet failed to add up without them.
            "RedeemableNoncontrollingInterestEquityCarryingAmount",
        ),
        instant=True,
    ),
    LineSpec(
        "equity",
        "Shareholders' equity",
        _us(
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        )
        + _ifrs("EquityAttributableToOwnersOfParent", "Equity"),
        instant=True,
        merge_chain=False,
    ),
)

CASH_FLOW: tuple[LineSpec, ...] = (
    LineSpec(
        "operating_cash_flow",
        "Operating cash flow",
        _us(
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        )
        + _ifrs("CashFlowsFromUsedInOperatingActivities"),
    ),
    LineSpec(
        "capex",
        "Capital expenditure",
        _us("PaymentsToAcquirePropertyPlantAndEquipment")
        + _ifrs("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
    ),
    LineSpec(
        "investing",
        "Investing cash flow",
        _us("NetCashProvidedByUsedInInvestingActivities")
        + _ifrs("CashFlowsFromUsedInInvestingActivities"),
    ),
    LineSpec(
        "financing",
        "Financing cash flow",
        _us("NetCashProvidedByUsedInFinancingActivities")
        + _ifrs("CashFlowsFromUsedInFinancingActivities"),
    ),
    LineSpec(
        "working_capital_change",
        "Change in working capital",
        _us("IncreaseDecreaseInOperatingCapital")
        + _ifrs("AdjustmentsForDecreaseIncreaseInWorkingCapital"),
    ),
    LineSpec(
        "acquisitions",
        "Acquisitions",
        _us("PaymentsToAcquireBusinessesNetOfCashAcquired")
        + _ifrs(
            "CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities"
        ),
    ),
    LineSpec(
        "debt_issued",
        "Debt raised",
        _us("ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfDebt")
        + _ifrs("ProceedsFromBorrowingsClassifiedAsFinancingActivities"),
    ),
    LineSpec(
        "debt_repaid",
        "Debt repaid",
        _us("RepaymentsOfLongTermDebt", "RepaymentsOfDebt")
        + _ifrs("RepaymentsOfBorrowingsClassifiedAsFinancingActivities"),
    ),
    LineSpec(
        "stock_issued",
        "Stock issued",
        _us("ProceedsFromIssuanceOfCommonStock") + _ifrs("ProceedsFromIssuingShares"),
    ),
    LineSpec(
        "taxes_paid",
        "Income taxes paid",
        _us("IncomeTaxesPaidNet", "IncomeTaxesPaid")
        + _ifrs("IncomeTaxesPaidClassifiedAsOperatingActivities"),
    ),
    LineSpec(
        "dividends",
        "Dividends paid",
        _us("PaymentsOfDividendsCommonStock", "PaymentsOfDividends")
        + _ifrs("DividendsPaidClassifiedAsFinancingActivities"),
    ),
    LineSpec(
        "buybacks",
        "Share repurchases",
        _us("PaymentsForRepurchaseOfCommonStock") + _ifrs("PaymentsToAcquireOrRedeemEntitysShares"),
    ),
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


def _anchor_date(end: date) -> date:
    return end - _MONTH_ANCHOR


def _anchor_month(end: date) -> int:
    return _anchor_date(end).month


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
    # The anchored date, not the raw one. A 52/53-week filer can close its
    # year on 3 January — Johnson & Johnson's FY2020 ends 2021-01-03 — and
    # `end.year` calls that 2021, colliding with the year that actually is
    # 2021 and putting two identically-labelled columns in the table.
    return _anchor_date(end).year


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
    # Day 28 so the fortnight anchor cannot push this sentinel into the
    # previous month — and so into the previous fiscal year label.
    year_end = date(end.year if month <= year_end_month else end.year + 1, year_end_month, 28)
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


def _derive_total_liabilities(lines: list[dict]) -> None:
    """Fill a total-liabilities line the filer never tagged.

    AT&T stopped reporting the `Liabilities` subtotal after 2015 — it files
    the components and `LiabilitiesAndStockholdersEquity` instead — and it is
    not alone. The balance sheet still states the number, just as the
    remainder once everything with a claim after creditors is taken out.

    Only filled where it is genuinely absent, and the arithmetic is named in
    the line's concepts so a derived figure is never passed off as a tag.
    """
    by_key = {line["key"]: line for line in lines}
    target = by_key.get("total_liabilities")
    assets = by_key.get("total_assets")
    equity = by_key.get("equity")
    if assets is None or equity is None:
        return

    # Gap-filling, not all-or-nothing: AT&T tagged `Liabilities` until 2015
    # and stopped, so the line exists and is empty across every year anyone
    # would look at.
    # Whether minority interests are already inside the equity figure
    # depends on which concept answered. Subtracting them again where they
    # are makes the derived liabilities too small by exactly that amount —
    # AT&T's 2022 sheet was out by its own $8.957bn of minorities.
    equity_includes_minorities = bool(
        set(equity["concepts"])
        & {
            "Equity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        }
    )
    subtract = (
        ["temporary_equity"]
        if equity_includes_minorities
        else [
            "noncontrolling_interest",
            "temporary_equity",
        ]
    )

    derived: dict[date, Fact] = {}
    existing = target["_values"] if target is not None else {}
    for end, asset_fact in assets["_values"].items():
        if end in existing:
            continue
        equity_fact = equity["_values"].get(end)
        if equity_fact is None:
            continue
        residual = asset_fact.value - equity_fact.value
        for key in subtract:
            other = by_key.get(key)
            found = other["_values"].get(end) if other else None
            if found is not None:
                residual -= found.value
        derived[end] = replace(asset_fact, value=residual)

    if not derived:
        return
    if target is None:
        spec = next(s for s in BALANCE_SHEET if s.key == "total_liabilities")
        target = {
            "statement": "balance",
            "instant": True,
            "kind": spec.unit,
            "key": spec.key,
            "label": spec.label,
            "unit": spec.unit,
            "concepts": [],
            "_values": {},
        }
        lines.append(target)
    target["_values"] = {**existing, **derived}
    target["concepts"] = [
        *target["concepts"],
        "derived: assets less equity and minority interests",
    ]


def _year_end_month(facts: dict | None, currency: str) -> int | None:
    """The month the fiscal year closes, read off the annual filings."""
    for taxonomy, concept in INCOME_STATEMENT[0].concepts + BALANCE_SHEET[5].concepts:
        rows = _facts_for(facts, taxonomy, concept, unit_key(MONEY, currency))
        annual = _pick(rows, instant=False, annual=True)
        if annual:
            return _anchor_month(max(annual))
    return None


def build_statements(facts: dict | None, annual: bool, limit: int = 8) -> dict:
    """Every statement line, over the most recent ``limit`` periods.

    Chains are merged period by period rather than resolved to a single
    concept: a company that changed concepts mid-history reports each half
    under a different name, and picking one name returns half a series.
    """
    currency = reporting_currency(facts)
    year_end_month = None if annual else _year_end_month(facts, currency)

    lines: list[dict] = []
    ends: set[date] = set()
    for statement_key, statement_label, specs in STATEMENTS:
        for spec in specs:
            merged: dict[date, Fact] = {}
            used: list[str] = []
            for taxonomy, concept in spec.concepts:
                reported = _facts_for(facts, taxonomy, concept, unit_key(spec.unit, currency))
                found = _pick(reported, instant=spec.instant, annual=annual)
                if not annual and not spec.instant and spec.additive:
                    # What the company stated wins; the arithmetic only fills
                    # the quarters no form ever carried.
                    found = {**_derive_quarters(reported), **found}
                if not found:
                    continue
                if merged and not spec.merge_chain:
                    # One definition for the whole row, not the best-covered
                    # patchwork of several.
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
                    "instant": spec.instant,
                    "kind": spec.unit,
                    "statement_label": statement_label,
                    "key": spec.key,
                    "label": spec.label,
                    "unit": unit_key(spec.unit, currency),
                    "concepts": used,
                    "_values": merged,
                }
            )

    _derive_total_liabilities(lines)

    periods = sorted(ends, reverse=True)[:limit]
    keys = [_period_key(end, annual, year_end_month) for end in periods]
    # The window each period covers, taken from whichever duration fact set
    # the axis. Conversion needs it: a flow goes at the average rate across
    # the period, and the average needs both ends.
    starts = {
        end: fact.start
        for line in lines
        if not line["instant"]
        for end, fact in line["_values"].items()
        if fact.start is not None
    }

    return {
        # Stated rather than assumed: a foreign private issuer reports in its
        # own currency, and a figure with no currency beside it is a number
        # that cannot be compared to anything.
        "currency": currency,
        "symbol_prefix": currency_symbol(currency),
        "periods": [
            {
                "key": key,
                "end": end.isoformat(),
                "start": starts[end].isoformat() if starts.get(end) else None,
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
                        "kind": line["kind"],
                        "instant": line["instant"],
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


async def convert_to_usd(built: dict, fx) -> dict:
    """Restate a statement set in dollars.

    Separate from `build_statements`, and async, because it reaches the
    network: the builder stays pure and testable, and this is the only part
    that can fail.

    Each period is converted at its own rate rather than at today's, so a
    2019 figure is what it was worth in 2019. A single current rate would
    push this year's exchange move back through ten years of history and
    call the result growth.

    Two rates per period, because a balance and a flow are not converted the
    same way — IAS 21 puts flows at the average across the period and
    balances at the closing rate on the sheet date.

    A period whose rate cannot be fetched keeps its own currency and is
    reported as unconverted rather than silently mixed into a dollar column.
    """
    native = built.get("currency", USD_CODE)
    if native == USD_CODE:
        built["native_currency"] = USD_CODE
        built["converted"] = False
        return built

    closing: dict[str, float | None] = {}
    average: dict[str, float | None] = {}
    for period in built.get("periods", []):
        end = _to_date(period.get("end"))
        start = _to_date(period.get("start"))
        if end is None:
            continue
        closing[period["key"]] = await fx.closing_rate(native, end)
        average[period["key"]] = (
            await fx.average_rate(native, start, end)
            if start is not None
            else closing[period["key"]]
        )
        period["fx_closing"] = closing[period["key"]]
        period["fx_average"] = average[period["key"]]

    keys = [period["key"] for period in built.get("periods", [])]
    unconverted = [key for key in keys if closing.get(key) is None or average.get(key) is None]

    for statement in built.get("statements", []):
        for line in statement.get("lines", []):
            if line.get("kind") == SHARES:
                continue
            rates = closing if line.get("instant") else average
            line["values"] = [
                None if value is None or rates.get(key) is None else round(value * rates[key], 4)
                for key, value in zip(keys, line["values"], strict=True)
            ]
            line["unit"] = unit_key(line.get("kind", MONEY), USD_CODE)

    built["native_currency"] = native
    built["currency"] = USD_CODE
    built["symbol_prefix"] = currency_symbol(USD_CODE)
    built["converted"] = True
    # Named rather than counted: a column silently missing from a converted
    # table is the one thing worse than an unconverted one.
    built["unconverted_periods"] = unconverted
    return built


# A search returns rows, not a statement, and a company can report nine
# hundred concepts. This is what one screenful of them costs.
MAX_CONCEPT_ROWS = 60


def _humanise(concept: str) -> str:
    """`RetainedEarningsAccumulatedDeficit` -> `Retained earnings accumulated deficit`."""
    words: list[str] = []
    current = ""
    for character in concept:
        if character.isupper() and current and not current.isupper():
            words.append(current)
            current = character
        else:
            current += character
    if current:
        words.append(current)
    joined = " ".join(words).replace("  ", " ").strip()
    return joined[:1].upper() + joined[1:].lower() if joined else concept


def search_concepts(
    facts: dict | None,
    annual: bool,
    query: str,
    limit: int = 8,
    max_rows: int = MAX_CONCEPT_ROWS,
) -> dict:
    """Every concept a company reports, not just the ones drawn on a statement.

    A curated statement is the readable view and it is roughly a tenth of what
    a filer actually tags — Apple reports 503 concepts, JP Morgan 931 — and the
    rest is where a specific question gets answered: what tax was actually
    paid, what sits in accumulated OCI, how large the lease liability is.

    The period axis is the statement's own, not one derived from whatever
    matched. Search results include instants filed at every quarter end, and
    letting those set the columns produced two columns both labelled FY2026
    with nothing in either. Reusing the statement axis also means a number
    found here sits in the same column as the statement line above it.

    Ranked by how much history each concept has, so something reported once in
    2013 does not outrank a line reported every year since.
    """
    currency = reporting_currency(facts)
    needle = query.strip().lower()
    empty = {"currency": currency, "query": query, "total": 0, "periods": [], "rows": []}
    if not isinstance(facts, dict) or not needle:
        return empty

    statements = build_statements(facts, annual=annual, limit=limit)
    periods = statements["periods"]
    if not periods:
        return empty
    ends = [date.fromisoformat(period["end"]) for period in periods]

    matches: list[dict] = []
    for taxonomy, concepts in (facts.get("facts") or {}).items():
        if not isinstance(concepts, dict):
            continue
        for concept, node in concepts.items():
            if needle not in concept.lower():
                continue
            for unit in (node or {}).get("units") or {}:
                rows = _facts_for(facts, taxonomy, concept, unit)
                # A concept is an instant or a duration, never both; the facts
                # say which, and the answer decides how it is picked.
                instant = all(row.start is None for row in rows) if rows else False
                found = _pick(rows, instant=instant, annual=annual)
                hits = sum(1 for end in ends if end in found)
                if not hits:
                    continue
                matches.append(
                    {
                        "key": f"{taxonomy}:{concept}:{unit}",
                        "label": _humanise(concept),
                        "concept": concept,
                        "taxonomy": taxonomy,
                        "unit": unit,
                        "hits": hits,
                        "values": [
                            round(found[end].value, 4) if end in found else None for end in ends
                        ],
                    }
                )

    # Most-populated first: a row with a value in every column is the one
    # worth reading, and a search for "tax" returns a hundred and twenty.
    matches.sort(key=lambda row: (-row["hits"], row["concept"]))

    return {
        "currency": currency,
        "query": query,
        "total": len(matches),
        "periods": periods,
        "rows": [
            {key: row[key] for key in ("key", "label", "concept", "taxonomy", "unit", "values")}
            for row in matches[:max_rows]
        ],
    }
