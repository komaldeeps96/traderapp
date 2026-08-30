"""Our numbers, checked against people who publish their own.

Every test here reaches the network and is excluded from `pytest tests`.
Run it deliberately:

    cd backend && .venv/bin/pytest -m audit -p no:randomly

The two auditors answer different questions. **yfinance** reports in the
filer's own currency, so it checks the *parse*: the right concept, in the
right period, before anything is restated. **TradingView** publishes in USD,
so it checks the *conversion*. Passing one and failing the other localises a
fault immediately, which is the whole reason for using two.
"""

from __future__ import annotations

import pytest

from tests.audit.conftest import (
    CONVERTED_TOLERANCE,
    NATIVE_TOLERANCE,
    nearest,
    our_line,
    relative_difference,
    their_line,
)
from tests.audit.universe import UNIVERSE

pytestmark = pytest.mark.audit

SUBJECTS = [pytest.param(subject, id=subject.symbol) for subject in UNIVERSE]

# Our line, and the labels yfinance files it under, in priority order.
#
# Order matters more than it looks. yfinance publishes both an *adjusted*
# "Operating Income" and a "Total Operating Income As Reported", and only the
# second is the figure in the filing: for Crocs in 2025 they are $888M and
# $150M, the difference being a goodwill impairment. Comparing against the
# adjusted line makes the audit fail on thirty-eight true readings.
CHECKED = (
    ("revenue", "income", ("Total Revenue", "Operating Revenue")),
    ("net_income", "income", ("Net Income", "Net Income Common Stockholders")),
    ("gross_profit", "income", ("Gross Profit",)),
    (
        "operating_income",
        "income",
        ("Total Operating Income As Reported", "Operating Income"),
    ),
    ("total_assets", "balance", ("Total Assets",)),
    ("equity", "balance", ("Stockholders Equity", "Total Equity Gross Minority Interest")),
    ("operating_cash_flow", "cash", ("Operating Cash Flow",)),
)

# Equity is two different quantities and the concept that answered says
# which. AT&T does not report `StockholdersEquity` at all, so we fall back to
# the including-minority-interest concept — a real $16bn larger number that
# must be compared against the auditor's equivalent, not against the parent
# figure it is not.
EQUITY_LABEL_FOR_CONCEPT = {
    "StockholdersEquity": "Stockholders Equity",
    "EquityAttributableToOwnersOfParent": "Stockholders Equity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": (
        "Total Equity Gross Minority Interest"
    ),
    "Equity": "Total Equity Gross Minority Interest",
}

# Differences that are real and are not ours. Each needs a reason; the point
# of an audit is lost the moment this becomes a way to silence a failure.
# Periods where the SEC's own data cannot be made coherent, with the
# evidence. `companyfacts` strips the XBRL dimensions that separate one
# reporting entity from another, so a company that changed shell carries two
# balance sheets under one date and no way to tell them apart.
INCOHERENT_PERIODS: dict[tuple[str, str], str] = {
    ("CELU", "2020-12-31"): (
        "pre-merger: companyfacts holds both the SPAC's balance sheet "
        "(Assets 292,156,433, AssetsHeldInTrust 291,797,144) and Celularity's "
        "predecessor sheet (Assets 431,008,000) under the same date, and the "
        "dimensions that would separate them are not published"
    ),
}

EXPECTED_DIVERGENCE: dict[tuple[str, str], tuple[float, str]] = {
    ("JPM", "revenue"): (
        0.06,
        "a bank's 'revenue' has no single definition: we report the filed "
        "`Revenues`, yfinance a net figure after interest expense",
    ),
    ("T", "equity"): (
        0.02,
        "yfinance folds redeemable minority interests into equity; US GAAP "
        "keeps them in mezzanine. The gap is exactly AT&T's own $2.001bn of "
        "redeemable NCI, which we report on its own line",
    ),
    ("T", "operating_cash_flow"): (
        0.15,
        "AT&T restated 2022 cash flow for discontinued operations; the filed "
        "total and the continuing-operations figure differ by that amount",
    ),
}


def line_concepts(statements: dict, key: str) -> list[str]:
    for statement in statements.get("statements", []):
        for line in statement["lines"]:
            if line["key"] == key:
                return line["concepts"]
    return []


class TestTheParse:
    """Before conversion: did we read the right number out of the filing?"""

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_currency_is_detected_correctly(self, subject, our_statements, yahoo):
        """Everything downstream is wrong if this is."""
        if subject.no_annual_filings:
            pytest.skip(f"{subject.symbol}: {subject.note}")
        ours = our_statements(subject.symbol)["currency"]
        assert ours == subject.currency, f"{subject.symbol}: expected {subject.currency}"
        theirs = yahoo(subject.symbol)["currency"]
        if theirs:
            assert ours == theirs, f"{subject.symbol}: yfinance says {theirs}"

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_statement_lines_agree_with_yfinance(self, subject, our_statements, yahoo):
        """Line by line, period by period, in the filer's own currency."""
        statements = our_statements(subject.symbol)
        data = yahoo(subject.symbol)

        if subject.no_annual_filings:
            # Asserted rather than skipped: if the SEC starts publishing
            # annual data for this entity, that is news and the audit should
            # say so rather than quietly keep passing.
            assert not statements["periods"], (
                f"{subject.symbol} now has annual filings — remove "
                "no_annual_filings from the universe and let it be audited"
            )
            return

        if not data["frames"].get("income"):
            pytest.skip(f"yfinance has no statements for {subject.symbol}")

        compared = 0
        disagreements: list[str] = []
        for key, frame, labels in CHECKED:
            mine = our_line(statements, key)
            wanted = labels
            if key == "equity":
                used = line_concepts(statements, key)
                wanted = tuple(
                    dict.fromkeys(
                        [EQUITY_LABEL_FOR_CONCEPT[c] for c in used if c in EQUITY_LABEL_FOR_CONCEPT]
                        + list(labels)
                    )
                )
            theirs = their_line(data, frame, *wanted)
            if not mine or not theirs:
                continue

            allowed, reason = EXPECTED_DIVERGENCE.get((subject.symbol, key), (NATIVE_TOLERANCE, ""))
            for period_end, value in mine.items():
                other = nearest(theirs, period_end)
                if other is None:
                    continue
                compared += 1
                drift = relative_difference(value, other)
                if drift > allowed:
                    note = f" [allowed {allowed:.0%}: {reason}]" if reason else ""
                    disagreements.append(
                        f"{key} {period_end}: ours {value:,.0f} vs {other:,.0f} ({drift:.1%}){note}"
                    )

        assert compared >= 3, f"{subject.symbol}: only {compared} figures could be compared"
        assert not disagreements, f"{subject.symbol}:\n  " + "\n  ".join(disagreements)


class TestTheConversion:
    """After conversion: is the USD figure the one the market would quote?"""

    @pytest.mark.parametrize(
        "subject",
        [pytest.param(s, id=s.symbol) for s in UNIVERSE if s.currency != "USD"],
    )
    def test_converted_revenue_matches_tradingview(self, subject, our_statements):
        from tradingview_screener import Query, col

        converted = our_statements(subject.symbol, converted=True)
        assert converted["converted"] is True
        assert converted["currency"] == "USD"
        assert converted["native_currency"] == subject.currency

        revenue = our_line(converted, "revenue")
        assert revenue, f"{subject.symbol}: no converted revenue"
        latest = max(revenue)

        _, frame = (
            Query()
            .select("name", "total_revenue")
            .where(col("name") == subject.symbol)
            .limit(1)
            .get_scanner_data()
        )
        if frame.empty:
            pytest.skip(f"TradingView has no row for {subject.symbol}")
        theirs = float(frame["total_revenue"].iloc[0])

        drift = relative_difference(revenue[latest], theirs)
        assert drift <= CONVERTED_TOLERANCE, (
            f"{subject.symbol} {latest}: ours ${revenue[latest]:,.0f} vs "
            f"TradingView ${theirs:,.0f} ({drift:.1%})"
        )

    @pytest.mark.parametrize(
        "subject",
        [pytest.param(s, id=s.symbol) for s in UNIVERSE if s.currency == "USD"],
    )
    def test_a_dollar_filer_is_left_alone(self, subject, our_statements):
        """Converting what is already dollars would be a way to introduce
        error for nothing."""
        native = our_line(our_statements(subject.symbol), "revenue")
        converted = our_line(our_statements(subject.symbol, converted=True), "revenue")
        assert native == converted


class TestInternalConsistency:
    """Checks that need no outside source at all."""

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_the_accounting_identity_holds(self, subject, our_statements):
        """Assets = liabilities + equity, where all three were reported.

        Not a check on the filer — they balance — but on us: if the three
        lines are pulled from different periods or different concepts, this
        is what notices.
        """
        statements = our_statements(subject.symbol)
        assets = our_line(statements, "total_assets")
        liabilities = our_line(statements, "total_liabilities")
        equity = our_line(statements, "equity")
        # The two claims that sit outside shareholders' equity and still have
        # to be on the right-hand side: minority interests, and shares
        # subject to redemption. Without them Alibaba is out by 7.7% and a
        # SPAC-era balance sheet by 460%.
        #
        # Whether minorities are already inside `equity` depends on which
        # concept answered, and the two taxonomies disagree by default: IFRS
        # `Equity` includes them, US-GAAP `StockholdersEquity` does not.
        # Adding them blind double-counts exactly the filers it was meant to
        # fix.
        equity_concepts = set(line_concepts(statements, "equity"))
        minorities_already_inside = bool(
            equity_concepts
            & {
                "Equity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            }
        )
        minority = (
            {} if minorities_already_inside else our_line(statements, "noncontrolling_interest")
        )
        redeemable = our_line(statements, "temporary_equity")

        shared = set(assets) & set(liabilities) & set(equity)
        if not shared:
            pytest.skip(f"{subject.symbol} does not report all three")

        for period_end in shared:
            incoherent = INCOHERENT_PERIODS.get((subject.symbol, str(period_end)))
            if incoherent:
                continue
            total = (
                liabilities[period_end]
                + equity[period_end]
                + minority.get(period_end, 0.0)
                + redeemable.get(period_end, 0.0)
            )
            drift = relative_difference(assets[period_end], total)
            # A balance sheet balances exactly. Anything past a rounding
            # difference means three lines were read from different places.
            assert drift <= 0.005, (
                f"{subject.symbol} {period_end}: assets {assets[period_end]:,.0f} vs "
                f"liabilities+equity+minorities {total:,.0f} ({drift:.1%})"
            )

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_gross_profit_is_revenue_less_cost(self, subject, our_statements):
        statements = our_statements(subject.symbol)
        revenue = our_line(statements, "revenue")
        cost = our_line(statements, "cost_of_revenue")
        gross = our_line(statements, "gross_profit")
        shared = set(revenue) & set(cost) & set(gross)
        if not shared:
            pytest.skip(f"{subject.symbol} does not report all three")

        for period_end in shared:
            drift = relative_difference(gross[period_end], revenue[period_end] - cost[period_end])
            assert drift <= 0.02, (
                f"{subject.symbol} {period_end}: gross {gross[period_end]:,.0f} vs "
                f"revenue-cost {revenue[period_end] - cost[period_end]:,.0f} ({drift:.1%})"
            )

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_periods_are_distinct_and_ordered(self, subject, our_statements):
        """Newest first, no duplicates.

        A duplicated period label is what a polluted axis looks like from
        the outside, and it has happened twice.
        """
        periods = our_statements(subject.symbol)["periods"]
        ends = [period["end"] for period in periods]
        assert ends == sorted(ends, reverse=True)
        assert len({period["key"] for period in periods}) == len(periods)
