"""SEC is asked for its ticker map again after a refusal — but not on every poll.

A failed fetch was never timestamped, so with the default User-Agent (which
www.sec.gov answers 403) every prefetch and every filing poll asked again,
which is how a caller earns SEC's fair-access block.
"""

from __future__ import annotations

import httpx
import pytest

from app.providers import edgar as edgar_module
from app.providers.edgar import FILINGS_TTL_SECONDS, MAP_RETRY_SECONDS
from tests.unit.test_edgar import edgar_ok, provider, submissions


@pytest.fixture
def clock(monkeypatch) -> dict:
    moment = {"now": 1_000_000.0}
    monkeypatch.setattr(edgar_module, "now_epoch", lambda: moment["now"])
    return moment


def refusing_map(asked: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        if "company_tickers" in str(request.url):
            asked["map"] += 1
            return httpx.Response(403)
        return edgar_ok(request)

    return handler


async def test_a_refused_map_is_not_asked_for_again_on_the_next_poll(clock):
    asked = {"map": 0}
    edgar = provider(refusing_map(asked))
    await edgar.prefetch("CELU")
    await edgar.refresh_filings("CELU")
    await edgar.refresh_filings("TLRY")
    assert asked["map"] == 1
    await edgar.close()


async def test_a_refused_map_is_asked_for_again_after_a_while(clock):
    asked = {"map": 0}
    edgar = provider(refusing_map(asked))
    await edgar.prefetch("CELU")
    clock["now"] += MAP_RETRY_SECONDS + 1
    await edgar.refresh_filings("CELU")
    assert asked["map"] == 2
    await edgar.close()


async def test_the_panel_still_says_why_while_it_waits(clock):
    edgar = provider(refusing_map({"map": 0}))
    await edgar.prefetch("CELU")
    await edgar.refresh_filings("CELU")
    assert edgar.note() == edgar_module.UNAVAILABLE_NOTE
    await edgar.close()


async def test_a_filer_with_no_filings_is_held_like_any_other_answer(clock):
    """An empty trail read as a miss and was held three times longer than a
    real answer — so a first 424B5 went unseen for fifteen minutes."""
    asked = {"submissions": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "submissions" in str(request.url):
            asked["submissions"] += 1
            payload = submissions()
            payload["filings"]["recent"] = {key: [] for key in payload["filings"]["recent"]}
            return httpx.Response(200, json=payload)
        return edgar_ok(request)

    edgar = provider(handler)
    await edgar.prefetch("CELU")
    clock["now"] += FILINGS_TTL_SECONDS + 1
    await edgar.prefetch("CELU")
    assert asked["submissions"] == 2
    await edgar.close()
