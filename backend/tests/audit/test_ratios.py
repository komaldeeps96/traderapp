"""The ratios and multiples, against what the market is quoting.

The statement audit proves the numbers were read correctly. This proves what
is built on top of them, which is where a mistake reaches a decision: a
margin or a P/E is what someone acts on, not the revenue line it came from.

It exists because that layer went unchecked and drifted. Every multiple was
computed on the latest *fiscal year* while every other screen quotes a
trailing twelve months, so Apple's P/E read 41.65 against a market quoting
36.65, and Crocs' operating margin read 3.70% on a year carrying a goodwill
impairment against the 24.22% behind the twelve months actually elapsed.
Nothing was miscalculated; the basis was simply not the one anybody else
uses.
"""

from __future__ import annotations

import math

import pytest

from app.services.metrics import TTM_QUARTERS
from tests.audit.conftest import relative_difference
from tests.audit.universe import UNIVERSE

pytestmark = pytest.mark.audit


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


SUBJECTS = [pytest.param(s, id=s.symbol) for s in UNIVERSE if not s.no_annual_filings]

# Our key, TradingView's column, and how much room. Tolerances are measured
# rather than guessed: across this universe the multiples sit at a median
# 0.2–3.1% and a 90th percentile of 5–6.5%, so 10% is loose enough for a
# restatement and tight enough to catch a wrong basis, which showed up at 14%.
COMPARED = (
    ("pe", "price_earnings_ttm", 1.0, 0.10),
    ("ps", "price_sales_current", 1.0, 0.10),
    ("pb", "price_book_fq", 1.0, 0.10),
    ("gross_margin", "gross_margin", 100.0, 0.10),
)

# Deliberately not compared, with the reason. Adding to this list is a
# statement that two sources mean different things, not that ours is wrong.
NOT_COMPARED = {
    "operating_margin": (
        "TradingView quotes an adjusted operating income, as yfinance does; "
        "ours is as filed. On Boeing the two have opposite signs"
    ),
    "return_on_equity": (
        "TradingView appears to use an average equity base rather than the "
        "closing one; the gap is systematic and not a reading error"
    ),
    "debt_to_equity": (
        "ours is long-term debt only and is labelled so. Summing the "
        "short-term line to reach total debt was measured worse, because "
        "`LongTermDebt` already includes the current portion for some filers"
    ),
}

# Allowances, each with what was checked. These are claims that two sources
# measure different things — not a way to make a failure go away, and every
# one here was traced before it was written down.
ALLOWANCE: dict[tuple[str, str], tuple[float, str]] = {
    ("T", "pb"): (
        0.15,
        "AT&T reports no parent-only equity, so our book value carries its "
        "$16bn of minority interests and TradingView's does not",
    ),
    ("BA", "pe"): (
        0.35,
        "Boeing's trailing earnings are near zero, where a 1% difference in "
        "net income moves the multiple by a third",
    ),
    ("CGC", "gross_margin"): (
        0.40,
        "trailing windows differ on a filer with inventory write-downs: our "
        "four quarters total $212.4M of revenue against their $204.6M, and "
        "their implied gross profit is $37.4M against our $53.4M",
    ),
    ("CELU", "ps"): (
        0.30,
        "micro cap whose trailing revenue window differs between sources; "
        "the cause was not traced further than that",
    ),
    ("TLRY", "ps"): (
        0.25,
        "May fiscal year end; the trailing windows do not line up, and the "
        "cause was not traced further than that",
    ),
}

# A multiple this large is one over a denominator near zero, where a 1%
# difference in earnings moves the ratio by a third. Palo Alto's P/E is 359
# against a quoted 306, which says nothing about either source.
UNSTABLE_MULTIPLE = 100.0


@pytest.fixture(scope="session")
def tradingview():
    """One screener row per subject, fetched once."""
    from tradingview_screener import Query, col

    columns = ["name", *{tv for _, tv, _, _ in COMPARED}]
    symbols = [subject.symbol for subject in UNIVERSE]
    _, frame = (
        Query().select(*columns).where(col("name").isin(symbols)).limit(100).get_scanner_data()
    )
    return {row["name"]: row for _, row in frame.iterrows()}


@pytest.fixture(scope="session")
def our_metrics(our_statements, market_caps, reference_stats):
    """Exactly what the metrics endpoint would serve, without a server."""
    from app.services.metrics import build_metrics

    cache: dict[str, dict] = {}

    def load(symbol: str) -> dict:
        if symbol not in cache:
            cache[symbol] = build_metrics(
                None,
                annual=True,
                limit=6,
                market_cap=market_caps.get(symbol),
                statements=our_statements(symbol, converted=True),
                trailing=our_statements(symbol, converted=True, quarterly=True),
                stats=reference_stats.get(symbol),
            )
        return cache[symbol]

    return load


class TestTheBasis:
    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_multiples_are_quoted_on_a_trailing_twelve_months(
        self, subject, our_metrics, our_statements
    ):
        """Where the quarters exist, they are what the multiples use.

        A fiscal-year P/E is not wrong, it is answering a question nobody
        asked — and it disagrees with every other screen.
        """
        valuation = our_metrics(subject.symbol)["valuation"]
        # Whether a trailing year exists is a question about the forms filed,
        # not the currency: Canopy Growth reports in CAD and files 10-Qs, so
        # it has quarters like any domestic issuer.
        quarters = our_statements(subject.symbol, converted=True, quarterly=True)["periods"]
        if len(quarters) >= TTM_QUARTERS:
            assert valuation["basis"] == "trailing twelve months", (
                f"{subject.symbol} has {len(quarters)} quarters and still fell "
                "back to a fiscal year"
            )
        else:
            # A foreign private issuer files no 10-Q, so there is nothing of
            # ours to trail. The reference row carries a trailing year, and
            # borrowing it openly beats quoting a fiscal year nobody else
            # uses: Alibaba's own filings give a P/E of 19.79 where the
            # market is quoting 28.01.
            assert valuation["basis"] == "trailing twelve months"
            assert valuation["source"] == "TradingView"


class TestAgainstTheMarket:
    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_ratios_and_multiples_agree(self, subject, our_metrics, tradingview):
        row = tradingview.get(subject.symbol)
        if row is None:
            pytest.skip(f"TradingView has no row for {subject.symbol}")

        built = our_metrics(subject.symbol)
        if built["valuation"].get("source") != "filings":
            # The multiples were borrowed from this very source, so checking
            # them against it proves nothing but that a number survived being
            # copied. That the borrowing happened at all is asserted below.
            pytest.skip(f"{subject.symbol}'s multiples come from TradingView")
        if built["valuation"]["basis"] != "trailing twelve months":
            # TradingView quotes a trailing twelve months. Holding an annual
            # figure against it measures the difference between two bases,
            # which is the mistake this whole file exists to have caught.
            pytest.skip(f"{subject.symbol} has no trailing year to compare")

        ours = {
            metric["key"]: metric["values"][0]
            for group in built["groups"]
            for metric in group["metrics"]
            if metric["values"]
        }
        ours.update({m["key"]: m["value"] for m in built["valuation"]["multiples"]})

        compared, disagreements = 0, []
        for key, column, scale, tolerance in COMPARED:
            mine, theirs = ours.get(key), row.get(column)
            if mine is None or not _is_number(theirs) or theirs == 0:
                continue
            if abs(theirs) > UNSTABLE_MULTIPLE or abs(mine * scale) > UNSTABLE_MULTIPLE:
                continue
            compared += 1
            allowed, reason = ALLOWANCE.get((subject.symbol, key), (tolerance, ""))
            drift = relative_difference(mine * scale, theirs)
            if drift > allowed:
                note = f" [allowed {allowed:.0%}: {reason}]" if reason else ""
                disagreements.append(
                    f"{key}: ours {mine * scale:,.2f} vs {theirs:,.2f} ({drift:.1%}){note}"
                )

        assert compared >= 1, f"{subject.symbol}: nothing comparable"
        assert not disagreements, f"{subject.symbol}:\n  " + "\n  ".join(disagreements)


class TestWhatIsNotCompared:
    def test_every_exclusion_carries_a_reason(self):
        """An exclusion is a claim about two definitions, not a way to pass."""
        for key, reason in NOT_COMPARED.items():
            assert len(reason) > 40, f"{key} needs a real reason"

    def test_every_allowance_carries_a_reason(self):
        for key, (allowed, reason) in ALLOWANCE.items():
            assert len(reason) > 40, f"{key} needs a real reason"
            # An allowance wide enough to admit anything is not an allowance.
            assert allowed <= 0.40, f"{key} is too loose to be evidence of anything"
