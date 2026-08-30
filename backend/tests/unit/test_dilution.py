"""The dilution read: fact selection, the derived numbers, and the verdict.

The fixtures mirror the shapes EDGAR actually returns, taken from Celularity's
live ``companyfacts`` document: instant facts restated by later filings,
cash-flow facts that are cumulative from the fiscal year start rather than
discrete quarters, and a share count reported on filing cover pages.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.filings import Filing, FilingKind
from app.services.dilution import (
    BABY_SHELF_FLOAT,
    BABY_SHELF_REASON,
    UNCAPPED_REASON,
    DilutionTone,
    _annual_flow,
    _latest_instant,
    _share_growth,
    measure,
    shelf_capacity,
)

TODAY = date(2026, 8, 28)


def facts(**concepts) -> dict:
    """``facts(us_gaap={"Concept": [(unit, [entries])]})`` is too clever; this
    takes ``{"taxonomy:Concept": (unit, [entry, ...])}`` instead."""
    payload: dict = {"facts": {}}
    for key, (unit, entries) in concepts.items():
        taxonomy, concept = key.split(":", 1)
        payload["facts"].setdefault(taxonomy, {})[concept] = {"units": {unit: entries}}
    return payload


def instant(end: str, val: float, form: str = "10-K", filed: str = "2026-04-30") -> dict:
    return {"end": end, "val": val, "form": form, "filed": filed}


def span(start: str, end: str, val: float, form: str = "10-K", filed: str = "2026-04-30") -> dict:
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed}


def filing(form: str, filed: date, items: tuple[str, ...] = ()) -> Filing:
    return Filing(
        form=form,
        kind=FilingKind.DILUTION,
        note="",
        filed=filed,
        accepted=None,
        accession="0000000000-00-000000",
        items=items,
        url="",
    )


# The real Celularity picture, as of the research run.
CELU_FACTS = facts(
    **{
        "dei:EntityCommonStockSharesOutstanding": (
            "shares",
            [
                instant("2025-04-06", 23_949_229),
                instant("2025-11-14", 28_328_880, "10-Q", "2025-11-14"),
                instant("2026-04-28", 28_945_961),
            ],
        ),
        "us-gaap:CommonStockSharesIssued": ("shares", [instant("2025-12-31", 28_837_787)]),
        "us-gaap:CommonStockSharesAuthorized": ("shares", [instant("2025-12-31", 730_000_000)]),
        "us-gaap:ClassOfWarrantOrRightOutstanding": (
            "shares",
            [
                instant("2024-12-31", 11_221_557),
                instant("2025-09-30", 17_064_071, "10-Q", "2025-11-14"),
                instant("2025-12-31", 25_774_577),
            ],
        ),
        "us-gaap:ClassOfWarrantOrRightExercisePriceOfWarrantsOrRights1": (
            "USD/shares",
            [instant("2024-11-25", 3.0)],
        ),
        "us-gaap:PreferredStockSharesOutstanding": ("shares", [instant("2025-12-31", 1_732_084)]),
        "us-gaap:ConvertibleNotesPayable": ("USD", [instant("2025-12-31", 922_000)]),
        "us-gaap:CashAndCashEquivalentsAtCarryingValue": (
            "USD",
            [instant("2025-09-30", 120_000, "10-Q", "2025-11-14"), instant("2025-12-31", 6_175_000)],
        ),
        "us-gaap:NetCashProvidedByUsedInOperatingActivities": (
            "USD",
            [
                span("2025-01-01", "2025-09-30", -8_151_000, "10-Q", "2025-11-14"),
                span("2025-01-01", "2025-12-31", -13_254_000),
            ],
        ),
        "dei:EntityPublicFloat": ("USD", [instant("2025-06-30", 28_400_000)]),
    }
)

CELU_FILINGS = [
    filing("NT 10-Q", date(2026, 8, 14)),
    filing("8-K", date(2026, 7, 29), ("3.01",)),
    filing("25-NSE", date(2026, 7, 22)),
    filing("424B3", date(2026, 1, 8)),
    filing("S-1", date(2025, 12, 31)),
    filing("S-1", date(2025, 12, 19)),
    filing("EFFECT", date(2026, 1, 7)),
]


class TestFactSelection:
    def test_the_newest_period_wins(self):
        got = _latest_instant(CELU_FACTS, (("us-gaap", "ClassOfWarrantOrRightOutstanding"),))
        assert got.value == 25_774_577
        assert got.as_of == date(2025, 12, 31)

    def test_a_restatement_of_the_same_period_beats_the_original(self):
        payload = facts(
            **{
                "us-gaap:CommonStockSharesIssued": (
                    "shares",
                    [
                        instant("2025-12-31", 100, filed="2026-01-10"),
                        instant("2025-12-31", 150, filed="2026-03-01"),
                    ],
                )
            }
        )
        assert _latest_instant(payload, (("us-gaap", "CommonStockSharesIssued"),)).value == 150

    def test_duration_facts_are_never_read_as_instants(self):
        payload = facts(
            **{"us-gaap:CommonStockSharesIssued": ("shares", [span("2025-01-01", "2025-12-31", 9)])}
        )
        assert _latest_instant(payload, (("us-gaap", "CommonStockSharesIssued"),)) is None

    def test_the_fallback_chain_is_used_when_the_preferred_concept_is_absent(self):
        payload = facts(
            **{"us-gaap:CommonStockSharesOutstanding": ("shares", [instant("2025-12-31", 42)])}
        )
        from app.services.dilution import _SHARES_OUTSTANDING

        assert _latest_instant(payload, _SHARES_OUTSTANDING).value == 42

    def test_missing_facts_read_as_none(self):
        assert _latest_instant(None, (("us-gaap", "X"),)) is None
        assert _latest_instant({}, (("us-gaap", "X"),)) is None


class TestAnnualFlow:
    def test_a_full_year_span_is_preferred_over_a_year_to_date_one(self):
        got = _annual_flow(CELU_FACTS, (("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),))
        assert got.value == -13_254_000
        assert got.as_of == date(2025, 12, 31)

    def test_a_year_to_date_span_is_annualised_when_no_full_year_exists(self):
        """Cash-flow facts accumulate from the fiscal year start, so summing
        the reported periods would count Q1 four times."""
        payload = facts(
            **{
                "us-gaap:NetCashProvidedByUsedInOperatingActivities": (
                    "USD",
                    [span("2025-01-01", "2025-09-30", -8_151_000)],
                )
            }
        )
        got = _annual_flow(payload, (("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),))
        assert got.value == pytest.approx(-8_151_000 * 365 / 272, rel=1e-6)

    def test_a_stub_period_is_not_annualised(self):
        payload = facts(
            **{
                "us-gaap:NetCashProvidedByUsedInOperatingActivities": (
                    "USD",
                    [span("2025-01-01", "2025-02-01", -1_000)],
                )
            }
        )
        assert _annual_flow(payload, (("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),)) is None


class TestShareGrowth:
    def test_measures_against_the_newest_point_a_year_old(self):
        growth = _share_growth(CELU_FACTS)
        assert growth == pytest.approx((28_945_961 - 23_949_229) / 23_949_229)

    def test_a_history_shorter_than_a_year_reports_nothing(self):
        payload = facts(
            **{
                "dei:EntityCommonStockSharesOutstanding": (
                    "shares",
                    [instant("2026-01-01", 10), instant("2026-06-01", 20)],
                )
            }
        )
        assert _share_growth(payload) is None

    def test_a_single_point_reports_nothing(self):
        payload = facts(
            **{"dei:EntityCommonStockSharesOutstanding": ("shares", [instant("2025-01-01", 10)])}
        )
        assert _share_growth(payload) is None


class TestMeasure:
    @pytest.fixture
    def read(self):
        return measure(CELU_FACTS, CELU_FILINGS, today=TODAY)

    def test_warrant_overhang(self, read):
        assert read.warrant_overhang == pytest.approx(25_774_577 / 28_945_961)

    def test_fully_diluted_excludes_preferred(self, read):
        """Conversion ratios are set per series in the charter and are not in
        the facts, so folding preferred in at 1:1 would invent a number."""
        assert read.fully_diluted == 28_945_961 + 25_774_577
        assert read.preferred.value == 1_732_084

    def test_the_warrant_strike_is_carried_for_the_frontend_to_compare(self):
        """Whether the warrants are in the money depends on the tape, which
        changes every tick; the strike is shipped and the comparison is made
        where the live price already lives."""
        read = measure(CELU_FACTS, CELU_FILINGS, today=TODAY)
        assert read.warrant_strike.value == 3.0
        assert not hasattr(read, "warrants_in_the_money")

    def test_runway(self, read):
        assert read.runway_months == pytest.approx(6_175_000 / (13_254_000 / 12), rel=1e-9)
        assert read.runway_months < 6.0

    def test_authorized_headroom(self, read):
        assert read.authorized_headroom == 730_000_000 - 28_837_787

    def test_baby_shelf(self, read):
        assert read.baby_shelf is True
        assert read.baby_shelf_capacity == pytest.approx(28_400_000 / 3)

    def test_a_large_float_is_not_on_a_baby_shelf(self):
        payload = facts(**{"dei:EntityPublicFloat": ("USD", [instant("2025-06-30", BABY_SHELF_FLOAT * 2)])})
        read = measure(payload, [], today=TODAY)
        assert read.baby_shelf is False
        assert read.baby_shelf_capacity is None

    def test_offerings_are_counted_over_a_trailing_year(self, read):
        # 424B3, two S-1s — EFFECT and the distress forms are not offerings.
        assert read.offerings_12m == 3

    def test_distress_flags(self, read):
        assert read.delinquent is True
        assert read.listing_deficiency is True
        assert read.delisting_filed is True

    def test_stale_dates_are_carried(self, read):
        assert read.cash.as_of == date(2025, 12, 31)
        assert read.cash.stale_days(TODAY) == 240

    def test_the_verdict_is_serial_with_reasons(self, read):
        assert read.tone is DilutionTone.SERIAL
        assert read.reasons
        assert any("warrants" in reason for reason in read.reasons)
        assert any("months of cash" in reason for reason in read.reasons)
        assert any("listing rule" in reason for reason in read.reasons)

    def test_it_serialises_for_the_wire(self, read):
        payload = read.to_dict()
        assert payload["tone"] == "serial"
        assert payload["cash"]["as_of"] == "2025-12-31"
        assert payload["cash"]["stale_days"] >= 240
        assert isinstance(payload["reasons"], list)


class TestVerdict:
    def test_nothing_reported_is_not_a_read(self):
        assert measure(None, [], today=TODAY) is None
        assert measure({}, [], today=TODAY) is None

    def test_filings_alone_are_enough_to_read(self):
        read = measure({}, [filing("424B5", date(2026, 6, 1))], today=TODAY)
        assert read is not None
        assert read.offerings_12m == 1

    def test_a_clean_company_says_nothing(self):
        payload = facts(
            **{
                "dei:EntityCommonStockSharesOutstanding": (
                    "shares",
                    [instant("2025-01-01", 100_000_000), instant("2026-06-30", 100_500_000)],
                ),
                "us-gaap:CashAndCashEquivalentsAtCarryingValue": ("USD", [instant("2026-06-30", 500_000_000)]),
                "us-gaap:NetCashProvidedByUsedInOperatingActivities": (
                    "USD",
                    [span("2025-07-01", "2026-06-30", 90_000_000)],
                ),
                "dei:EntityPublicFloat": ("USD", [instant("2026-06-30", 4_000_000_000)]),
            }
        )
        read = measure(payload, [filing("10-K", date(2026, 2, 1))], today=TODAY)
        assert read.tone is DilutionTone.CLEAN
        assert read.reasons == ()
        # Cash-generative: a runway is not a meaningful number.
        assert read.runway_months is None

    def test_a_heavy_overhang_alone_reaches_heavy(self):
        payload = facts(
            **{
                "dei:EntityCommonStockSharesOutstanding": ("shares", [instant("2026-06-30", 10_000_000)]),
                "us-gaap:ClassOfWarrantOrRightOutstanding": ("shares", [instant("2026-06-30", 4_000_000)]),
            }
        )
        read = measure(payload, [], today=TODAY)
        assert read.tone is DilutionTone.HEAVY

    def test_a_mild_overhang_only_reaches_watch(self):
        payload = facts(
            **{
                "dei:EntityCommonStockSharesOutstanding": ("shares", [instant("2026-06-30", 10_000_000)]),
                "us-gaap:ClassOfWarrantOrRightOutstanding": ("shares", [instant("2026-06-30", 1_200_000)]),
            }
        )
        read = measure(payload, [], today=TODAY)
        assert read.tone is DilutionTone.WATCH

    def test_an_offering_alongside_distress_is_serial(self):
        read = measure(
            {},
            [filing("424B5", date(2026, 6, 1)), filing("NT 10-Q", date(2026, 6, 2))],
            today=TODAY,
        )
        assert read.tone is DilutionTone.SERIAL

    def test_a_bare_form_25_is_not_a_delisting_risk(self):
        """A large issuer files Form 25 to remove a matured note most years.
        Uncorroborated, it must not read as its stock being delisted — Apple
        would otherwise come back HEAVY.
        """
        read = measure({}, [filing("25-NSE", date(2026, 5, 22))], today=TODAY)
        assert read.delisting_filed is True
        assert read.listing_deficiency is False
        assert read.tone is DilutionTone.CLEAN
        assert read.reasons == ()

    def test_a_listing_rule_notice_is_the_signal_that_counts(self):
        read = measure({}, [filing("8-K", date(2026, 6, 12), ("3.01",))], today=TODAY)
        assert read.listing_deficiency is True
        assert read.tone is DilutionTone.HEAVY

    def test_a_form_25_beside_a_deficiency_is_worth_saying(self):
        read = measure(
            {},
            [filing("8-K", date(2026, 6, 12), ("3.01",)), filing("25-NSE", date(2026, 7, 22))],
            today=TODAY,
        )
        assert any("filed for delisting" in reason for reason in read.reasons)

    def test_old_filings_fall_out_of_the_window(self):
        read = measure({}, [filing("424B5", date(2024, 1, 1))], today=TODAY)
        assert read.offerings_12m == 0
        assert read.tone is DilutionTone.CLEAN


class TestLiveShelfCapacity:
    """Baby-shelf capacity priced at the tape rather than at the cover page.

    The rule re-measures public float on the date of every sale, against a
    price taken from a 60-day look-back. So the run itself is what decides
    how much can be sold into it — the number on the last 10-K describes a
    company that, on a mover, no longer exists.
    """

    # Ten million float shares against $8M of float on the last cover page:
    # the stock was 80 cents when they filed it.
    FLOAT_SHARES = 10_000_000
    REPORTED = 8_000_000.0

    def test_the_cap_is_a_third_of_float_at_the_lookback_high(self):
        shelf = shelf_capacity(self.FLOAT_SHARES, 1.20, self.REPORTED)
        assert shelf.public_float == pytest.approx(12_000_000)
        assert shelf.capped is True
        assert shelf.capacity == pytest.approx(4_000_000)

    def test_a_run_multiplies_what_they_may_sell(self):
        """Tripling the price triples the dollars, without a single filing."""
        before = shelf_capacity(self.FLOAT_SHARES, 1.00, self.REPORTED)
        after = shelf_capacity(self.FLOAT_SHARES, 3.00, self.REPORTED)
        assert after.capacity == pytest.approx(before.capacity * 3)
        assert after.multiple == pytest.approx(3.75)  # against the cover page

    def test_past_seventy_five_million_the_cap_stops_applying(self):
        """Not a bigger third — no third at all, until the next measurement
        date. The loudest state this read has."""
        shelf = shelf_capacity(self.FLOAT_SHARES, 7.50, self.REPORTED)
        assert shelf.public_float == pytest.approx(BABY_SHELF_FLOAT)
        assert shelf.capped is False
        assert shelf.capacity is None

    def test_the_boundary_belongs_to_the_cap(self):
        assert shelf_capacity(self.FLOAT_SHARES, 7.4999, self.REPORTED).capped is True
        assert shelf_capacity(self.FLOAT_SHARES, 7.5001, self.REPORTED).capped is False

    def test_without_a_cover_page_figure_there_is_no_multiple(self):
        shelf = shelf_capacity(self.FLOAT_SHARES, 1.20, None)
        assert shelf.multiple is None
        assert shelf.capacity == pytest.approx(4_000_000)

    @pytest.mark.parametrize(
        ("shares", "price"),
        [(None, 1.2), (10_000_000, None), (0, 1.2), (10_000_000, 0), (-5, 1.2)],
    )
    def test_half_the_inputs_is_no_answer(self, shares, price):
        """A capacity computed from a missing float or a missing price would
        be a confident number about nothing."""
        assert shelf_capacity(shares, price, self.REPORTED) is None


class TestReasonsFollowTheLiveShelf:
    """The verdict is built from the last cover page. When the run has moved
    float past $75M the filed reason contradicts the panel beside it, and the
    contradiction has to resolve toward the worse fact.
    """

    def build(self):
        return measure(
            facts(**{"dei:EntityPublicFloat": ("USD", [instant("2025-06-30", 8_000_000)])}),
            [],
            today=TODAY,
        )

    def test_the_filed_reason_stands_while_the_cap_still_binds(self):
        read = self.build().with_live_shelf(shelf_capacity(10_000_000, 1.20, 8_000_000))
        assert any(BABY_SHELF_REASON in reason for reason in read.reasons)
        assert UNCAPPED_REASON not in read.reasons

    def test_an_uncapped_run_replaces_it(self):
        read = self.build().with_live_shelf(shelf_capacity(10_000_000, 9.00, 8_000_000))
        assert not any(BABY_SHELF_REASON in reason for reason in read.reasons)
        assert UNCAPPED_REASON in read.reasons

    def test_without_a_live_figure_nothing_is_rewritten(self):
        plain = self.build()
        assert plain.with_live_shelf(None).reasons == plain.reasons
