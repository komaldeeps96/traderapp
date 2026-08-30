"""Ratios and valuation built on the statements.

The arithmetic is easy; what earns tests is everything this refuses to
compute. A margin on a missing revenue, a P/E on a loss, a growth rate off a
negative base — each is a number that would render, and each would be read as
information it is not.
"""

from __future__ import annotations

import pytest

from app.services.financials import build_statements
from app.services.metrics import build_metrics
from tests.unit.test_financials import REVENUE, fact, facts, usd


def annual(concept: str, rows: list[tuple[str, float]], unit: str = "USD") -> dict:
    return usd(
        concept,
        [
            fact(f"{year}-01-01", f"{year}-12-31", value, filed=f"{year + 1}-02-01")
            for year, value in rows
        ],
        unit=unit,
    )


def metric(built: dict, key: str) -> dict | None:
    for group in built["groups"]:
        for entry in group["metrics"]:
            if entry["key"] == key:
                return entry
    return None


class TestRatios:
    def test_a_margin_is_the_two_lines_of_one_period(self):
        data = facts(
            annual(REVENUE, [(2025, 100.0)]),
            annual("GrossProfit", [(2025, 40.0)]),
        )
        assert metric(build_metrics(data, annual=True), "gross_margin")["values"] == [0.4]

    def test_a_ratio_needs_both_sides(self):
        """A margin against a blank revenue is not small, it is absent."""
        data = facts(annual("GrossProfit", [(2025, 40.0)]))
        assert metric(build_metrics(data, annual=True), "gross_margin") is None

    def test_growth_is_measured_against_the_year_before(self):
        data = facts(annual(REVENUE, [(2024, 100.0), (2025, 120.0)]))
        values = metric(build_metrics(data, annual=True), "revenue_growth")["values"]
        # Newest first, and the oldest period has nothing to compare against.
        assert values == [0.2, None]

    def test_growth_from_a_negative_base_is_refused(self):
        """Revenue rising from -2 to 1 is a sign change, not 150% growth."""
        data = facts(annual(REVENUE, [(2024, -2.0), (2025, 1.0)]))
        assert metric(build_metrics(data, annual=True), "revenue_growth") is None

    def test_a_negative_denominator_is_refused(self):
        """Debt/equity on negative book value is arithmetic, not information.

        A company with more liabilities than assets would otherwise show a
        tidy positive ratio and read as conservatively financed.
        """
        data = facts(
            annual(REVENUE, [(2025, 100.0)]),
            usd("StockholdersEquity", [fact(None, "2025-12-31", -50.0, filed="2026-02-01")]),
            usd("LongTermDebtNoncurrent", [fact(None, "2025-12-31", 80.0, filed="2026-02-01")]),
        )
        assert metric(build_metrics(data, annual=True), "debt_to_equity") is None

    def test_free_cash_flow_is_operating_less_capex(self):
        data = facts(
            annual(REVENUE, [(2025, 100.0)]),
            annual("NetCashProvidedByUsedInOperatingActivities", [(2025, 30.0)]),
            annual("PaymentsToAcquirePropertyPlantAndEquipment", [(2025, 12.0)]),
        )
        built = build_metrics(data, annual=True)
        assert metric(built, "free_cash_flow")["values"] == [18.0]
        assert metric(built, "fcf_margin")["values"] == [0.18]

    def test_a_loss_still_reports_a_negative_margin(self):
        """Refusing negative *denominators* must not suppress a real loss."""
        data = facts(
            annual(REVENUE, [(2025, 100.0)]),
            annual("NetIncomeLoss", [(2025, -25.0)]),
        )
        assert metric(build_metrics(data, annual=True), "net_margin")["values"] == [-0.25]

    def test_a_group_with_nothing_in_it_is_dropped(self):
        data = facts(annual(REVENUE, [(2025, 100.0)]))
        labels = [group["label"] for group in build_metrics(data, annual=True)["groups"]]
        assert "Cash" not in labels


class TestValuation:
    def _apple_ish(self) -> dict:
        return facts(
            annual(REVENUE, [(2025, 400.0)]),
            annual("NetIncomeLoss", [(2025, 100.0)]),
            usd("StockholdersEquity", [fact(None, "2025-12-31", 70.0, filed="2026-02-01")]),
            usd(
                "CashAndCashEquivalentsAtCarryingValue",
                [fact(None, "2025-12-31", 30.0, filed="2026-02-01")],
            ),
            usd("LongTermDebtNoncurrent", [fact(None, "2025-12-31", 80.0, filed="2026-02-01")]),
        )

    def test_multiples_use_the_market_cap_passed_in(self):
        built = build_metrics(self._apple_ish(), annual=True, market_cap=2000.0)
        by_key = {entry["key"]: entry["value"] for entry in built["valuation"]["multiples"]}
        assert by_key["pe"] == 20.0
        assert by_key["ps"] == 5.0

    def test_enterprise_value_adds_debt_and_takes_out_cash(self):
        built = build_metrics(self._apple_ish(), annual=True, market_cap=2000.0)
        assert built["valuation"]["enterprise_value"] == 2000.0 + 80.0 - 30.0

    def test_a_price_to_earnings_on_a_loss_is_refused(self):
        """ "-14.2x" invites being read as cheap."""
        data = facts(annual(REVENUE, [(2025, 400.0)]), annual("NetIncomeLoss", [(2025, -50.0)]))
        built = build_metrics(data, annual=True, market_cap=2000.0)
        by_key = {entry["key"]: entry["value"] for entry in built["valuation"]["multiples"]}
        assert by_key["pe"] is None
        assert by_key["ps"] == 5.0

    def test_no_market_cap_means_no_multiples(self):
        built = build_metrics(self._apple_ish(), annual=True, market_cap=None)
        assert all(entry["value"] is None for entry in built["valuation"]["multiples"])
        assert built["valuation"]["enterprise_value"] is None

    def test_a_trailing_year_needs_four_quarters(self):
        """Three quarters and a gap is not a year.

        Summing what is there would understate the denominator, which on a
        multiple reads as *cheaper* than the company is.
        """
        rows = [
            fact("2025-01-01", "2025-03-31", 10.0, filed="2025-05-01", form="10-Q"),
            fact("2025-04-01", "2025-06-30", 12.0, filed="2025-08-01", form="10-Q"),
            fact("2025-07-01", "2025-09-30", 13.0, filed="2025-11-01", form="10-Q"),
        ]
        built = build_metrics(facts(usd(REVENUE, rows)), annual=False, market_cap=100.0)
        by_key = {entry["key"]: entry["value"] for entry in built["valuation"]["multiples"]}
        assert by_key["ps"] is None

    def test_four_quarters_make_a_trailing_year(self):
        rows = [
            fact("2025-01-01", "2025-03-31", 10.0, filed="2025-05-01", form="10-Q"),
            fact("2025-04-01", "2025-06-30", 12.0, filed="2025-08-01", form="10-Q"),
            fact("2025-07-01", "2025-09-30", 13.0, filed="2025-11-01", form="10-Q"),
            fact("2025-10-01", "2025-12-31", 15.0, filed="2026-02-01", form="10-Q"),
        ]
        built = build_metrics(facts(usd(REVENUE, rows)), annual=False, market_cap=100.0)
        by_key = {entry["key"]: entry["value"] for entry in built["valuation"]["multiples"]}
        assert by_key["ps"] == pytest.approx(2.0)
        assert built["valuation"]["basis"] == "trailing twelve months"


class TestEmptiness:
    @pytest.mark.parametrize("payload", [None, {}, {"facts": {"us-gaap": {}}}])
    def test_nothing_reported_is_not_an_error(self, payload):
        built = build_metrics(payload, annual=True, market_cap=100.0)
        assert built["groups"] == []
        assert built["periods"] == []


class TestCrossCurrency:
    """A foreign private issuer reports in its own currency.

    Market cap for a US listing is quoted in USD, so every multiple built
    from both would be wrong by the exchange rate — and wrong *quietly*: a
    P/E of 12 where the truth is 17 looks like nothing at all.
    """

    def _canadian(self) -> dict:
        rows = [fact("2025-01-01", "2025-12-31", 946.0, filed="2026-03-12", form="40-F")]
        profit = [fact("2025-01-01", "2025-12-31", 100.0, filed="2026-03-12", form="40-F")]
        gross = [fact("2025-01-01", "2025-12-31", 258.0, filed="2026-03-12", form="40-F")]
        return {
            "facts": {
                "ifrs-full": {
                    "Revenue": {"units": {"CAD": rows}},
                    "ProfitLoss": {"units": {"CAD": profit}},
                    "GrossProfit": {"units": {"CAD": gross}},
                }
            }
        }

    def test_multiples_are_refused_rather_than_computed_wrong(self):
        built = build_metrics(self._canadian(), annual=True, market_cap=1000.0)
        assert all(entry["value"] is None for entry in built["valuation"]["multiples"])

    def test_the_refusal_says_why(self):
        built = build_metrics(self._canadian(), annual=True, market_cap=1000.0)
        note = built["valuation"]["note"]
        assert "CAD" in note and "exchange rate" in note

    def test_currency_neutral_ratios_survive(self):
        """A margin is one currency over itself, so it is still a fact."""
        built = build_metrics(self._canadian(), annual=True, market_cap=1000.0)
        margin = metric(built, "gross_margin")
        assert margin["values"][0] == pytest.approx(258.0 / 946.0)

    def test_the_currency_travels_with_the_read(self):
        assert build_metrics(self._canadian(), annual=True, market_cap=1.0)["currency"] == "CAD"

    def test_a_dollar_filer_still_gets_multiples(self):
        data = facts(
            annual(REVENUE, [(2025, 400.0)]),
            annual("NetIncomeLoss", [(2025, 100.0)]),
        )
        built = build_metrics(data, annual=True, market_cap=2000.0)
        by_key = {entry["key"]: entry["value"] for entry in built["valuation"]["multiples"]}
        assert by_key["pe"] == 20.0
        assert built["valuation"]["note"] is None


class TestValuationBasis:
    """Which twelve months the multiples are quoted on.

    Every other screen uses a trailing twelve months. Quoting the latest
    fiscal year instead is not a miscalculation — it answers a question
    nobody asked, and disagrees with every other source. Apple's P/E read
    41.65 against a market quoting 36.65, and Crocs' operating margin 3.70%
    on a year carrying a goodwill impairment against 24.22% on the twelve
    months actually elapsed.
    """

    def _quarters(self, revenue: list[float], profit: list[float]) -> dict:
        rows, income = [], []
        starts = ["2025-10-01", "2025-07-01", "2025-04-01", "2025-01-01"]
        ends = ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"]
        for start, end, r, p in zip(starts, ends, revenue, profit, strict=True):
            rows.append(fact(start, end, r, filed="2026-02-01", form="10-Q"))
            income.append(fact(start, end, p, filed="2026-02-01", form="10-Q"))
        return facts(usd(REVENUE, rows), usd("NetIncomeLoss", income))

    def _year(self, revenue: float, profit: float) -> dict:
        return facts(
            annual(REVENUE, [(2025, revenue)]),
            annual("NetIncomeLoss", [(2025, profit)]),
        )

    def test_the_trailing_year_is_used_when_the_quarters_are_there(self):
        built = build_metrics(
            None,
            annual=True,
            market_cap=1000.0,
            statements=build_statements(self._year(400.0, 100.0), annual=True),
            trailing=build_statements(
                self._quarters([30, 30, 30, 30], [10, 10, 10, 10]), annual=False
            ),
        )
        assert built["valuation"]["basis"] == "trailing twelve months"
        by_key = {m["key"]: m["value"] for m in built["valuation"]["multiples"]}
        # 1000 / (10+10+10+10), not 1000 / 100.
        assert by_key["pe"] == pytest.approx(25.0)

    def test_the_fiscal_year_stands_when_there_are_no_quarters(self):
        """A foreign private issuer files no 10-Q; the year is all there is."""
        built = build_metrics(
            None,
            annual=True,
            market_cap=1000.0,
            statements=build_statements(self._year(400.0, 100.0), annual=True),
            trailing=build_statements(facts(), annual=False),
        )
        assert built["valuation"]["basis"] == "annual"
        by_key = {m["key"]: m["value"] for m in built["valuation"]["multiples"]}
        assert by_key["pe"] == pytest.approx(10.0)

    def test_three_quarters_is_not_a_trailing_year(self):
        """Summing what is there would understate the denominator, which on
        a multiple reads as cheaper than the company is."""
        partial = self._quarters([30, 30, 30, 30], [10, 10, 10, 10])
        rows = partial["facts"]["us-gaap"][REVENUE]["units"]["USD"][:3]
        partial["facts"]["us-gaap"][REVENUE]["units"]["USD"] = rows
        built = build_metrics(
            None,
            annual=True,
            market_cap=1000.0,
            statements=build_statements(self._year(400.0, 100.0), annual=True),
            trailing=build_statements(partial, annual=False),
        )
        assert built["valuation"]["basis"] == "annual"

    def test_a_caller_asking_for_quarters_still_gets_quarters(self):
        """With no trailing set supplied the caller's own basis stands.

        Asking for a quarterly view and being handed an annual valuation
        would be a surprise, not a default.
        """
        built = build_metrics(
            None,
            annual=False,
            market_cap=1000.0,
            statements=build_statements(
                self._quarters([30, 30, 30, 30], [10, 10, 10, 10]), annual=False
            ),
        )
        assert built["valuation"]["basis"] == "trailing twelve months"


# Alibaba's own reference row, as the terminal already fetches it.
BORROWED_STATS = {
    "revenue_ttm": 144.12e9,
    "enterprise_value": 274.56e9,
    "free_cash_flow": None,
    "price_earnings": 28.005,
    "price_to_sales": 1.88,
    "price_to_book": 1.846,
}


class TestBorrowedValuation:
    """Where the filings give no trailing year, somebody else's will do.

    A foreign private issuer files no 10-Q, so there are no quarters to
    trail. Alibaba's fiscal-year P/E of 19.79 is not the 28.01 the market is
    quoting, and the market's is the one worth showing — borrowed openly
    rather than derived, with the strip saying whose it is.
    """

    def _annual_only(self) -> dict:
        return facts(
            annual(REVENUE, [(2025, 400.0)]),
            annual("NetIncomeLoss", [(2025, 100.0)]),
        )

    def test_our_own_quarters_win(self):
        """Borrowing is the fallback, never the preference."""
        quarters = facts(
            usd(
                REVENUE,
                [
                    fact("2025-01-01", "2025-03-31", 30.0, filed="2025-05-01", form="10-Q"),
                    fact("2025-04-01", "2025-06-30", 30.0, filed="2025-08-01", form="10-Q"),
                    fact("2025-07-01", "2025-09-30", 30.0, filed="2025-11-01", form="10-Q"),
                    fact("2025-10-01", "2025-12-31", 30.0, filed="2026-02-01", form="10-Q"),
                ],
            ),
            usd(
                "NetIncomeLoss",
                [
                    fact("2025-01-01", "2025-03-31", 10.0, filed="2025-05-01", form="10-Q"),
                    fact("2025-04-01", "2025-06-30", 10.0, filed="2025-08-01", form="10-Q"),
                    fact("2025-07-01", "2025-09-30", 10.0, filed="2025-11-01", form="10-Q"),
                    fact("2025-10-01", "2025-12-31", 10.0, filed="2026-02-01", form="10-Q"),
                ],
            ),
        )
        built = build_metrics(
            None,
            annual=True,
            market_cap=1000.0,
            statements=build_statements(self._annual_only(), annual=True),
            trailing=build_statements(quarters, annual=False),
            stats=BORROWED_STATS,
        )
        assert built["valuation"]["source"] == "filings"
        by_key = {m["key"]: m["value"] for m in built["valuation"]["multiples"]}
        assert by_key["pe"] == pytest.approx(25.0)

    def test_the_reference_row_fills_in_when_there_are_no_quarters(self):
        built = build_metrics(
            None,
            annual=True,
            market_cap=1000.0,
            statements=build_statements(self._annual_only(), annual=True),
            trailing=build_statements(facts(), annual=False),
            stats=BORROWED_STATS,
        )
        assert built["valuation"]["source"] == "TradingView"
        assert built["valuation"]["basis"] == "trailing twelve months"
        by_key = {m["key"]: m["value"] for m in built["valuation"]["multiples"]}
        assert by_key["pe"] == pytest.approx(28.005)

    def test_a_missing_figure_is_still_refused(self):
        """Borrowing does not mean accepting whatever arrives."""
        built = build_metrics(
            None,
            annual=True,
            market_cap=1000.0,
            statements=build_statements(self._annual_only(), annual=True),
            trailing=build_statements(facts(), annual=False),
            stats=BORROWED_STATS,
        )
        by_key = {m["key"]: m["value"] for m in built["valuation"]["multiples"]}
        # Alibaba reports no free cash flow on that row.
        assert by_key["p_fcf"] is None

    def test_a_negative_multiple_is_refused_however_it_arrived(self):
        built = build_metrics(
            None,
            annual=True,
            market_cap=1000.0,
            statements=build_statements(self._annual_only(), annual=True),
            trailing=build_statements(facts(), annual=False),
            stats={**BORROWED_STATS, "price_earnings": -12.0},
        )
        by_key = {m["key"]: m["value"] for m in built["valuation"]["multiples"]}
        assert by_key["pe"] is None

    def test_the_fiscal_year_stands_when_there_is_nothing_to_borrow(self):
        built = build_metrics(
            None,
            annual=True,
            market_cap=1000.0,
            statements=build_statements(self._annual_only(), annual=True),
            trailing=build_statements(facts(), annual=False),
            stats={},
        )
        assert built["valuation"]["source"] == "filings"
        assert built["valuation"]["basis"] == "annual"
