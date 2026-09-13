"""Who may call the REST API, and in what shape.

CORS stops a foreign page reading a response, not making the request: the news
summary is a paid process and the swing config a saved write, both reachable by
any page open in the browser without this.
"""

from __future__ import annotations

import json

import pytest


class TestWhereARequestComesFrom:
    def test_a_request_another_site_made_is_refused(self, client):
        response = client.get("/api/health", headers={"sec-fetch-site": "cross-site"})
        assert response.status_code == 403

    @pytest.mark.parametrize("origin", ["https://evil.example", "null"])
    def test_a_foreign_origin_is_refused(self, client, origin):
        assert client.get("/api/health", headers={"origin": origin}).status_code == 403

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


class TestSwingConfig:
    def test_is_changed_by_a_json_body(self, client):
        response = client.post("/api/swing/config", json={"rows": 20})
        assert response.status_code == 200
        assert response.json()["config"]["rows"] == 20

    def test_query_parameters_alone_change_nothing(self, client):
        """A bare form post can carry query parameters across sites."""
        response = client.post("/api/swing/config?rows=20")
        assert response.status_code == 422

    def test_a_body_that_is_not_json_is_refused(self, client):
        response = client.post(
            "/api/swing/config",
            content=json.dumps({"rows": 20}),
            headers={"content-type": "text/plain"},
        )
        assert response.status_code == 422

    def test_an_unknown_field_is_refused(self, client):
        assert client.post("/api/swing/config", json={"rowz": 20}).status_code == 422


class TestStatementPeriods:
    def test_an_unknown_period_is_refused_rather_than_read_as_annual(self, client):
        assert client.get("/api/financials/AAPL?period=weekly").status_code == 422
