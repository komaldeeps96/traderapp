"""Statements built from EDGAR ``companyfacts``.

Every fixture here is shaped like the real thing, because the traps in this
data are all shape: a fact's ``fy`` belongs to the filing that carried it, a
10-Q reports the quarter and the year to date in the same list, and a concept
can stop mid-history and continue under another name.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.financials import build_statements, fiscal_year_of


def usd(concept: str, rows: list[dict], unit: str = "USD") -> dict:
    return {concept: {"units": {unit: rows}}}


def fact(start: str | None, end: str, val: float, *, filed: str, form: str = "10-K", **extra):
    row = {"end": end, "val": val, "filed": filed, "form": form, **extra}
    if start is not None:
        row["start"] = start
    return row


def facts(*concept_maps: dict) -> dict:
    merged: dict = {}
    for entry in concept_maps:
        merged.update(entry)
    return {"facts": {"us-gaap": merged}}


REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"

# Revenue as a filer actually reports it: three quarters stated, the
# year-to-date figures beside them, and the year itself in the 10-K. That
# is what lets the fourth quarter be derived, and so what gives the table
# a fourth column for a non-additive line to be missing from.
REVENUE_ROWS = [
    fact("2025-01-01", "2025-03-31", 10.0, filed="2025-05-01", form="10-Q"),
    fact("2025-04-01", "2025-06-30", 12.0, filed="2025-08-01", form="10-Q"),
    fact("2025-07-01", "2025-09-30", 13.0, filed="2025-11-01", form="10-Q"),
    fact("2025-01-01", "2025-06-30", 22.0, filed="2025-08-01", form="10-Q"),
    fact("2025-01-01", "2025-09-30", 35.0, filed="2025-11-01", form="10-Q"),
    fact("2025-01-01", "2025-12-31", 50.0, filed="2026-02-01"),
]


def line(built: dict, key: str) -> dict | None:
    for statement in built["statements"]:
        for item in statement["lines"]:
            if item["key"] == key:
                return item
    return None


class TestPeriodIdentity:
    def test_a_comparative_lands_in_its_own_year(self):
        """``fy`` names the filing, not the fact.

        Apple's FY2016 revenue is carried by the FY2018 10-K tagged
        ``fy: 2018``. Keying on that field files six years of history under
        one heading and loses the rest.
        """
        data = facts(
            usd(
                REVENUE,
                [
                    fact("2016-01-01", "2016-12-31", 100.0, filed="2018-02-01", fy=2018, fp="FY"),
                    fact("2017-01-01", "2017-12-31", 200.0, filed="2018-02-01", fy=2018, fp="FY"),
                ],
            )
        )
        built = build_statements(data, annual=True)
        assert [period["key"] for period in built["periods"]] == ["FY2017", "FY2016"]
        assert line(built, "revenue")["values"] == [200.0, 100.0]

    def test_a_restatement_wins(self):
        """The newest statement of a period is the one to believe."""
        data = facts(
            usd(
                REVENUE,
                [
                    fact("2024-01-01", "2024-12-31", 100.0, filed="2025-02-01"),
                    fact("2024-01-01", "2024-12-31", 111.0, filed="2026-02-01"),
                ],
            )
        )
        assert line(build_statements(data, annual=True), "revenue")["values"] == [111.0]

    def test_a_year_to_date_figure_is_not_a_quarter(self):
        """A 10-Q reports the quarter and the year so far, in one list.

        Letting the cumulative ones through makes a quarterly series that
        grows through the year and then resets.
        """
        data = facts(
            usd(
                REVENUE,
                [
                    fact("2025-01-01", "2025-03-31", 10.0, filed="2025-05-01", form="10-Q"),
                    fact("2025-04-01", "2025-06-30", 12.0, filed="2025-08-01", form="10-Q"),
                    # The half-year, filed alongside the second quarter.
                    fact("2025-01-01", "2025-06-30", 22.0, filed="2025-08-01", form="10-Q"),
                ],
            )
        )
        built = build_statements(data, annual=False)
        assert line(built, "revenue")["values"] == [12.0, 10.0]

    def test_a_quarter_is_not_a_year(self):
        data = facts(
            usd(
                REVENUE,
                [
                    fact("2025-01-01", "2025-03-31", 10.0, filed="2025-05-01", form="10-Q"),
                    fact("2025-01-01", "2025-12-31", 50.0, filed="2026-02-01"),
                ],
            )
        )
        assert line(build_statements(data, annual=True), "revenue")["values"] == [50.0]


class TestDerivedQuarters:
    """The quarters no form ever carried."""

    def test_the_fourth_quarter_comes_from_the_year(self):
        """No 10-Q is filed for Q4; the 10-K covers it.

        Without this the last quarter of every year is a blank column.
        """
        rows = [
            fact("2025-01-01", "2025-03-31", 10.0, filed="2025-05-01", form="10-Q"),
            fact("2025-01-01", "2025-06-30", 22.0, filed="2025-08-01", form="10-Q"),
            fact("2025-01-01", "2025-09-30", 35.0, filed="2025-11-01", form="10-Q"),
            fact("2025-01-01", "2025-12-31", 50.0, filed="2026-02-01"),
        ]
        built = build_statements(facts(usd(REVENUE, rows)), annual=False)
        # Q1 as filed, then each successive difference — Q4 is 50 − 35.
        assert line(built, "revenue")["values"] == [15.0, 13.0, 12.0, 10.0]

    def test_quarterly_cash_flow_comes_from_the_year_to_date(self):
        """A 10-Q states cash flow for the year so far, never the quarter.

        So a three-month cash-flow fact frequently does not exist at all, and
        the whole line would otherwise be empty on a quarterly view.
        """
        rows = [
            fact("2025-01-01", "2025-03-31", 5.0, filed="2025-05-01", form="10-Q"),
            fact("2025-01-01", "2025-06-30", 11.0, filed="2025-08-01", form="10-Q"),
        ]
        built = build_statements(
            facts(usd("NetCashProvidedByUsedInOperatingActivities", rows)), annual=False
        )
        assert line(built, "operating_cash_flow")["values"] == [6.0, 5.0]

    def test_what_the_company_stated_wins_over_the_arithmetic(self):
        rows = [
            fact("2025-01-01", "2025-03-31", 10.0, filed="2025-05-01", form="10-Q"),
            fact("2025-04-01", "2025-06-30", 99.0, filed="2025-08-01", form="10-Q"),
            # The cumulative implies a second quarter of 12, not 99.
            fact("2025-01-01", "2025-06-30", 22.0, filed="2025-08-01", form="10-Q"),
        ]
        built = build_statements(facts(usd(REVENUE, rows)), annual=False)
        assert line(built, "revenue")["values"][0] == 99.0

    def test_an_average_is_never_derived(self):
        """A weighted average is not a flow and does not difference.

        Taking a nine-month average share count from a twelve-month one gives
        a negative number of shares, which is what the terminal drew before
        this: "-47.0M diluted shares" in Apple's fourth quarter. A blank is
        the honest answer — that quarter's average is in no filing.
        """
        data = facts(
            usd(REVENUE, REVENUE_ROWS),
            usd(
                "WeightedAverageNumberOfDilutedSharesOutstanding",
                [
                    fact("2025-01-01", "2025-03-31", 1000.0, filed="2025-05-01", form="10-Q"),
                    fact("2025-04-01", "2025-06-30", 990.0, filed="2025-08-01", form="10-Q"),
                    fact("2025-07-01", "2025-09-30", 980.0, filed="2025-11-01", form="10-Q"),
                    fact("2025-01-01", "2025-12-31", 985.0, filed="2026-02-01"),
                ],
                unit="shares",
            ),
        )
        built = build_statements(data, annual=False)
        # The fourth quarter is derived for revenue and blank for the average.
        assert line(built, "revenue")["values"] == [15.0, 13.0, 12.0, 10.0]
        assert line(built, "shares_diluted")["values"] == [None, 980.0, 990.0, 1000.0]

    def test_earnings_per_share_is_never_derived(self):
        """A ratio is not a flow either, however nearly the quarters sum."""
        data = facts(
            usd(REVENUE, REVENUE_ROWS),
            usd(
                "EarningsPerShareDiluted",
                [
                    fact("2025-01-01", "2025-03-31", 2.40, filed="2025-05-01", form="10-Q"),
                    fact("2025-04-01", "2025-06-30", 1.65, filed="2025-08-01", form="10-Q"),
                    fact("2025-07-01", "2025-09-30", 1.57, filed="2025-11-01", form="10-Q"),
                    fact("2025-01-01", "2025-12-31", 7.46, filed="2026-02-01"),
                ],
                unit="USD/shares",
            ),
        )
        built = build_statements(data, annual=False)
        assert line(built, "eps_diluted")["values"] == [None, 1.57, 1.65, 2.40]

    def test_the_annual_view_is_never_derived(self):
        """Differencing is a quarterly device; a year is filed as a year."""
        rows = [
            fact("2025-01-01", "2025-03-31", 10.0, filed="2025-05-01", form="10-Q"),
            fact("2025-01-01", "2025-06-30", 22.0, filed="2025-08-01", form="10-Q"),
        ]
        built = build_statements(facts(usd(REVENUE, rows)), annual=True)
        assert built["periods"] == []


class TestConceptChains:
    def test_a_concept_that_stops_is_continued_by_the_next(self):
        """ASC 606 ended ``Revenues`` mid-history for a great many filers.

        Resolving the chain to whichever concept answers first returns half a
        series; they are merged period by period instead.
        """
        data = facts(
            usd(REVENUE, [fact("2025-01-01", "2025-12-31", 200.0, filed="2026-02-01")]),
            usd("Revenues", [fact("2017-01-01", "2017-12-31", 100.0, filed="2018-02-01")]),
        )
        built = build_statements(data, annual=True)
        assert line(built, "revenue")["values"] == [200.0, 100.0]
        assert line(built, "revenue")["concepts"] == [REVENUE, "Revenues"]

    def test_the_first_concept_wins_where_both_report(self):
        data = facts(
            usd(REVENUE, [fact("2025-01-01", "2025-12-31", 200.0, filed="2026-02-01")]),
            usd("Revenues", [fact("2025-01-01", "2025-12-31", 999.0, filed="2026-02-01")]),
        )
        assert line(build_statements(data, annual=True), "revenue")["values"] == [200.0]


class TestUnits:
    def test_earnings_per_share_is_not_mixed_with_dollars(self):
        """One concept can be reported in more than one unit.

        Merging them puts 1.50 in the same line as 1.5 billion.
        """
        data = {
            "facts": {
                "us-gaap": {
                    "EarningsPerShareDiluted": {
                        "units": {
                            "USD/shares": [
                                fact("2025-01-01", "2025-12-31", 1.5, filed="2026-02-01")
                            ],
                            "USD": [fact("2025-01-01", "2025-12-31", 1.5e9, filed="2026-02-01")],
                        }
                    }
                }
            }
        }
        assert line(build_statements(data, annual=True), "eps_diluted")["values"] == [1.5]


class TestBalanceSheet:
    def test_a_balance_does_not_add_columns_of_its_own(self):
        """A balance sheet is filed every quarter; a year has four of them.

        Letting instants set the axis puts three columns between one annual
        close and the next, each holding a balance and nothing else.
        """
        data = facts(
            usd(REVENUE, [fact("2025-01-01", "2025-12-31", 50.0, filed="2026-02-01")]),
            usd(
                "Assets",
                [
                    fact(None, "2025-03-31", 10.0, filed="2025-05-01", form="10-Q"),
                    fact(None, "2025-06-30", 11.0, filed="2025-08-01", form="10-Q"),
                    fact(None, "2025-12-31", 13.0, filed="2026-02-01"),
                ],
            ),
        )
        built = build_statements(data, annual=True)
        assert [period["key"] for period in built["periods"]] == ["FY2025"]
        assert line(built, "total_assets")["values"] == [13.0]

    def test_a_balance_is_read_at_the_period_end(self):
        data = facts(
            usd(REVENUE, [fact("2025-01-01", "2025-12-31", 50.0, filed="2026-02-01")]),
            usd("Assets", [fact(None, "2025-06-30", 11.0, filed="2025-08-01", form="10-Q")]),
        )
        # Nothing was reported on 31 December, so the column stays blank
        # rather than borrowing the nearest balance from mid-year.
        assert line(build_statements(data, annual=True), "total_assets")["values"] == [None]


class TestFiscalYears:
    @pytest.mark.parametrize(
        ("end", "expected"),
        [
            ("2025-09-27", 2025),  # Apple, September year end
            ("2026-01-31", 2026),  # Walmart and Salesforce both call this FY2026
            ("2025-12-31", 2025),
        ],
    )
    def test_named_for_the_year_it_closes_in(self, end, expected):
        from datetime import date

        assert fiscal_year_of(date.fromisoformat(end)) == expected

    def test_quarters_belong_to_the_year_that_closes_after_them(self):
        """A September-year-end company's December quarter is Q1.

        The quarter is numbered from the month the fiscal year closes, not
        from January.
        """
        rows = [
            fact("2024-09-29", "2025-09-27", 400.0, filed="2025-10-31"),
            fact("2025-09-28", "2025-12-27", 140.0, filed="2026-01-30", form="10-Q"),
            fact("2025-12-28", "2026-03-28", 110.0, filed="2026-05-01", form="10-Q"),
        ]
        built = build_statements(facts(usd(REVENUE, rows)), annual=False)
        assert [period["key"] for period in built["periods"]] == ["FY2026 Q2", "FY2026 Q1"]

    def test_a_fiscal_close_that_drifts_past_month_end_still_counts(self):
        """Fiscal calendars run in weeks, so a quarter can close on 3 May.

        Reading the month off the end date directly would put that quarter in
        the following one.
        """
        rows = [
            fact("2025-02-01", "2026-01-31", 400.0, filed="2026-03-01"),
            fact("2026-02-01", "2026-05-03", 100.0, filed="2026-06-01", form="10-Q"),
        ]
        built = build_statements(facts(usd(REVENUE, rows)), annual=False)
        assert built["periods"][0]["key"] == "FY2027 Q1"


class TestEmptiness:
    @pytest.mark.parametrize("payload", [None, {}, {"facts": {}}, {"facts": {"us-gaap": {}}}])
    def test_nothing_reported_is_not_an_error(self, payload):
        built = build_statements(payload, annual=True)
        assert built["periods"] == []
        assert built["statements"] == []
        # A filer with nothing on record is assumed to report in dollars,
        # which is what an empty table is captioned with.
        assert built["currency"] == "USD"

    def test_a_malformed_entry_is_skipped_rather_than_fatal(self):
        data = facts(
            usd(
                REVENUE,
                [
                    {"start": "2025-01-01", "end": "not-a-date", "val": 1, "filed": "2026-01-01"},
                    {"start": "2025-01-01", "end": "2025-12-31", "val": None, "filed": "x"},
                    {"start": "2025-01-01", "end": "2025-12-31", "val": True, "filed": "x"},
                    fact("2024-01-01", "2024-12-31", 7.0, filed="2025-02-01"),
                ],
            )
        )
        assert line(build_statements(data, annual=True), "revenue")["values"] == [7.0]


def ifrs(concept: str, rows: list[dict], unit: str = "CAD") -> dict:
    """A concept under the IFRS taxonomy, in a filer's own currency."""
    return {concept: {"units": {unit: rows}}}


def facts_ifrs(*concept_maps: dict) -> dict:
    merged: dict = {}
    for entry in concept_maps:
        merged.update(entry)
    return {"facts": {"ifrs-full": merged}}


class TestForeignPrivateIssuers:
    """A 40-F or 20-F filer tags under `ifrs-full`, not `us-gaap`.

    Its facts sit in the same free `companyfacts` payload the terminal
    already fetches for every symbol — the tabs were empty only because the
    parser looked in one taxonomy. This is most of the Canadian small-cap
    universe.
    """

    def test_reads_a_statement_tagged_under_ifrs(self):
        data = facts_ifrs(
            ifrs(
                "Revenue",
                [fact("2025-01-01", "2025-12-31", 946.0, filed="2026-03-12", form="40-F")],
            ),
            ifrs(
                "ProfitLoss",
                [fact("2025-01-01", "2025-12-31", -16.0, filed="2026-03-12", form="40-F")],
            ),
        )
        built = build_statements(data, annual=True)
        assert line(built, "revenue")["values"] == [946.0]
        assert line(built, "net_income")["values"] == [-16.0]

    def test_reports_the_currency_it_was_filed_in(self):
        data = facts_ifrs(
            ifrs("Assets", [fact(None, "2025-12-31", 1336.0, filed="2026-03-12", form="40-F")]),
        )
        assert build_statements(data, annual=True)["currency"] == "CAD"

    def test_a_us_filer_is_still_dollars(self):
        data = facts(usd("Assets", [fact(None, "2025-12-31", 1.0, filed="2026-02-01")]))
        assert build_statements(data, annual=True)["currency"] == "USD"

    def test_earnings_per_share_is_found_in_the_filers_currency(self):
        """The unit key is "CAD/shares", not "USD/shares"."""
        data = facts_ifrs(
            ifrs("Revenue", [fact("2025-01-01", "2025-12-31", 946.0, filed="2026-03-12")]),
            ifrs(
                "DilutedEarningsLossPerShare",
                [fact("2025-01-01", "2025-12-31", -0.06, filed="2026-03-12")],
                unit="CAD/shares",
            ),
        )
        built = build_statements(data, annual=True)
        assert line(built, "eps_diluted")["values"] == [-0.06]
        assert line(built, "eps_diluted")["unit"] == "CAD/shares"

    def test_a_taxonomy_switch_makes_one_continuous_series(self):
        """Canopy Growth carries both, having moved from IFRS to US GAAP.

        Branching on taxonomy would return whichever half was checked first;
        merging the chains period by period returns the whole history, the
        same way the ASC 606 break is handled.
        """
        data = {
            "facts": {
                "us-gaap": usd(
                    REVENUE, [fact("2025-01-01", "2025-12-31", 285.0, filed="2026-02-01")]
                ),
                "ifrs-full": ifrs(
                    "Revenue",
                    [fact("2022-01-01", "2022-12-31", 476.0, filed="2023-02-01")],
                    unit="USD",
                ),
            }
        }
        built = build_statements(data, annual=True)
        assert line(built, "revenue")["values"] == [285.0, 476.0]

    def test_us_gaap_wins_where_both_report_the_same_year(self):
        """A filer stating both is reporting to US investors in the second."""
        data = {
            "facts": {
                "us-gaap": usd(
                    REVENUE, [fact("2025-01-01", "2025-12-31", 285.0, filed="2026-02-01")]
                ),
                "ifrs-full": ifrs(
                    "Revenue",
                    [fact("2025-01-01", "2025-12-31", 999.0, filed="2026-02-01")],
                    unit="USD",
                ),
            }
        }
        assert line(build_statements(data, annual=True), "revenue")["values"] == [285.0]


class TestCurrencyDetection:
    def test_dollars_win_a_tie(self):
        """A filer stating both is reporting to US investors in the dollars."""
        from app.services.financials import reporting_currency

        data = {
            "facts": {
                "ifrs-full": {
                    "Assets": {
                        "units": {
                            "CAD": [fact(None, "2025-12-31", 1.0, filed="2026-01-01")],
                            "USD": [fact(None, "2025-12-31", 1.0, filed="2026-01-01")],
                        }
                    }
                }
            }
        }
        assert reporting_currency(data) == "USD"

    def test_nothing_on_record_is_assumed_to_be_dollars(self):
        from app.services.financials import reporting_currency

        assert reporting_currency(None) == "USD"
        assert reporting_currency({"facts": {}}) == "USD"

    def test_a_unit_that_is_not_a_currency_is_ignored(self):
        """`shares` and `USD/shares` sit in the same units map."""
        from app.services.financials import reporting_currency

        data = {
            "facts": {
                "ifrs-full": {
                    "Assets": {
                        "units": {
                            "shares": [fact(None, "2025-12-31", 1.0, filed="2026-01-01")] * 9,
                            "CAD": [fact(None, "2025-12-31", 1.0, filed="2026-01-01")],
                        }
                    }
                }
            }
        }
        assert reporting_currency(data) == "CAD"


class TestFiftyTwoWeekCalendars:
    """A fiscal year that closes in the first days of January.

    Johnson & Johnson's FY2020 ends 2021-01-03. Naming it for the calendar
    year the date falls in makes it "FY2021", which then collides with the
    year that really is 2021 — two identically-labelled columns in one table.
    Caught by the audit, which asserts period keys are distinct.
    """

    @pytest.mark.parametrize(
        ("end", "expected"),
        [
            ("2021-01-03", 2020),  # J&J, 52/53-week year
            ("2023-01-01", 2022),
            ("2025-12-28", 2025),
            ("2026-01-31", 2026),  # Walmart, and it calls this FY2026
            ("2025-09-27", 2025),
        ],
    )
    def test_a_year_is_named_for_the_year_it_covers(self, end, expected):
        assert fiscal_year_of(date.fromisoformat(end)) == expected

    def test_consecutive_years_get_distinct_labels(self):
        rows = [
            fact("2019-12-30", "2021-01-03", 100.0, filed="2021-02-01"),
            fact("2021-01-04", "2022-01-02", 110.0, filed="2022-02-01"),
            fact("2022-01-03", "2023-01-01", 120.0, filed="2023-02-01"),
        ]
        built = build_statements(facts(usd(REVENUE, rows)), annual=True)
        keys = [period["key"] for period in built["periods"]]
        assert keys == ["FY2022", "FY2021", "FY2020"]
        assert len(set(keys)) == len(keys)


class TestDerivedLiabilities:
    """A total the filer stopped tagging.

    AT&T tagged `Liabilities` until 2015 and files only the components since,
    so the line is empty across every year anyone would look at. The number
    is still on the balance sheet: it is what remains once everything with a
    claim after creditors is removed.
    """

    def _sheet(self, equity_concept: str, extra: dict | None = None) -> dict:
        entries = {
            # A duration line, because only those set the period axis.
            **usd(REVENUE, [fact("2025-01-01", "2025-12-31", 10.0, filed="2026-02-01")]),
            **usd("Assets", [fact(None, "2025-12-31", 1000.0, filed="2026-02-01")]),
            **usd(equity_concept, [fact(None, "2025-12-31", 300.0, filed="2026-02-01")]),
        }
        entries.update(extra or {})
        return facts(entries)

    def test_it_is_derived_when_absent(self):
        built = build_statements(self._sheet("StockholdersEquity"), annual=True)
        assert line(built, "total_liabilities")["values"] == [700.0]

    def test_the_derivation_is_named_rather_than_passed_off_as_a_tag(self):
        built = build_statements(self._sheet("StockholdersEquity"), annual=True)
        assert any("derived" in c for c in line(built, "total_liabilities")["concepts"])

    def test_minorities_are_taken_out_when_equity_excludes_them(self):
        data = self._sheet(
            "StockholdersEquity",
            usd("MinorityInterest", [fact(None, "2025-12-31", 50.0, filed="2026-02-01")]),
        )
        assert line(build_statements(data, annual=True), "total_liabilities")["values"] == [650.0]

    def test_minorities_are_not_taken_out_twice(self):
        """The concept that answered says whether they are already inside.

        Subtracting them again where they are makes the derived liabilities
        too small by exactly that amount — AT&T's 2022 sheet was out by its
        own $8.957bn of minorities.
        """
        data = self._sheet(
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            usd("MinorityInterest", [fact(None, "2025-12-31", 50.0, filed="2026-02-01")]),
        )
        assert line(build_statements(data, annual=True), "total_liabilities")["values"] == [700.0]

    def test_a_reported_total_is_never_overwritten(self):
        data = self._sheet(
            "StockholdersEquity",
            usd("Liabilities", [fact(None, "2025-12-31", 690.0, filed="2026-02-01")]),
        )
        built = build_statements(data, annual=True)
        assert line(built, "total_liabilities")["values"] == [690.0]
        assert line(built, "total_liabilities")["concepts"] == ["Liabilities"]


class TestOneDefinitionPerRow:
    def test_equity_does_not_switch_definition_mid_series(self):
        """Parent-only and including-minorities are different numbers.

        Filling the gaps in one from the other makes a row that is not
        comparable to itself, which is worse than a gap.
        """
        data = facts(
            usd("StockholdersEquity", [fact(None, "2025-12-31", 300.0, filed="2026-02-01")]),
            usd(
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                [
                    fact(None, "2025-12-31", 350.0, filed="2026-02-01"),
                    fact(None, "2024-12-31", 340.0, filed="2025-02-01"),
                ],
            ),
            usd(REVENUE, [fact("2025-01-01", "2025-12-31", 10.0, filed="2026-02-01")]),
        )
        built = build_statements(data, annual=True)
        equity = line(built, "equity")
        assert equity["concepts"] == ["StockholdersEquity"]
        # The 2024 gap stays a gap rather than borrowing the other definition.
        assert equity["values"] == [300.0]

    def test_revenue_still_stitches_across_a_concept_change(self):
        """The merge is right where the chain is one quantity under two
        names — which is the ASC 606 case."""
        data = facts(
            usd(REVENUE, [fact("2025-01-01", "2025-12-31", 200.0, filed="2026-02-01")]),
            usd("Revenues", [fact("2017-01-01", "2017-12-31", 100.0, filed="2018-02-01")]),
        )
        assert line(build_statements(data, annual=True), "revenue")["values"] == [200.0, 100.0]
