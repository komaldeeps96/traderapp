"""The news panel's top half: one session, read and scored, by Claude Code.

The process, the flags and the safety argument live in ``claude_cli.py`` —
this file is the part that stops it being expensive.

A reading is cached against the *article ids* it covers, so switching away
from a symbol and back costs nothing, and a live headline that collapsed into
a story already on screen — the usual case, the starred bulletin ahead of its
own press release — does not trigger a re-read. When the ids genuinely do
change there is still a cooldown, because a busy morning delivers a headline
a minute and each one would otherwise start a process.

One reading per symbol at a time. Two clients, or a client and a live
headline, asking together share the one process rather than starting two.
"""

from __future__ import annotations

import asyncio
import logging

from ..core.clock import now_epoch
from ..core.settings import NewsAISettings
from ..domain.news import to_paragraphs
from ..domain.news_ai import (
    SCHEMA,
    Brief,
    BriefError,
    NewsWindow,
    bodies_wanted,
    build_prompt,
    digest,
    select_session,
    to_brief,
)
from ..domain.news_prompt import SYSTEM_PROMPT
from .claude_cli import ClaudeReader, ReaderError, parse_output

logger = logging.getLogger(__name__)

# Symbols whose reading is kept in memory. Matches the news cache's own
# ceiling: a brief for a symbol whose headlines have been evicted is a brief
# nothing will ever ask for again.
MAX_SYMBOLS = 40


class NewsAIService:
    """Per-symbol briefs, produced by a child ``claude`` process."""

    def __init__(self, settings: NewsAISettings, news):
        self._settings = settings
        self._reader = ClaudeReader(settings)
        # The news cache, for the day's headlines and their article bodies.
        # Typed loosely for the same reason NewsService types its providers
        # that way: two methods are used and a test should not have to build
        # the rest.
        self._news = news
        # symbol -> (digest, brief). The digest is what makes the cache
        # correct rather than merely fast: it changes exactly when the set of
        # stories the model read changes.
        self._cache: dict[str, tuple[str, Brief]] = {}
        self._started_at: dict[str, float] = {}
        self._running: dict[str, asyncio.Task[Brief]] = {}

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    def resolve_binary(self) -> str | None:
        return self._reader.resolve_binary()

    def peek(self, symbol: str) -> Brief | None:
        """The brief held for a symbol, if it still covers the current day."""
        held = self._cache.get(symbol)
        if held is None:
            return None
        current = digest(symbol, select_session(self._news.peek(symbol), now_epoch()))
        return held[1] if held[0] == current else None

    async def brief(self, symbol: str, *, force: bool = False) -> dict:
        """The panel's payload: a brief, or the reason there is not one.

        Always a dict rather than a raise. Every branch here is an ordinary
        state of the world — the CLI is not installed, the company published
        nothing today, a reading is already running — and a panel that says
        which one is far more use than one showing an error banner.
        """
        blocked = self._blocked()
        if blocked is not None:
            return blocked

        selection = select_session(self._news.peek(symbol), now_epoch())
        if not selection:
            return _unavailable("no-news", "Nothing to summarise — no headlines in 30 days.")

        key = digest(symbol, selection)
        held = self._cache.get(symbol)
        if held is not None and held[0] == key and not force:
            return _ready(held[1].to_dict())

        served = self._start(symbol, selection, held=held, force=force)
        return await self._collect(symbol, served) if isinstance(served, asyncio.Task) else served

    def _start(self, symbol: str, selection: NewsWindow, *, held, force: bool):
        """The reading in flight for this symbol, or a payload to serve now.

        Three cases. One is already running and is joined rather than
        duplicated; the cooldown has not elapsed, so the last reading is
        served and marked behind; or a new process is started.
        """
        running = self._running.get(symbol)
        if running is not None:
            return running

        since = now_epoch() - self._started_at.get(symbol, 0.0)
        if not force and held is not None and since < self._settings.min_interval_seconds:
            # New headlines, but the last reading is minutes old. Serve it and
            # say it is behind rather than starting a process for a row the
            # reader can already see in the list below.
            return _ready({**held[1].to_dict(), "stale": True})

        self._started_at[symbol] = now_epoch()
        task = asyncio.create_task(self._read(symbol, selection))
        self._running[symbol] = task
        return task

    async def _collect(self, symbol: str, running: asyncio.Task[Brief]) -> dict:
        """Wait on a reading, turning every way it can fail into a line.

        Shielded, because two clients share the one process: the first to
        give up on its own request must not cancel the reading the second is
        still waiting for.
        """
        try:
            result = await asyncio.shield(running)
        except (BriefError, ReaderError) as exc:
            return _unavailable("failed", str(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("News summary failed for %s: %s", symbol, exc)
            return _unavailable("failed", "The reader could not be run.")
        return _ready(result.to_dict())

    def _blocked(self) -> dict | None:
        """Why no reading can happen at all, independent of the symbol."""
        if not self._settings.enabled:
            return _unavailable("off", "News summaries are switched off in settings.")
        if self.resolve_binary() is None:
            return _unavailable(
                "no-cli",
                f"The {self._settings.command!r} CLI was not found on this machine.",
            )
        return None

    async def _read(self, symbol: str, selection: NewsWindow) -> Brief:
        try:
            bodies = await self._bodies(symbol, selection)
            prompt = build_prompt(symbol, selection, bodies)
            stdout = await self._reader.run(
                prompt=prompt, schema=SCHEMA, system_prompt=SYSTEM_PROMPT
            )
            brief = to_brief(
                parse_output(stdout),
                symbol=symbol,
                selection=selection,
                generated_at=int(now_epoch()),
                model=self._settings.model,
            )
        finally:
            self._running.pop(symbol, None)
        self._cache[symbol] = (digest(symbol, selection), brief)
        self._evict()
        return brief

    async def _bodies(self, symbol: str, selection: NewsWindow) -> dict[str, list[str]]:
        """The article text for the day's own stories.

        Fetched one at a time and each allowed to fail: a body is what turns
        "Announces Strategic Partnership" into knowing who with and for how
        much, but a missing one is a thinner reading rather than no reading.
        """
        bodies: dict[str, list[str]] = {}
        for row in bodies_wanted(selection):
            try:
                raw = await self._news.article(row.provider, row.article_id)
            except Exception as exc:
                logger.debug("No body for %s %s: %s", symbol, row.article_id, exc)
                continue
            if raw:
                bodies[row.article_id] = to_paragraphs(raw)
        return bodies

    def _evict(self) -> None:
        if len(self._cache) <= MAX_SYMBOLS:
            return
        stale = sorted(self._cache, key=lambda symbol: self._started_at.get(symbol, 0.0))
        for symbol in stale[: len(self._cache) - MAX_SYMBOLS]:
            self._cache.pop(symbol, None)
            self._started_at.pop(symbol, None)


def _ready(brief: dict) -> dict:
    return {"status": "ready", "available": True, "brief": brief}


def _unavailable(status: str, note: str) -> dict:
    return {"status": status, "available": False, "note": note, "brief": None}
