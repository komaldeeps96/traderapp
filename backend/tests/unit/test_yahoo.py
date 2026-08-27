"""The Yahoo float provider: crumb dance, degradation, parsing."""

from __future__ import annotations

import httpx
import pytest

from app.providers.yahoo import YahooFloatProvider, _parse_float


def summary(float_shares: float | None = 3_500_000):
    stats = {} if float_shares is None else {"floatShares": {"raw": float_shares}}
    return {"quoteSummary": {"result": [{"defaultKeyStatistics": stats}]}}


def transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def yahoo_ok(request: httpx.Request) -> httpx.Response:
    if "getcrumb" in str(request.url):
        return httpx.Response(200, text="abc123")
    if "quoteSummary" in str(request.url):
        assert request.url.params["crumb"] == "abc123"
        return httpx.Response(200, json=summary())
    return httpx.Response(404)


class TestParse:
    def test_reads_the_float(self):
        assert _parse_float(summary()) == pytest.approx(3_500_000)

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"quoteSummary": {"result": []}},
            summary(float_shares=None),
            {"quoteSummary": {"result": [{"defaultKeyStatistics": {"floatShares": {}}}]}},
        ],
    )
    def test_missing_pieces_read_as_none(self, payload):
        assert _parse_float(payload) is None

    def test_a_zero_float_is_no_float(self):
        assert _parse_float(summary(float_shares=0)) is None


class TestProvider:
    async def test_prefetch_then_peek(self):
        provider = YahooFloatProvider(transport=transport(yahoo_ok))
        assert provider.peek_float("FGI") is None
        await provider.prefetch("FGI")
        assert provider.peek_float("FGI") == pytest.approx(3_500_000)
        await provider.close()

    async def test_a_stale_crumb_is_refreshed_once(self):
        state = {"crumbs": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if "getcrumb" in str(request.url):
                state["crumbs"] += 1
                return httpx.Response(200, text=f"crumb{state['crumbs']}")
            if "quoteSummary" in str(request.url):
                if request.url.params["crumb"] == "crumb1":
                    return httpx.Response(401)
                return httpx.Response(200, json=summary())
            return httpx.Response(404)

        provider = YahooFloatProvider(transport=transport(handler))
        await provider.prefetch("FGI")
        assert provider.peek_float("FGI") == pytest.approx(3_500_000)
        assert state["crumbs"] == 2
        await provider.close()

    async def test_a_throttled_crumb_host_falls_back_to_the_other(self):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "getcrumb" in url:
                if "query1" in url:
                    return httpx.Response(429, text="Too Many Requests")
                return httpx.Response(200, text="abc123")
            if "quoteSummary" in url:
                return httpx.Response(200, json=summary())
            return httpx.Response(404)

        provider = YahooFloatProvider(transport=transport(handler))
        await provider.prefetch("FGI")
        assert provider.peek_float("FGI") == pytest.approx(3_500_000)
        await provider.close()

    async def test_a_consent_wall_degrades_to_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "getcrumb" in str(request.url):
                return httpx.Response(200, text="<html>consent</html>")
            return httpx.Response(200, json=summary())

        provider = YahooFloatProvider(transport=transport(handler))
        await provider.prefetch("FGI")
        assert provider.peek_float("FGI") is None
        await provider.close()

    async def test_a_network_error_degrades_to_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        provider = YahooFloatProvider(transport=transport(handler))
        await provider.prefetch("FGI")
        assert provider.peek_float("FGI") is None
        await provider.close()

    async def test_a_miss_is_cached_and_not_rehit_per_tick(self):
        calls = {"summary": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if "getcrumb" in str(request.url):
                return httpx.Response(200, text="abc")
            if "quoteSummary" not in str(request.url):
                return httpx.Response(404)  # the cookie request
            calls["summary"] += 1
            return httpx.Response(500)

        provider = YahooFloatProvider(transport=transport(handler))
        await provider.prefetch("FGI")
        await provider.prefetch("FGI")
        assert calls["summary"] == 1
        await provider.close()
