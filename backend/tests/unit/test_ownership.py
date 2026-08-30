"""Form 4s, read for what they mean.

Most of a Form 4 trail is payroll. The tests here are almost all about the
separation: a vest, an option exercise and shares withheld for tax are how a
person is paid, and counting them as "insider selling" is the single most
common way this data is misread.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.ownership import Intent
from app.services.ownership import parse_form4, raw_document_url, summarise

FILED = date(2026, 8, 27)
URL = "https://www.sec.gov/Archives/edgar/data/1/2/form4.xml"


def form4(
    *transactions: str,
    owner: str = "Doe Jane",
    officer: bool = True,
    director: bool = False,
    ten_percent: bool = False,
    title: str = "CFO",
    planned: bool = False,
) -> str:
    return f"""<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <periodOfReport>2026-08-25</periodOfReport>
  <issuer><issuerName>Test Inc.</issuerName></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>{owner}</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>{str(officer).lower()}</isOfficer>
      <isDirector>{str(director).lower()}</isDirector>
      <isTenPercentOwner>{str(ten_percent).lower()}</isTenPercentOwner>
      <officerTitle>{title}</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <aff10b5One>{str(planned).lower()}</aff10b5One>
  <nonDerivativeTable>{"".join(transactions)}</nonDerivativeTable>
</ownershipDocument>"""


def transaction(code: str, shares: float, price: float, acquired: str = "D", after: float = 1000):
    return f"""
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-08-25</value></transactionDate>
      <transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>{shares}</value></transactionShares>
        <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>{acquired}</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>{after}</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>"""


class TestDocumentUrl:
    def test_finds_the_machine_readable_sibling(self):
        rendered = "https://www.sec.gov/Archives/edgar/data/320193/0001/xslF345X06/form4.xml"
        assert raw_document_url(rendered).endswith("/0001/form4.xml")

    def test_a_url_that_is_already_raw_is_left_alone(self):
        plain = "https://www.sec.gov/Archives/edgar/data/320193/0001/form4.xml"
        assert raw_document_url(plain) == plain


class TestParsing:
    def test_reads_a_purchase(self):
        trade = parse_form4(form4(transaction("P", 500, 20.0, acquired="A")), FILED, URL)[0]
        assert (trade.intent, trade.code) == (Intent.BUY, "P")
        assert (trade.shares, trade.price, trade.value) == (500.0, 20.0, 10_000.0)
        assert trade.acquired is True

    def test_names_the_person_and_their_role(self):
        trade = parse_form4(form4(transaction("P", 1, 1.0), title="CEO"), FILED, URL)[0]
        assert trade.owner == "Doe Jane"
        assert "CEO" in trade.role

    def test_collects_every_role_held(self):
        xml = form4(transaction("P", 1, 1.0), director=True, ten_percent=True, title="Chair")
        assert parse_form4(xml, FILED, URL)[0].role == "Chair, director, 10% owner"

    def test_a_ten_percent_holder_with_no_title(self):
        xml = form4(transaction("P", 1, 1.0), officer=False, ten_percent=True, title="")
        assert parse_form4(xml, FILED, URL)[0].role == "10% owner"

    def test_marks_a_planned_sale(self):
        trade = parse_form4(form4(transaction("S", 100, 10.0), planned=True), FILED, URL)[0]
        assert trade.planned is True

    def test_a_purchase_under_a_plan_is_still_a_purchase(self):
        """A plan excuses a sale. It does not excuse cash out of pocket."""
        trade = parse_form4(form4(transaction("P", 100, 10.0), planned=True), FILED, URL)[0]
        assert trade.intent is Intent.BUY
        assert trade.planned is False

    @pytest.mark.parametrize(
        ("code", "intent"),
        [
            ("P", Intent.BUY),
            ("S", Intent.SELL),
            ("A", Intent.COMPENSATION),
            ("M", Intent.COMPENSATION),
            ("F", Intent.COMPENSATION),
            ("G", Intent.OTHER),
            ("Z", Intent.OTHER),
        ],
    )
    def test_classifies_the_codes(self, code, intent):
        assert parse_form4(form4(transaction(code, 1, 1.0)), FILED, URL)[0].intent is intent

    def test_reads_every_line_of_one_form(self):
        xml = form4(transaction("M", 800, 0.0), transaction("F", 260, 1.28))
        assert len(parse_form4(xml, FILED, URL)) == 2

    def test_a_derivative_table_is_not_double_counted(self):
        """An option grant and its later exercise are one piece of pay."""
        xml = form4(transaction("A", 100, 0.0)).replace(
            "</nonDerivativeTable>",
            "</nonDerivativeTable><derivativeTable>"
            + transaction("A", 999, 0.0).replace(
                "nonDerivativeTransaction", "derivativeTransaction"
            )
            + "</derivativeTable>",
        )
        trades = parse_form4(xml, FILED, URL)
        assert [trade.shares for trade in trades] == [100.0]

    def test_an_unparseable_document_is_skipped(self):
        assert parse_form4("<not xml", FILED, URL) == []

    def test_a_transaction_with_no_code_is_skipped(self):
        assert parse_form4(form4(transaction("", 1, 1.0)), FILED, URL) == []

    def test_a_missing_price_leaves_the_value_unknown(self):
        xml = form4(transaction("M", 800, 0.0)).replace(
            "<transactionPricePerShare><value>0.0</value></transactionPricePerShare>", ""
        )
        trade = parse_form4(xml, FILED, URL)[0]
        assert trade.price is None
        assert trade.value is None


class TestSummary:
    TODAY = date(2026, 8, 27)

    def _trades(self, *xml: str):
        out = []
        for document in xml:
            out.extend(parse_form4(document, FILED, URL))
        return out

    def test_compensation_is_kept_out_of_the_net(self):
        """A vest and a purchase are not the same act.

        This is the misreading the whole module exists to prevent: a naive
        tracker counts tax withholding as selling and reports an exodus.
        """
        trades = self._trades(form4(transaction("M", 800, 0.0), transaction("F", 260, 10.0)))
        read = summarise(trades, self.TODAY)
        assert read["compensation"]["count"] == 2
        assert read["net_value"] == 0
        assert read["verdict"] == "No open-market insider activity in the window."

    def test_a_planned_sale_is_kept_out_of_the_net(self):
        trades = self._trades(form4(transaction("S", 1000, 10.0), planned=True))
        read = summarise(trades, self.TODAY)
        assert read["planned_sells"]["count"] == 1
        assert read["discretionary_sells"]["count"] == 0
        assert read["net_value"] == 0

    def test_a_discretionary_sale_counts_against(self):
        trades = self._trades(form4(transaction("S", 1000, 10.0)))
        assert summarise(trades, self.TODAY)["net_value"] == -10_000.0

    def test_buying_nets_positive(self):
        trades = self._trades(form4(transaction("P", 1000, 10.0, acquired="A")))
        read = summarise(trades, self.TODAY)
        assert read["net_value"] == 10_000.0
        assert read["verdict"] == "an insider bought at the market and none sold."

    def test_counts_distinct_people_not_filings(self):
        """Three directors buying is a different fact from one buying thrice."""
        trades = self._trades(
            form4(transaction("P", 100, 10.0, acquired="A"), owner="A One"),
            form4(transaction("P", 100, 10.0, acquired="A"), owner="B Two"),
            form4(transaction("P", 100, 10.0, acquired="A"), owner="B Two"),
        )
        read = summarise(trades, self.TODAY)
        assert read["buys"]["count"] == 3
        assert read["buys"]["people"] == 2
        assert read["verdict"] == "2 insiders bought at the market and none sold."

    def test_only_the_window_counts(self):
        old = parse_form4(form4(transaction("P", 1000, 10.0, acquired="A")), FILED, URL)
        stale = [
            trade.__class__(
                **{**{f: getattr(trade, f) for f in trade.__slots__}, "traded": date(2025, 1, 1)}
            )
            for trade in old
        ]
        assert summarise(stale, self.TODAY)["buys"]["count"] == 0

    def test_both_sides_is_said_plainly(self):
        trades = self._trades(
            form4(transaction("P", 100, 10.0, acquired="A"), owner="A One"),
            form4(transaction("S", 100, 10.0), owner="B Two"),
        )
        assert summarise(trades, self.TODAY)["verdict"] == "Insiders on both sides of the market."

    def test_an_empty_trail_is_not_an_error(self):
        read = summarise([], self.TODAY)
        assert read["net_value"] == 0
        assert read["buys"]["count"] == 0
