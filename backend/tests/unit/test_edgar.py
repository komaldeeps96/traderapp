"""The EDGAR provider: CIK resolution, parsing, caching, degradation."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.domain.filings import FilingKind
from app.providers.edgar import (
    EdgarProvider,
    _parse_accepted,
    _parse_filings,
    _parse_profile,
    _parse_ticker_map,
)

CIK = 1752828

TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": CIK, "ticker": "CELU", "title": "Celularity Inc"},
}


def submissions(forms=None) -> dict:
    forms = forms or [
        ("NT 10-Q", "2026-08-14", "0001493152-26-038318", "nt.htm", "", "2026-08-14T16:05:12.000Z"),
        ("8-K", "2026-08-07", "0001493152-26-037000", "f8k.htm", "5.02", "2026-08-07T21:01:00.000Z"),
        ("424B5", "2026-01-08", "0001493152-26-000878", "p.htm", "", "2026-01-08T09:30:00.000Z"),
    ]
    return {
        "name": "Celularity Inc",
        "sic": "2834",
        "sicDescription": "Pharmaceutical Preparations",
        "exchanges": ["Nasdaq"],
        "website": "",
        "stateOfIncorporationDescription": "DE",
        "fiscalYearEnd": "1231",
        "filings": {
            "recent": {
                "form": [row[0] for row in forms],
                "filingDate": [row[1] for row in forms],
                "accessionNumber": [row[2] for row in forms],
                "primaryDocument": [row[3] for row in forms],
                "items": [row[4] for row in forms],
                "acceptanceDateTime": [row[5] for row in forms],
            }
        },
    }


FACTS = {"facts": {"us-gaap": {"CommonStockSharesIssued": {"units": {"shares": []}}}}}


def edgar_ok(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    assert "traderapp" in request.headers["user-agent"]
    if "company_tickers" in url:
        return httpx.Response(200, json=TICKERS)
    if "submissions" in url:
        return httpx.Response(200, json=submissions())
    if "companyfacts" in url:
        return httpx.Response(200, json=FACTS)
    return httpx.Response(404)


def provider(handler, **kwargs) -> EdgarProvider:
    return EdgarProvider(
        transport=httpx.MockTransport(handler), user_agent="traderapp/1.0 (t@e.com)", **kwargs
    )


class TestTickerMap:
    def test_builds_the_lookup(self):
        assert _parse_ticker_map(TICKERS)["CELU"] == CIK

    def test_lowercase_tickers_are_normalised(self):
        payload = {"0": {"cik_str": 5, "ticker": "abc"}}
        assert _parse_ticker_map(payload) == {"ABC": 5}

    @pytest.mark.parametrize("payload", [None, [], {"0": None}, {"0": {"ticker": "X"}}])
    def test_malformed_payloads_yield_nothing(self, payload):
        assert _parse_ticker_map(payload) == {}


class TestParseFilings:
    def test_rows_carry_kind_and_note(self):
        rows = _parse_filings(submissions(), CIK)
        assert [row.form for row in rows] == ["NT 10-Q", "8-K", "424B5"]
        assert rows[0].kind is FilingKind.DISTRESS
        assert rows[1].kind is FilingKind.ROUTINE
        assert rows[2].kind is FilingKind.DILUTION

    def test_items_are_split(self):
        rows = _parse_filings(submissions(), CIK)
        assert rows[1].items == ("5.02",)
        assert rows[0].items == ()

    def test_the_url_points_at_the_document(self):
        rows = _parse_filings(submissions(), CIK)
        assert rows[0].url.endswith("/000149315226038318/nt.htm")

    def test_a_ragged_column_store_truncates_rather_than_misaligns(self):
        """A short column must not let a row borrow its neighbour's fields."""
        payload = submissions()
        payload["filings"]["recent"]["items"] = [""]
        rows = _parse_filings(payload, CIK)
        assert len(rows) == 1

    def test_rows_without_a_date_or_form_are_dropped(self):
        payload = submissions()
        payload["filings"]["recent"]["filingDate"][1] = "not-a-date"
        payload["filings"]["recent"]["form"][2] = ""
        rows = _parse_filings(payload, CIK)
        assert [row.form for row in rows] == ["NT 10-Q"]

    @pytest.mark.parametrize("payload", [{}, {"filings": {}}, {"filings": {"recent": []}}])
    def test_a_missing_trail_is_empty_not_an_error(self, payload):
        assert _parse_filings(payload, CIK) == []


class TestParseAccepted:
    def test_a_zulu_timestamp_becomes_epoch(self):
        assert _parse_accepted("2026-08-14T16:05:12.000Z") == 1786723512

    @pytest.mark.parametrize("value", [None, "", "2026-08-14 16:05:12", "garbage"])
    def test_anything_without_a_zone_is_omitted(self, value):
        """Guessing a zone on a timestamp used to place a filing inside the
        session would be worse than having no timestamp."""
        assert _parse_accepted(value) is None


class TestParseProfile:
    def test_reads_the_header(self):
        profile = _parse_profile(submissions(), CIK)
        assert profile is not None
        assert profile.name == "Celularity Inc"
        assert profile.sic_description == "Pharmaceutical Preparations"
        assert profile.exchanges == ("Nasdaq",)

    def test_a_nameless_document_is_no_profile(self):
        assert _parse_profile({"name": ""}, CIK) is None


class TestProvider:
    async def test_prefetch_then_peek(self):
        edgar = provider(edgar_ok)
        assert edgar.peek_filings("CELU") == []
        await edgar.prefetch("CELU")
        assert len(edgar.peek_filings("CELU")) == 3
        assert edgar.peek_profile("CELU").name == "Celularity Inc"
        assert edgar.peek_facts("CELU") == FACTS
        await edgar.close()

    async def test_an_unknown_ticker_degrades_to_nothing(self):
        edgar = provider(edgar_ok)
        await edgar.prefetch("NOPE")
        assert edgar.peek_filings("NOPE") == []
        assert edgar.peek_profile("NOPE") is None
        await edgar.close()

    async def test_the_ticker_map_is_fetched_once_for_many_symbols(self):
        calls = {"tickers": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if "company_tickers" in str(request.url):
                calls["tickers"] += 1
            return edgar_ok(request)

        edgar = provider(handler)
        await edgar.prefetch("CELU")
        await edgar.prefetch("AAPL")
        assert calls["tickers"] == 1
        await edgar.close()

    async def test_a_second_prefetch_inside_the_ttl_does_not_refetch(self):
        calls = {"submissions": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if "submissions" in str(request.url):
                calls["submissions"] += 1
            return edgar_ok(request)

        edgar = provider(handler)
        await edgar.prefetch("CELU")
        await edgar.prefetch("CELU")
        assert calls["submissions"] == 1
        await edgar.close()

    async def test_refresh_filings_ignores_the_cache_but_not_the_facts(self):
        calls = {"submissions": 0, "facts": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "submissions" in url:
                calls["submissions"] += 1
            if "companyfacts" in url:
                calls["facts"] += 1
            return edgar_ok(request)

        edgar = provider(handler)
        await edgar.prefetch("CELU")
        rows = await edgar.refresh_filings("CELU")
        assert len(rows) == 3
        assert calls["submissions"] == 2
        # Quarterly data must not be re-fetched on the live-alert cadence.
        assert calls["facts"] == 1
        await edgar.close()

    async def test_a_transient_failure_keeps_the_last_good_trail(self):
        state = {"fail": False}

        def handler(request: httpx.Request) -> httpx.Response:
            if state["fail"] and "submissions" in str(request.url):
                return httpx.Response(503)
            return edgar_ok(request)

        edgar = provider(handler)
        await edgar.prefetch("CELU")
        state["fail"] = True
        await edgar.refresh_filings("CELU")
        assert len(edgar.peek_filings("CELU")) == 3
        await edgar.close()

    async def test_a_network_error_degrades_to_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        edgar = provider(handler)
        await edgar.prefetch("CELU")
        assert edgar.peek_filings("CELU") == []
        assert edgar.peek_facts("CELU") is None
        await edgar.close()

    async def test_a_company_without_xbrl_history_is_not_an_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "companyfacts" in str(request.url):
                return httpx.Response(404)
            return edgar_ok(request)

        edgar = provider(handler)
        await edgar.prefetch("CELU")
        assert edgar.peek_facts("CELU") is None
        assert len(edgar.peek_filings("CELU")) == 3
        await edgar.close()

    async def test_the_budget_is_taken_for_every_request(self):
        from app.services.api_budget import ProviderBudget

        budget = ProviderBudget("edgar", 9, 1)
        edgar = provider(edgar_ok, budget=budget)
        await edgar.prefetch("CELU")
        assert budget.used() == 3  # tickers, submissions, facts
        await edgar.close()


class TestFilingDict:
    def test_serialises_for_the_wire(self):
        row = _parse_filings(submissions(), CIK)[2]
        payload = row.to_dict()
        assert payload["form"] == "424B5"
        assert payload["kind"] == "dilution"
        assert payload["filed"] == date(2026, 1, 8).isoformat()
        assert payload["url"].startswith("https://www.sec.gov/Archives/")


class TestEdgeCases:
    async def test_refresh_filings_on_an_unknown_ticker_is_empty(self):
        edgar = provider(edgar_ok)
        assert await edgar.refresh_filings("NOPE") == []
        await edgar.close()

    async def test_the_note_names_the_configuration_problem(self):
        """www.sec.gov answers 403 to a User-Agent with no contact address
        while data.sec.gov answers 200, so the CIK lookup fails and every
        panel would otherwise blame the company."""
        from app.providers.edgar import UNAVAILABLE_NOTE

        def handler(request: httpx.Request) -> httpx.Response:
            if "company_tickers" in str(request.url):
                return httpx.Response(403)
            return edgar_ok(request)

        edgar = provider(handler)
        assert edgar.note() is None
        await edgar.prefetch("CELU")
        assert edgar.note() == UNAVAILABLE_NOTE
        await edgar.close()

    async def test_a_map_already_held_survives_a_failed_refresh(self):
        """Only a first failure is fatal; a refresh that fails keeps serving
        the map already in hand rather than blaming SEC."""
        state = {"fail": False}

        def handler(request: httpx.Request) -> httpx.Response:
            if state["fail"] and "company_tickers" in str(request.url):
                return httpx.Response(503)
            return edgar_ok(request)

        edgar = provider(handler)
        await edgar.prefetch("CELU")
        state["fail"] = True
        edgar._tickers_at = 0.0  # force the map past its TTL
        await edgar.refresh_filings("CELU")
        assert edgar.note() is None
        await edgar.close()
