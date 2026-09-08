"""CORS as the browser on the phone actually experiences it.

test_cors_origins pins the pattern; this pins the wiring around it — that the
regex is handed to the middleware at all, and that clearing it narrows the app
instead of opening it, which is what ``re.compile("")`` would do.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app

PHONE = "http://10.0.0.130:3000"


class TestTheApiAnswersTheHomeNetwork:
    def test_a_phone_on_the_wifi_gets_the_header_back(self, client: TestClient):
        response = client.get("/api/health", headers={"Origin": PHONE})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == PHONE

    def test_the_preflight_passes(self, client: TestClient):
        response = client.options(
            "/api/health",
            headers={
                "Origin": PHONE,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == PHONE

    def test_the_open_internet_does_not(self, client: TestClient):
        """No allow-origin header is how a browser is refused; the response
        body still arrives, which is why this is easy to miss by eye."""
        response = client.get("/api/health", headers={"Origin": "http://evil.com:3000"})
        assert "access-control-allow-origin" not in response.headers


def test_clearing_the_regex_binds_the_app_back_to_this_laptop(settings, alpaca_api):
    """`TRADERAPP_CORS_ORIGIN_REGEX= make backend`.

    An empty pattern must reach the middleware as None. Passed through as an
    empty string it compiles to a pattern that fullmatches nothing — right by
    accident here, but one refactor away from matching everything, and the
    failure mode is silent.
    """
    laptop_only = settings.model_copy(update={"cors_origin_regex": ""})
    with TestClient(create_app(laptop_only)) as client:
        phone = client.get("/api/health", headers={"Origin": PHONE})
        assert "access-control-allow-origin" not in phone.headers

        # The explicit list is untouched, so the laptop still works.
        laptop = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
        assert laptop.headers["access-control-allow-origin"] == "http://localhost:3000"
