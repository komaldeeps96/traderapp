"""The news cache: backfill, the live merge, and article bodies."""

from __future__ import annotations

from app.domain.news import Catalyst
from app.services.news import (
    BACKFILL_TTL_SECONDS,
    MAX_ROWS,
    MAX_SYMBOLS,
    NewsService,
)


class FakeIBKR:
    """The three provider methods the service uses, and nothing else."""

    def __init__(self, rows=None, providers=None, article="<p>Body text</p>"):
        self.rows = rows or []
        self.providers = providers or [("DJ-N", "Dow Jones Global Equity Trader")]
        self.article = article
        self.history_calls: list[tuple[str, int, int]] = []
        self.article_calls: list[tuple[str, str]] = []
        self.provider_calls = 0

    async def fetch_news_providers(self):
        self.provider_calls += 1
        return self.providers

    async def fetch_historical_news(self, symbol, days, limit):
        self.history_calls.append((symbol, days, limit))
        return list(self.rows)

    async def fetch_news_article(self, provider_code, article_id):
        self.article_calls.append((provider_code, article_id))
        return self.article


def row(headline: str, time: int, article_id: str, provider: str = "DJ-N") -> dict:
    return {
        "headline": headline,
        "time": time,
        "article_id": article_id,
        "provider": provider,
    }


class TestBackfill:
    async def test_prefetch_populates_the_panel(self):
        ibkr = FakeIBKR([row("Celularity prices public offering", 1000, "a")])
        service = NewsService(ibkr)

        assert service.peek("CELU") == []
        await service.prefetch("CELU")

        headlines = service.peek("CELU")
        assert len(headlines) == 1
        assert headlines[0].catalyst is Catalyst.SUPPLY

    async def test_a_second_prefetch_inside_the_ttl_makes_no_request(self):
        ibkr = FakeIBKR([row("Something happened at the company", 1000, "a")])
        service = NewsService(ibkr)
        await service.prefetch("CELU")
        await service.prefetch("CELU")
        assert len(ibkr.history_calls) == 1

    async def test_the_window_is_re_read_once_the_ttl_lapses(self, monkeypatch):
        clock = {"now": 10_000.0}
        monkeypatch.setattr("app.services.news.now_epoch", lambda: clock["now"])
        ibkr = FakeIBKR([row("Something happened at the company", 1000, "a")])
        service = NewsService(ibkr)

        await service.prefetch("CELU")
        clock["now"] += BACKFILL_TTL_SECONDS + 1
        await service.prefetch("CELU")

        assert len(ibkr.history_calls) == 2

    async def test_without_a_provider_it_degrades_to_empty(self):
        service = NewsService(None)
        await service.prefetch("CELU")
        assert service.peek("CELU") == []
        assert await service.providers() == []

    async def test_entitled_providers_are_fetched_once(self):
        ibkr = FakeIBKR()
        service = NewsService(ibkr)
        assert (await service.providers())[0]["code"] == "DJ-N"
        await service.providers()
        assert ibkr.provider_calls == 1


class TestLiveMerge:
    async def test_a_new_headline_is_returned_for_broadcast(self):
        service = NewsService(FakeIBKR())
        added = service.add_live("CELU", row("Celularity prices public offering", 2000, "live1"))
        assert added is not None
        assert added.catalyst is Catalyst.SUPPLY

    async def test_the_bulletin_that_precedes_a_press_release_is_not_pushed_twice(self):
        """Dow Jones sends the starred bulletin seconds before the fuller
        version; the panel must not flash the same story twice."""
        ibkr = FakeIBKR(
            [
                row(
                    "Press Release: Celularity and MuseCell Innovations(R) Announce U.S. "
                    "Manufacturing Collaboration for the Dezawa",
                    2000,
                    "full",
                )
            ]
        )
        service = NewsService(ibkr)
        await service.prefetch("CELU")

        added = service.add_live(
            "CELU",
            row("* Celularity and MuseCell Innovations Announce U.S. Manufacturing Collab", 2000, "bulletin"),
        )
        assert added is None
        assert len(service.peek("CELU")) == 1

    async def test_the_same_headline_twice_does_not_duplicate(self):
        service = NewsService(FakeIBKR())
        service.add_live("CELU", row("Celularity prices public offering", 2000, "x"))
        service.add_live("CELU", row("Celularity prices public offering", 2000, "x"))
        assert len(service.peek("CELU")) == 1

    async def test_a_row_without_an_article_id_is_ignored(self):
        service = NewsService(FakeIBKR())
        assert service.add_live("CELU", row("Headline with no id", 2000, "")) is None
        assert service.peek("CELU") == []

    async def test_live_and_backfill_land_in_one_list(self):
        ibkr = FakeIBKR([row("Older story about the company board", 1000, "old")])
        service = NewsService(ibkr)
        await service.prefetch("CELU")
        service.add_live("CELU", row("Celularity prices public offering", 5000, "new"))

        headlines = service.peek("CELU")
        assert [headline.article_id for headline in headlines] == ["new", "old"]


class TestArticles:
    async def test_fetches_and_caches_a_body(self):
        ibkr = FakeIBKR()
        service = NewsService(ibkr)
        assert await service.article("DJ-N", "a1") == "<p>Body text</p>"
        await service.article("DJ-N", "a1")
        # An article is immutable once published; re-fetching spends an IBKR
        # request on a string we already hold.
        assert len(ibkr.article_calls) == 1

    async def test_an_empty_body_is_not_cached(self):
        ibkr = FakeIBKR(article="")
        service = NewsService(ibkr)
        await service.article("DJ-N", "a1")
        await service.article("DJ-N", "a1")
        assert len(ibkr.article_calls) == 2

    async def test_without_a_provider_there_is_no_body(self):
        assert await NewsService(None).article("DJ-N", "a1") == ""


class TestBounds:
    async def test_a_symbol_stops_accumulating_raw_wire_rows(self):
        """A busy session must not grow one symbol's buffer without limit."""
        service = NewsService(FakeIBKR())
        for index in range(MAX_ROWS + 50):
            service.add_live("CELU", row(f"Story number {index} about the company", 1000 + index, f"a{index}"))
        assert len(service._raw["CELU"]) == MAX_ROWS

    async def test_trimming_keeps_the_newest(self):
        service = NewsService(FakeIBKR())
        for index in range(MAX_ROWS + 50):
            service.add_live("CELU", row(f"Story number {index} about the company", 1000 + index, f"a{index}"))
        held = service._raw["CELU"]
        newest = f"a{MAX_ROWS + 49}"
        assert newest in held
        assert "a0" not in held


class TestEviction:
    async def test_a_day_of_switching_tickers_does_not_accumulate(self):
        service = NewsService(FakeIBKR())
        for index in range(MAX_SYMBOLS + 10):
            service.add_live(f"SYM{index}", row(f"Story number {index} about things", 1000, f"a{index}"))
        assert len(service._raw) <= MAX_SYMBOLS
