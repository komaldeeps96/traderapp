"""The news panel's cache: backfill, live merge, and article bodies.

Two sources. IBKR is the entitled one — eight feeds, thirty days of headlines,
full article bodies — while everything fundamental on the same connection
answers error 10358. Alpaca's Benzinga feed is the second, and it is here
because the first goes quiet on some of exactly the companies this terminal
exists for: WETO returned its own halt and its own resume and nothing else
while Benzinga had ten rows, and AEMD's catalyst was there when IBKR had
nothing in thirty days.

Both land in one per-symbol dict keyed by article id, so ``build`` dedupes
*across* them: a press release carried by Dow Jones and by Benzinga is one
row, not two. The cleaning, catalyst tagging and deduplication all live in
``domain/news.py``.

What this adds is state. Headlines arrive two ways — a thirty-day backfill
when a symbol is opened, and single live headlines on generic tick 292 — and
both have to land in one list that is deduplicated *as a whole*. A live
headline is very often the starred bulletin whose fuller press-release version
arrives seconds later, so merging by appending would show the story twice. The
raw rows are therefore kept per symbol and the whole set is rebuilt on every
change, which is cheap at fifty rows and is the only way the dedup stays
correct across the two paths.

Article bodies are cached separately and indefinitely: an article is immutable
once published, and re-fetching one the user clicked back to would spend an
IBKR request on a string we already have.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from ..core.clock import now_epoch
from ..domain.news import BENZINGA_CODE, Headline, build, to_benzinga_row

logger = logging.getLogger(__name__)

# Thirty days is what the workflow needs — the offering that repriced the
# stock last week, not the one from last year — and matches what the probe
# confirmed the feeds answer with.
BACKFILL_DAYS = 30
BACKFILL_LIMIT = 50

# A symbol's backfill is re-fetched no more often than this. Live headlines
# arrive on the stream regardless, so the backfill only exists to fill in what
# happened before the symbol was opened.
BACKFILL_TTL_SECONDS = 300.0

# Raw wire rows kept per symbol. Well above the backfill limit so a busy
# session's live headlines do not evict the history they arrived beside.
MAX_ROWS = 400

# Symbols kept in memory at once — a session switching tickers all day should
# not accumulate every one of them.
MAX_SYMBOLS = 40


class NewsService:
    """Per-symbol headline state, fed by backfill and by the live tick."""

    def __init__(self, provider=None, alpaca=None):
        # The IBKR provider, or None when it is disabled or absent. Typed
        # loosely on purpose: this service only needs three methods and
        # should not drag the provider's import into a test that stubs it.
        self._provider = provider
        # Alpaca, for the Benzinga feed. Independent of the one above: with
        # no TWS running this is the only source there is, and it still works.
        self._alpaca = alpaca
        # symbol -> article_id -> raw row. A dict keyed by article id is what
        # makes the live merge idempotent: the same headline arriving twice
        # replaces itself rather than duplicating.
        self._raw: dict[str, dict[str, dict]] = {}
        self._fetched_at: dict[str, float] = {}
        self._articles: dict[tuple[str, str], str] = {}
        self._providers: list[dict] | None = None

    def peek(self, symbol: str) -> list[Headline]:
        """The deduplicated, tagged headlines held for a symbol."""
        rows = self._raw.get(symbol)
        return build(list(rows.values())) if rows else []

    async def providers(self) -> list[dict]:
        """The feeds behind the panel, for its footer."""
        if self._providers is not None:
            return self._providers
        entries: list[dict] = []
        if self._provider is not None:
            with contextlib.suppress(Exception):
                entries = [
                    {"code": code, "name": name}
                    for code, name in await self._provider.fetch_news_providers()
                ]
        if self._alpaca is not None:
            entries.append({"code": BENZINGA_CODE, "name": "Benzinga (via Alpaca)"})
        self._providers = entries
        return entries

    async def prefetch(self, symbol: str) -> None:
        """Warm the backfill; called at subscribe time beside the others.

        Both sources are asked at once and each is allowed to fail on its own.
        One feed being down is the ordinary case this exists to survive — the
        whole reason there are two — so a raise from either must not cost the
        panel the rows the other returned.
        """
        if self._provider is None and self._alpaca is None:
            return
        if now_epoch() - self._fetched_at.get(symbol, 0.0) < BACKFILL_TTL_SECONDS:
            return
        # Stamped before the await, so a slow fetch cannot be started twice by
        # two subscribes landing together.
        self._fetched_at[symbol] = now_epoch()
        wire, benzinga = await asyncio.gather(
            self._from_ibkr(symbol), self._from_alpaca(symbol), return_exceptions=True
        )
        for rows in (wire, benzinga):
            if isinstance(rows, list) and rows:
                self._merge(symbol, rows)

    async def _from_ibkr(self, symbol: str) -> list[dict]:
        if self._provider is None:
            return []
        try:
            return await self._provider.fetch_historical_news(
                symbol, BACKFILL_DAYS, BACKFILL_LIMIT
            )
        except Exception as exc:
            logger.warning("IBKR news failed for %s: %s", symbol, exc)
            return []

    async def _from_alpaca(self, symbol: str) -> list[dict]:
        """Benzinga rows, mapped onto the shape ``build`` already reads."""
        if self._alpaca is None:
            return []
        try:
            raw = await self._alpaca.fetch_news(symbol, days=BACKFILL_DAYS, limit=BACKFILL_LIMIT)
        except Exception as exc:
            logger.warning("Alpaca news failed for %s: %s", symbol, exc)
            return []

        rows: list[dict] = []
        for entry in raw:
            row = to_benzinga_row(entry)
            if row is None:
                continue
            # The body arrives with the headline here, so an article opened
            # from this source costs no request at all.
            body = entry.get("content") or entry.get("summary") or ""
            if body:
                self._articles[(BENZINGA_CODE, row["article_id"])] = str(body)
            rows.append(row)
        return rows

    def add_live(self, symbol: str, row: dict) -> Headline | None:
        """Fold one live headline in, returning the row it produced.

        ``None`` when the headline collapsed into a story already on screen —
        the usual case for the starred bulletin that precedes a press release
        — so the caller can broadcast only genuinely new rows.
        """
        before = {headline.article_id for headline in self.peek(symbol)}
        self._merge(symbol, [row])
        for headline in self.peek(symbol):
            if headline.article_id not in before:
                return headline
        return None

    async def article(self, provider_code: str, article_id: str) -> str:
        """The article body, cached forever — a published article is fixed."""
        key = (provider_code, article_id)
        cached = self._articles.get(key)
        if cached is not None:
            return cached
        # A Benzinga body arrives with its headline and is cached then. Missing
        # here means the row predates a restart — and asking IBKR for an id
        # from another source would spend a request to be told no.
        if provider_code == BENZINGA_CODE or self._provider is None:
            return ""
        body = await self._provider.fetch_news_article(provider_code, article_id)
        if body:
            self._articles[key] = body
        return body

    def remember_article(self, article_id: str, body: str) -> None:
        """Cache a body that arrived alongside its headline.

        Benzinga sends the article with the notification, so opening one from
        the live stream costs no request at all.
        """
        if body:
            self._articles[(BENZINGA_CODE, article_id)] = body

    def _merge(self, symbol: str, rows: list[dict]) -> None:
        held = self._raw.setdefault(symbol, {})
        for row in rows:
            article_id = str(row.get("article_id") or "")
            if not article_id:
                continue
            held[article_id] = row
        if len(held) > MAX_ROWS:
            # Oldest first out. Rebuilt rather than trimmed in place because
            # the wire does not deliver in time order.
            keep = sorted(held.items(), key=lambda item: item[1].get("time") or 0, reverse=True)
            self._raw[symbol] = dict(keep[:MAX_ROWS])
        self._evict()

    def _evict(self) -> None:
        if len(self._raw) <= MAX_SYMBOLS:
            return
        stale = sorted(self._raw, key=lambda symbol: self._fetched_at.get(symbol, 0.0))
        for symbol in stale[: len(self._raw) - MAX_SYMBOLS]:
            self._raw.pop(symbol, None)
            self._fetched_at.pop(symbol, None)
