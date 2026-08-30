"""Ratios and valuation built on the statements.

The arithmetic is easy; what earns tests is everything this refuses to
compute. A margin on a missing revenue, a P/E on a loss, a growth rate off a
negative base — each is a number that would render, and each would be read as
information it is not.
"""

from __future__ import annotations

import pytest

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
