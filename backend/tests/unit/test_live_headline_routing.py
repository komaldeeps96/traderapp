"""Which of the market's headlines reach the terminal.

The socket carries every headline published, so something has to decide which
are worth keeping — the alternative is folding market-wide news into a
per-symbol cache that holds forty symbols and watching it thrash.

The rule is: charts open now, plus the watchlist. That second half is the
point of the whole feature. IBKR's live headlines ride generic tick 292 and
follow only the open chart, so a name on the watchlist could run on news with
nothing on screen to say so.
"""

from __future__ import annotations

import pytest

from app.core.settings import (
    AlpacaSettings,
    EdgarSettings,
    IBKRSettings,
    RegimeSettings,
    ScannerSettings,
    Settings,
)
from app.services.container import AppContainer


@pytest.fixture
def container(tmp_path):
    return AppContainer(
        Settings(
            alpaca=AlpacaSettings(key_id="k", secret_key="s", news_stream=False),
            ibkr=IBKRSettings(enabled=False),
            scanner=ScannerSettings(enabled=False),
            regime=RegimeSettings(enabled=False),
            edgar=EdgarSettings(enabled=False),
            state_file=tmp_path / "state.yaml",
            log_level="WARNING",
        )
    )


def entry(symbols, identifier=1, headline="Wetour Robotics Wins A Contract", content="<p>x</p>"):
    return {
        "T": "n",
        "id": identifier,
        "headline": headline,
        "created_at": "2026-08-31T14:14:47Z",
        "url": f"https://www.benzinga.com/news/{identifier}",
        "symbols": symbols,
        "content": content,
    }


def broadcasts(container) -> list[dict]:
    sent: list[dict] = []
    container.hub.broadcast = sent.append
    return sent


class TestRouting:
    async def test_a_headline_for_a_watchlist_name_is_pushed(self, container):
        """The reason this exists: nothing about WETO is on screen."""
        await container.watchlist.add("WETO")
        sent = broadcasts(container)
        await container._on_live_headline(entry(["WETO"]))
        assert [m["symbol"] for m in sent] == ["WETO"]

    async def test_a_headline_for_nothing_tracked_is_dropped(self, container):
        """The common case on a market-wide feed, and it must cost nothing."""
        sent = broadcasts(container)
        await container._on_live_headline(entry(["ZZZZ"]))
        assert sent == []
        assert container.news.peek("ZZZZ") == []

    async def test_one_story_can_reach_several_tracked_names(self, container):
        await container.watchlist.add("WETO")
        await container.watchlist.add("FNGR")
        sent = broadcasts(container)
        await container._on_live_headline(entry(["WETO", "ZZZZ", "FNGR"]))
        assert sorted(m["symbol"] for m in sent) == ["FNGR", "WETO"]

    async def test_only_the_tracked_half_of_a_story_is_kept(self, container):
        await container.watchlist.add("WETO")
        await container._on_live_headline(entry(["WETO", "ZZZZ"]))
        assert len(container.news.peek("WETO")) == 1
        assert container.news.peek("ZZZZ") == []

    async def test_a_lower_case_symbol_still_matches(self, container):
        await container.watchlist.add("WETO")
        sent = broadcasts(container)
        await container._on_live_headline(entry(["weto"]))
        assert [m["symbol"] for m in sent] == ["WETO"]

    async def test_the_same_headline_twice_pushes_once(self, container):
        """A socket that reconnects can replay; the panel must not flash."""
        await container.watchlist.add("WETO")
        sent = broadcasts(container)
        await container._on_live_headline(entry(["WETO"]))
        await container._on_live_headline(entry(["WETO"]))
        assert len(sent) == 1


class TestMalformedFrames:
    @pytest.mark.parametrize("symbols", [None, "WETO", 7, {}])
    async def test_a_frame_without_a_symbol_list_is_dropped(self, container, symbols):
        sent = broadcasts(container)
        await container._on_live_headline(entry(symbols))
        assert sent == []

    async def test_a_frame_missing_its_headline_is_dropped(self, container):
        await container.watchlist.add("WETO")
        sent = broadcasts(container)
        await container._on_live_headline(entry(["WETO"], headline=""))
        assert sent == []

    async def test_an_unparseable_timestamp_is_dropped(self, container):
        """Better no row than a row sorted to 1970."""
        await container.watchlist.add("WETO")
        sent = broadcasts(container)
        payload = entry(["WETO"])
        payload["created_at"] = "whenever"
        await container._on_live_headline(payload)
        assert sent == []


class TestTheBodyRidesAlong:
    async def test_an_article_opened_from_a_live_headline_costs_no_request(self, container):
        await container.watchlist.add("WETO")
        await container._on_live_headline(entry(["WETO"], content="<p>The company said…</p>"))
        assert await container.news.article("BZ-ALP", "bz:1") == "<p>The company said…</p>"

    async def test_a_headline_with_no_body_caches_nothing(self, container):
        await container.watchlist.add("WETO")
        await container._on_live_headline(entry(["WETO"], content=""))
        assert await container.news.article("BZ-ALP", "bz:1") == ""
