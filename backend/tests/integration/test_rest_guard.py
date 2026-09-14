"""Who may call the REST API, and in what shape.

CORS stops a foreign page reading a response, not making the request: the news
summary is a paid process, reachable by any page open in the browser without
this.
"""

from __future__ import annotations

import pytest


class TestWhereARequestComesFrom:
    def test_a_request_another_site_made_is_refused(self, client):
        response = client.get("/api/health", headers={"sec-fetch-site": "cross-site"})
        assert response.status_code == 403

    @pytest.mark.parametrize("origin", ["https://evil.example", "null"])
    def test_a_foreign_origin_is_refused(self, client, origin):
        assert client.get("/api/health", headers={"origin": origin}).status_code == 403

    def test_a_page_on_a_rebound_dns_name_is_refused(self, client):
        """Same-origin fetches carry no Origin, so the Host is the only tell."""
        response = client.get(
            "/api/health", headers={"host": "evil.example:8000", "sec-fetch-site": "same-origin"}
        )
        assert response.status_code == 403

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"sec-fetch-site": "same-origin"},
            {"sec-fetch-site": "same-site", "origin": "http://localhost:3000"},
            {"sec-fetch-site": "same-site", "origin": "http://192.168.1.20:3000"},
        ],
        ids=["no browser", "same origin", "the dev server", "a phone on the wifi"],
    )
    def test_the_terminals_own_pages_are_served(self, client, headers):
        assert client.get("/api/health", headers=headers).status_code == 200


class TestStatementPeriods:
    def test_an_unknown_period_is_refused_rather_than_read_as_annual(self, client):
        assert client.get("/api/financials/AAPL?period=weekly").status_code == 422
