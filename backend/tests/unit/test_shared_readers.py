"""The readers every upstream shares: ISO dates, screener rows, companyfacts."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.clock import parse_iso_date
from app.domain.companyfacts import concept_units
from app.domain.screener import RowReader


class TestParseIsoDate:
    def test_reads_a_calendar_date(self):
        assert parse_iso_date("2024-02-29") == date(2024, 2, 29)

    @pytest.mark.parametrize("value", [None, 20240229, "", "2023-02-29", "29/02/2024"])
    def test_anything_else_is_none(self, value):
        assert parse_iso_date(value) is None


class TestRowReader:
    read = RowReader(["name", "close", "volume"])

    def test_reads_by_column_name(self):
        row = ["AAPL", 190.5, 1_000]
        assert self.read.text(row, "name") == "AAPL"
        assert self.read.number(row, "close") == 190.5
        assert self.read.number(row, "volume") == 1_000.0

    def test_a_missing_cell_is_none_not_nan(self):
        assert self.read.number(["AAPL", float("nan"), None], "close") is None

    def test_text_that_is_not_text_is_empty(self):
        assert self.read.text([None, 1.0, 2.0], "name") == ""


FACTS = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [{"val": 1}]}}}}}


class TestConceptUnits:
    def test_reaches_a_concepts_units(self):
        assert concept_units(FACTS, "us-gaap", "Revenues") == {"USD": [{"val": 1}]}

    @pytest.mark.parametrize(
        ("facts", "taxonomy", "concept"),
        [
            (None, "us-gaap", "Revenues"),
            ({}, "us-gaap", "Revenues"),
            (FACTS, "ifrs-full", "Revenues"),
            (FACTS, "us-gaap", "NetIncomeLoss"),
            ({"facts": {"us-gaap": {"Revenues": {"units": []}}}}, "us-gaap", "Revenues"),
        ],
    )
    def test_absent_is_empty(self, facts, taxonomy, concept):
        assert concept_units(facts, taxonomy, concept) == {}
