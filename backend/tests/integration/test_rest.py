"""REST endpoints against a running application."""

from __future__ import annotations


class TestHealth:
    def test_reports_ok(self, client):
        assert client.get("/api/health").json()["status"] == "ok"

    def test_reports_alpaca_as_the_active_source(self, client):
        body = client.get("/api/health").json()
        assert body["source"] == "alpaca"
        assert body["alpaca_available"] is True

    def test_reports_ibkr_as_absent(self, client):
        body = client.get("/api/health").json()
        assert body["ibkr_connected"] is False

    def test_explains_the_fallback(self, client):
        """A user with no TWS should be told why, not left guessing."""
        assert "IBKR" in (client.get("/api/health").json()["message"] or "")

    def test_counts_connected_clients(self, client):
        assert client.get("/api/health").json()["clients"] == 0


class TestIndicators:
    def test_returns_the_configured_set(self, client):
        assert len(client.get("/api/indicators").json()) >= 25

    def test_each_entry_has_what_the_chart_needs(self, client):
        first = client.get("/api/indicators").json()[0]
        assert {"id", "type", "label", "color", "color_dark", "pane", "timeframes"} <= set(first)

    def test_exposes_key_levels(self, client):
        ids = {entry["id"] for entry in client.get("/api/indicators").json()}
        assert {"pm_high", "pm_low", "prev_day_close", "high_52w"} <= ids

    def test_panes_are_declared(self, client):
        panes = {entry["pane"] for entry in client.get("/api/indicators").json()}
        # No macd: the shipped config dropped it, though the engine still
        # knows how to build one if the YAML ever brings it back.
        assert panes == {"price", "volume"}


class TestTimeframes:
    def test_lists_every_timeframe(self, client):
        values = [entry["value"] for entry in client.get("/api/timeframes").json()]
        assert values == ["10s", "1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

    def test_marks_which_are_intraday(self, client):
        entries = {e["value"]: e["intraday"] for e in client.get("/api/timeframes").json()}
        assert entries["10s"] is True and entries["1m"] is True and entries["1d"] is False


class TestSession:
    def test_returns_defaults_before_anything_is_viewed(self, client):
        body = client.get("/api/session").json()
        assert body["symbol"] == "AAPL"
        assert body["timeframe"] == "10s"

    def test_remembers_the_last_chart(self, client):
        with client.websocket_connect("/ws") as socket:
            socket.receive_json()
            socket.receive_json()
            socket.send_json({"action": "subscribe", "symbol": "TSLA", "timeframe": "5m"})
            for _ in range(6):
                if socket.receive_json().get("type") == "snapshot":
                    break

        body = client.get("/api/session").json()
        assert body["symbol"] == "TSLA"
        assert body["timeframe"] == "5m"


class TestScannerTiers:
    def test_lists_the_scan_codes(self, client):
        codes = {entry["code"] for entry in client.get("/api/scanner/tiers").json()["scan_codes"]}
        assert "TOP_PERC_GAIN" in codes

    def test_lists_the_four_market_cap_tiers(self, client):
        tiers = client.get("/api/scanner/tiers").json()["tiers"]
        assert {t["id"] for t in tiers} == {"small_cap", "mid_cap", "large_cap", "mega_cap"}
        assert all("label" in t for t in tiers)

    def test_the_note_explains_ibkr_is_required(self, client):
        body = client.get("/api/scanner/tiers").json()
        assert "IBKR" in body["note"]


class TestCors:
    def test_allows_the_dev_frontend(self, client):
        response = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


class TestFundamentals:
    """The dock's fundamentals panel, for one symbol."""

    def test_reports_unavailable_when_edgar_is_switched_off(self, client):
        body = client.get("/api/fundamentals/CELU").json()
        assert body == {
            "symbol": "CELU",
            "available": False,
            "note": None,
            "dilution": None,
            "profile": None,
            # TradingView is off in these settings too, so nothing to carry.
            "business": None,
        }

    def test_serves_the_dilution_read(self, edgar_client):
        body = edgar_client.get("/api/fundamentals/CELU").json()
        assert body["available"] is True
        read = body["dilution"]
        assert read["warrants"]["value"] == 25_774_577
        assert read["shares_outstanding"]["value"] == 28_945_961
        assert read["warrant_overhang"] > 0.88
        assert read["tone"] == "serial"

    def test_every_figure_carries_the_date_it_was_reported_for(self, edgar_client):
        """XBRL lags by a quarter or more; a number without its as-of date is
        a lie with the timestamp missing."""
        read = edgar_client.get("/api/fundamentals/CELU").json()["dilution"]
        for field in ("cash", "warrants", "shares_outstanding", "public_float"):
            assert read[field]["as_of"]
            assert read[field]["stale_days"] >= 0

    def test_carries_the_reasons_behind_the_verdict(self, edgar_client):
        read = edgar_client.get("/api/fundamentals/CELU").json()["dilution"]
        assert any("warrants" in reason for reason in read["reasons"])
        assert any("listing rule" in reason for reason in read["reasons"])

    def test_serves_the_filer_profile(self, edgar_client):
        profile = edgar_client.get("/api/fundamentals/CELU").json()["profile"]
        assert profile["name"] == "Celularity Inc"
        assert profile["sic_description"] == "Pharmaceutical Preparations"
        assert profile["exchanges"] == ["Nasdaq"]

    def test_normalises_the_symbol(self, edgar_client):
        assert edgar_client.get("/api/fundamentals/celu").json()["symbol"] == "CELU"

    def test_rejects_a_symbol_that_is_not_one(self, edgar_client):
        """It reaches an upstream URL, so it is validated like a command."""
        assert edgar_client.get("/api/fundamentals/..%2Fetc").status_code in (404, 422)
        assert edgar_client.get("/api/fundamentals/TOOLONGSYMBOL").status_code == 422

    def test_an_unknown_ticker_answers_without_a_profile(self, edgar_client):
        body = edgar_client.get("/api/fundamentals/ZZZZ").json()
        assert body["available"] is True
        assert body["profile"] is None
        # The company being unknown is not an EDGAR problem.
        assert body["note"] is None

    def test_a_refused_request_says_so_rather_than_blaming_the_company(
        self, settings, alpaca_api
    ):
        """www.sec.gov answers 403 to a User-Agent with no contact address
        while data.sec.gov answers 200, so the CIK lookup fails and everything
        else comes back null. Reporting that as "this company files nothing"
        sends the reader hunting for a story that is really a config line."""
        from fastapi.testclient import TestClient

        from app.core.settings import EdgarSettings
        from app.main import create_app
        from app.providers.edgar import UNAVAILABLE_NOTE, EdgarProvider
        from app.services.container import get_container
        from tests.integration.edgar_stub import edgar_transport

        settings = settings.model_copy(update={"edgar": EdgarSettings(enabled=True)})
        with TestClient(create_app(settings)) as client:
            container = get_container()
            container.edgar = EdgarProvider(transport=edgar_transport(fail=True))
            container.symbol_info._edgar = container.edgar

            body = client.get("/api/fundamentals/CELU").json()
            assert body["note"] == UNAVAILABLE_NOTE
            assert body["dilution"] is None
            assert client.get("/api/filings/CELU").json()["note"] == UNAVAILABLE_NOTE


class TestFilings:
    """The dock's filings panel — the SEC trail, classified."""

    def test_reports_unavailable_when_edgar_is_switched_off(self, client):
        body = client.get("/api/filings/CELU").json()
        assert body == {"symbol": "CELU", "available": False, "note": None, "filings": []}

    def test_serves_the_trail_newest_first(self, edgar_client):
        rows = edgar_client.get("/api/filings/CELU").json()["filings"]
        assert [row["form"] for row in rows][:3] == ["NT 10-Q", "8-K", "25-NSE"]

    def test_each_row_is_classified_and_explained(self, edgar_client):
        rows = edgar_client.get("/api/filings/CELU").json()["filings"]
        by_form = {row["form"]: row for row in rows}
        assert by_form["NT 10-Q"]["kind"] == "distress"
        assert by_form["424B3"]["kind"] == "dilution"
        assert by_form["10-K"]["kind"] == "periodic"
        assert by_form["4"]["kind"] == "ownership"
        assert by_form["424B3"]["note"]

    def test_an_eight_k_is_classified_by_its_items(self, edgar_client):
        rows = edgar_client.get("/api/filings/CELU").json()["filings"]
        eight_ks = {tuple(row["items"]): row for row in rows if row["form"] == "8-K"}
        assert eight_ks[("3.01",)]["kind"] == "distress"
        assert eight_ks[("1.01",)]["kind"] == "dilution"

    def test_rows_link_to_the_document_on_sec_gov(self, edgar_client):
        rows = edgar_client.get("/api/filings/CELU").json()["filings"]
        assert rows[0]["url"].startswith("https://www.sec.gov/Archives/edgar/data/1752828/")

    def test_acceptance_time_rides_along(self, edgar_client):
        """A 424B5 accepted at 16:05 is the one that matters, and only this
        field can say so."""
        rows = edgar_client.get("/api/filings/CELU").json()["filings"]
        assert rows[0]["accepted"] == 1786723512

    def test_a_company_with_nothing_on_file_is_not_an_edgar_problem(self, edgar_client):
        body = edgar_client.get("/api/filings/ZZZZ").json()
        assert body["available"] is True
        assert body["filings"] == []
        assert body["note"] is None

    def test_normalises_the_symbol(self, edgar_client):
        assert edgar_client.get("/api/filings/celu").json()["symbol"] == "CELU"

    def test_rejects_a_symbol_that_is_not_one(self, edgar_client):
        assert edgar_client.get("/api/filings/TOOLONGSYMBOL").status_code == 422


class TestNews:
    """The dock's news panel. IBKR is disabled in these settings, which is the
    configuration a user without TWS has — the panel must say so rather than
    fail."""

    def test_answers_without_ibkr_rather_than_erroring(self, client):
        body = client.get("/api/news/CELU").json()
        assert body == {"symbol": "CELU", "providers": [], "headlines": []}

    def test_normalises_the_symbol(self, client):
        assert client.get("/api/news/celu").json()["symbol"] == "CELU"

    def test_rejects_a_symbol_that_is_not_one(self, client):
        assert client.get("/api/news/TOOLONGSYMBOL").status_code == 422

    def test_an_article_needs_both_identifiers(self, client):
        assert client.get("/api/news/CELU/article").status_code == 422

    def test_an_article_body_comes_back_as_paragraphs(self, client):
        body = client.get(
            "/api/news/CELU/article", params={"provider": "DJ-N", "article_id": "DJ-N$1f36"}
        ).json()
        assert body["paragraphs"] == []
        assert body["article_id"] == "DJ-N$1f36"


class TestFinancials:
    """`/api/financials` — the statements the main-area tab draws."""

    def test_builds_a_series_from_companyfacts(self, edgar_client):
        payload = edgar_client.get("/api/financials/CELU").json()
        assert payload["available"] is True
        assert payload["period"] == "annual"
        assert [period["key"] for period in payload["periods"]] == ["FY2025", "FY2024"]

    def test_carries_the_period_end_beside_the_label(self, edgar_client):
        """The label is a convention; the end date is the fact.

        Companies with the same January year-end do not agree on what to call
        it, so the exact close always travels with it.
        """
        payload = edgar_client.get("/api/financials/CELU").json()
        assert payload["periods"][0]["end"] == "2025-12-31"

    def test_groups_the_lines_by_statement(self, edgar_client):
        payload = edgar_client.get("/api/financials/CELU").json()
        assert [statement["key"] for statement in payload["statements"]] == [
            "income",
            "balance",
            "cash_flow",
        ]

    def test_a_concept_change_does_not_break_the_series(self, edgar_client):
        """The stub changes revenue concept between the two years."""
        payload = edgar_client.get("/api/financials/CELU").json()
        income = next(s for s in payload["statements"] if s["key"] == "income")
        revenue = next(line for line in income["lines"] if line["key"] == "revenue")
        assert revenue["values"] == [26_400_000, 48_100_000]
        assert len(revenue["concepts"]) == 2

    def test_names_the_concepts_that_answered(self, edgar_client):
        """Which tag a number came from is part of reading it."""
        payload = edgar_client.get("/api/financials/CELU").json()
        income = next(s for s in payload["statements"] if s["key"] == "income")
        revenue = next(line for line in income["lines"] if line["key"] == "revenue")
        assert "RevenueFromContractWithCustomerExcludingAssessedTax" in revenue["concepts"]

    def test_serves_a_quarterly_view(self, edgar_client):
        payload = edgar_client.get("/api/financials/CELU?period=quarterly").json()
        assert payload["period"] == "quarterly"

    def test_caps_the_number_of_periods(self, edgar_client):
        """An unbounded limit turns the endpoint into a scrape."""
        payload = edgar_client.get("/api/financials/CELU?limit=9999").json()
        assert len(payload["periods"]) <= 12

    def test_a_symbol_that_files_nothing_is_empty_not_broken(self, edgar_client):
        payload = edgar_client.get("/api/financials/NOSUCH").json()
        assert payload["periods"] == []
        assert payload["statements"] == []

    def test_says_so_when_edgar_is_switched_off(self, client):
        """The default test client runs with EDGAR disabled."""
        payload = client.get("/api/financials/CELU").json()
        assert payload["available"] is False
        assert payload["statements"] == []


class TestMetrics:
    """`/api/metrics` — ratios, and multiples against the live market cap."""

    def test_derives_ratios_from_the_statements(self, edgar_client):
        payload = edgar_client.get("/api/metrics/CELU").json()
        assert payload["available"] is True
        keys = {metric["key"] for group in payload["groups"] for metric in group["metrics"]}
        assert "net_margin" in keys

    def test_shares_the_period_axis_with_the_statements(self, edgar_client):
        """The two tabs must not disagree about which years are on screen."""
        metrics = edgar_client.get("/api/metrics/CELU").json()
        financials = edgar_client.get("/api/financials/CELU").json()
        assert [p["key"] for p in metrics["periods"]] == [p["key"] for p in financials["periods"]]

    def test_reports_a_loss_as_a_negative_margin(self, edgar_client):
        """The stub's company loses money; that has to survive to the tab."""
        payload = edgar_client.get("/api/metrics/CELU").json()
        margin = next(
            metric
            for group in payload["groups"]
            for metric in group["metrics"]
            if metric["key"] == "net_margin"
        )
        assert margin["values"][0] is not None
        assert margin["values"][0] < 0

    def test_carries_a_valuation_block(self, edgar_client):
        payload = edgar_client.get("/api/metrics/CELU").json()
        assert payload["valuation"]["basis"] == "annual"
        assert {m["key"] for m in payload["valuation"]["multiples"]} >= {"pe", "ps"}

    def test_says_so_when_edgar_is_switched_off(self, client):
        payload = client.get("/api/metrics/CELU").json()
        assert payload["available"] is False
        assert payload["groups"] == []
