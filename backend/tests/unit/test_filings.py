"""The filing-form taxonomy: classification, 8-K items, document links."""

from __future__ import annotations

import pytest

from app.domain.filings import (
    OFFERING_FORMS,
    FilingKind,
    classify,
    filing_url,
)


class TestClassify:
    @pytest.mark.parametrize(
        "form",
        ["S-1", "S-3", "S-3ASR", "424B5", "424B3", "EFFECT", "POS AM", "S-8"],
    )
    def test_registration_and_prospectus_forms_are_dilution(self, form):
        kind, note = classify(form)
        assert kind is FilingKind.DILUTION
        assert note

    @pytest.mark.parametrize("form", ["NT 10-Q", "NT 10-K", "25-NSE", "15-12B"])
    def test_late_and_delisting_forms_are_distress(self, form):
        kind, note = classify(form)
        assert kind is FilingKind.DISTRESS
        assert note

    @pytest.mark.parametrize("form", ["10-K", "10-Q", "20-F"])
    def test_periodic_reports_are_periodic(self, form):
        assert classify(form)[0] is FilingKind.PERIODIC

    @pytest.mark.parametrize("form", ["4", "SC 13D", "SC 13G/A"])
    def test_holder_forms_are_ownership(self, form):
        assert classify(form)[0] is FilingKind.OWNERSHIP

    def test_an_unknown_form_is_routine_and_says_nothing(self):
        assert classify("ARS") == (FilingKind.ROUTINE, "")

    def test_a_prefix_lookalike_is_not_confused_for_its_neighbour(self):
        """``S-1MEF`` and ``SC 13D`` must not collide under a prefix match."""
        assert classify("S-1MEF")[0] is FilingKind.DILUTION
        assert classify("SC 13D")[0] is FilingKind.OWNERSHIP


class TestEightK:
    def test_an_unregistered_sale_is_dilution(self):
        kind, note = classify("8-K", "3.02")
        assert kind is FilingKind.DILUTION
        assert "unregistered" in note

    def test_a_listing_rule_failure_is_distress(self):
        assert classify("8-K", "3.01")[0] is FilingKind.DISTRESS

    def test_an_officer_change_is_routine(self):
        assert classify("8-K", "5.02")[0] is FilingKind.ROUTINE

    def test_the_worst_item_describes_the_filing(self):
        """A filing carrying both routine and distress items reads as distress."""
        kind, note = classify("8-K", "5.02,3.01,8.01")
        assert kind is FilingKind.DISTRESS
        assert "listing rule" in note

    def test_dilution_beats_routine_but_loses_to_distress(self):
        assert classify("8-K", "8.01,3.02")[0] is FilingKind.DILUTION
        assert classify("8-K", "3.02,1.03")[0] is FilingKind.DISTRESS

    def test_no_items_is_a_plain_current_report(self):
        kind, note = classify("8-K", "")
        assert kind is FilingKind.ROUTINE
        assert note == "current report"

    def test_unrecognised_items_do_not_crash(self):
        assert classify("8-K", "9.99, 12.34")[0] is FilingKind.ROUTINE

    def test_whitespace_around_items_is_tolerated(self):
        assert classify("8-K", " 3.02 , 5.02 ")[0] is FilingKind.DILUTION


class TestOfferingForms:
    def test_employee_plans_are_not_offerings(self):
        """S-8 registers a stock plan; it is dilution, but not a raise."""
        assert classify("S-8")[0] is FilingKind.DILUTION
        assert "S-8" not in OFFERING_FORMS

    def test_effect_is_not_double_counted(self):
        """EFFECT flips a switch on a registration already counted."""
        assert "EFFECT" not in OFFERING_FORMS

    def test_the_takedown_counts(self):
        assert "424B5" in OFFERING_FORMS


class TestFilingUrl:
    def test_links_to_the_primary_document(self):
        url = filing_url(1752828, "0001493152-26-038318", "form10q.htm")
        assert url == (
            "https://www.sec.gov/Archives/edgar/data/1752828/"
            "000149315226038318/form10q.htm"
        )

    def test_without_a_document_it_links_to_the_index(self):
        url = filing_url(320193, "9999999995-26-000103", "")
        assert url.endswith("9999999995-26-000103-index.htm")
