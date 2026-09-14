"""The statement lines the terminal draws, and the XBRL concepts behind each.

A catalogue, not logic: financials.py resolves these against a filer's facts.
"""

from __future__ import annotations

from dataclasses import dataclass

Chain = tuple[tuple[str, str], ...]

# What a line is measured in. The literal unit key depends on the company:
# a Canadian issuer reports money in CAD and earnings per share in
# "CAD/shares", so the kind is declared here and resolved per filer.
MONEY = "money"
PER_SHARE = "per_share"
SHARES = "shares"


def _us(*concepts: str) -> Chain:
    return tuple(("us-gaap", concept) for concept in concepts)


def _ifrs(*concepts: str) -> Chain:
    """The IFRS equivalents, for foreign private issuers.

    A 40-F or 20-F filer tags under `ifrs-full`, not `us-gaap`, in the same
    `companyfacts` payload. Appended to the chain rather than branching, so a
    filer that switched taxonomies gets one continuous series.
    """
    return tuple(("ifrs-full", concept) for concept in concepts)


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
    # Whether later concepts in the chain may fill periods the first does not
    # cover. True almost everywhere; false where the entries are not the same
    # quantity — equity with and without minority interests are different
    # numbers, and a row switching between them is not comparable to itself.
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
            # A bank's total revenue. JP Morgan stopped tagging quarterly
            # `Revenues` in 2014 and files this instead, so without it the
            # whole sector has annual figures and no trailing twelve months.
            "RevenuesNetOfInterestExpense",
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
        merge_chain=False,
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
