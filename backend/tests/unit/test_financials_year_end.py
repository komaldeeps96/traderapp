"""A filer with no revenue still has a fiscal year.

The year-end month was read from revenue, then from a balance-sheet line that
can never match an annual-flow search, so a pre-revenue company — common among
the small-cap biotechs this terminal watches — got ISO dates for quarter names.
"""

from __future__ import annotations

from app.domain.financials import build_statements
from tests.unit.test_financials import fact, facts, usd


def test_quarters_are_named_off_the_net_loss_when_there_is_no_revenue():
    rows = [
        fact("2024-10-01", "2025-09-30", -40.0, filed="2025-12-01"),
        fact("2025-10-01", "2025-12-31", -12.0, filed="2026-02-10", form="10-Q"),
        fact("2026-01-01", "2026-03-31", -11.0, filed="2026-05-10", form="10-Q"),
    ]
    built = build_statements(facts(usd("NetIncomeLoss", rows)), annual=False)
    assert [period["key"] for period in built["periods"]] == ["FY2026 Q2", "FY2026 Q1"]


def test_and_off_the_cash_burn_when_even_that_is_missing():
    rows = [
        fact("2024-07-01", "2025-06-30", -30.0, filed="2025-09-01"),
        fact("2025-07-01", "2025-09-30", -8.0, filed="2025-11-10", form="10-Q"),
    ]
    built = build_statements(
        facts(usd("NetCashProvidedByUsedInOperatingActivities", rows)), annual=False
    )
    assert built["periods"][0]["key"] == "FY2026 Q1"
