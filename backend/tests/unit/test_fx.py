"""Converting a foreign filer's statements into dollars.

Two rates per period, not one. IAS 21 puts income and expenses at the rate
on the transaction date — approximated by the average across the period, as
every provider does — and assets and liabilities at the closing rate on the
balance-sheet date. Using one rate for both is the common shortcut and it is
measurably wrong: against TradingView's own USD figures for Alibaba, the
period average lands within 0.06% and the closing rate is out by 2.94%.
"""

from __future__ import annotations

from datetime import date

from app.services.financials import build_statements, convert_to_usd
from tests.unit.test_financials import fact, ifrs


class FakeFx:
    """Rates without a network. Deliberately different per convention, so a
    test can tell which one a line was converted at."""

    CLOSING = 0.80
    AVERAGE = 0.70

    def __init__(self, *, fails: bool = False):
        self.fails = fails
        self.asked: list[tuple[str, str]] = []

    async def closing_rate(self, currency, on):
        self.asked.append(("closing", currency))
        if currency == "USD":
            return 1.0
        return None if self.fails else self.CLOSING

    async def average_rate(self, currency, start, end):
        self.asked.append(("average", currency))
        if currency == "USD":
            return 1.0
        return None if self.fails else self.AVERAGE


def canadian() -> dict:
    return {
        "facts": {
            "ifrs-full": {
                **ifrs("Revenue", [fact("2025-01-01", "2025-12-31", 1000.0, filed="2026-03-12")]),
                **ifrs("Assets", [fact(None, "2025-12-31", 2000.0, filed="2026-03-12")]),
                **ifrs(
                    "DilutedEarningsLossPerShare",
                    [fact("2025-01-01", "2025-12-31", 2.0, filed="2026-03-12")],
                    unit="CAD/shares",
                ),
                **ifrs(
                    "WeightedAverageNumberOfDilutedSharesOutstanding",
                    [fact("2025-01-01", "2025-12-31", 500.0, filed="2026-03-12")],
                    unit="shares",
                ),
            }
        }
    }


def line(built: dict, key: str) -> dict | None:
    for statement in built["statements"]:
        for item in statement["lines"]:
            if item["key"] == key:
                return item
    return None


class TestConventions:
    async def test_a_flow_takes_the_period_average(self):
        built = await convert_to_usd(build_statements(canadian(), annual=True), FakeFx())
        assert line(built, "revenue")["values"] == [1000.0 * FakeFx.AVERAGE]

    async def test_a_balance_takes_the_closing_rate(self):
        """A balance sheet is a photograph of one day, not a year."""
        built = await convert_to_usd(build_statements(canadian(), annual=True), FakeFx())
        assert line(built, "total_assets")["values"] == [2000.0 * FakeFx.CLOSING]

    async def test_earnings_per_share_is_a_flow(self):
        built = await convert_to_usd(build_statements(canadian(), annual=True), FakeFx())
        assert line(built, "eps_diluted")["values"] == [2.0 * FakeFx.AVERAGE]

    async def test_a_share_count_is_not_money_and_is_not_converted(self):
        """Shares are shares in every currency."""
        built = await convert_to_usd(build_statements(canadian(), annual=True), FakeFx())
        assert line(built, "shares_diluted")["values"] == [500.0]

    async def test_units_are_restated_too(self):
        built = await convert_to_usd(build_statements(canadian(), annual=True), FakeFx())
        assert line(built, "revenue")["unit"] == "USD"
        assert line(built, "eps_diluted")["unit"] == "USD/shares"
        assert line(built, "shares_diluted")["unit"] == "shares"


class TestDisclosure:
    async def test_the_original_currency_is_kept(self):
        """A converted number that cannot be traced to its filing is a
        number nobody can check."""
        built = await convert_to_usd(build_statements(canadian(), annual=True), FakeFx())
        assert built["currency"] == "USD"
        assert built["native_currency"] == "CAD"
        assert built["converted"] is True

    async def test_the_rates_used_travel_with_each_period(self):
        built = await convert_to_usd(build_statements(canadian(), annual=True), FakeFx())
        period = built["periods"][0]
        assert period["fx_average"] == FakeFx.AVERAGE
        assert period["fx_closing"] == FakeFx.CLOSING

    async def test_a_dollar_filer_is_not_converted_at_all(self):
        from tests.unit.test_financials import REVENUE, facts, usd

        data = facts(usd(REVENUE, [fact("2025-01-01", "2025-12-31", 10.0, filed="2026-02-01")]))
        fx = FakeFx()
        built = await convert_to_usd(build_statements(data, annual=True), fx)
        assert built["converted"] is False
        assert line(built, "revenue")["values"] == [10.0]
        # And no rate was ever asked for.
        assert fx.asked == []


class TestFailure:
    async def test_a_period_with_no_rate_is_left_out_and_named(self):
        """Better a missing column than a CAD figure in a dollar table."""
        built = await convert_to_usd(build_statements(canadian(), annual=True), FakeFx(fails=True))
        assert line(built, "revenue")["values"] == [None]
        assert built["unconverted_periods"] == ["FY2025"]

    async def test_nothing_reported_survives_conversion(self):
        built = await convert_to_usd(build_statements(None, annual=True), FakeFx())
        assert built["periods"] == []
        assert built["converted"] is False


class TestRatesAreRealDates:
    async def test_each_period_is_converted_at_its_own_rate(self):
        """A single current rate would push this year's exchange move back
        through ten years of history and call the result growth."""
        seen: list[tuple[date, date]] = []

        class Recording(FakeFx):
            async def average_rate(self, currency, start, end):
                seen.append((start, end))
                return 0.5

        data = {
            "facts": {
                "ifrs-full": ifrs(
                    "Revenue",
                    [
                        fact("2024-01-01", "2024-12-31", 100.0, filed="2025-03-01"),
                        fact("2025-01-01", "2025-12-31", 200.0, filed="2026-03-01"),
                    ],
                )
            }
        }
        await convert_to_usd(build_statements(data, annual=True), Recording())
        assert seen == [
            (date(2025, 1, 1), date(2025, 12, 31)),
            (date(2024, 1, 1), date(2024, 12, 31)),
        ]
