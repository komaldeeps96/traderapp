"""The AI tab: the whole screen, judged.

The news reader has one input and one question. This has every input the
terminal holds and the question the trader is actually asking, so the work
here is not the process — that lives in ``claude_cli.py`` — it is the
*assembly*: pulling the five pillars, the level ladder, the tape conditions,
the dilution read, the regime and the news score out of six different
services and handing them over as one moment.

Assembled on the server rather than posted by the browser, deliberately. The
frontend has all these numbers on screen already and it would be less code to
let it send them — but then the thing being judged is whatever the client
says it is, and the judgement is only worth what its inputs are worth. The
server owns the data; the server builds the snapshot.

Two things make this different from the news reading and both come from the
same fact: **a setup is a moving target**.

It cannot be cached against its inputs. Price changes every tick, so a digest
of the snapshot would never hit twice and every open of the tab would spend a
process. So a reading is held per symbol and *dated*, and the panel is told
when the tape has moved out from under it — two percent of price, or five
minutes, whichever comes first. That number is deliberately tight: on a name
doing what this terminal is for, two percent is under a minute, and a
judgement that quietly ages into wrongness is worse than one that says it is
old.

And it does not run by itself. The news reading follows the feed because the
feed changes rarely; this one is asked for — opening the tab, or pressing
refresh — because otherwise a chart left open would spend a cent a minute
saying much the same thing.
"""

from __future__ import annotations

import asyncio
import logging
import math

from ..core.clock import now_epoch
from ..core.settings import SetupAISettings
from ..domain.setup_ai import (
    SCHEMA,
    Judgement,
    JudgementError,
    Snapshot,
    build_prompt,
    to_judgement,
)
from ..domain.setup_prompt import SYSTEM_PROMPT
from ..domain.timeframes import Timeframe
from ..indicators.engine import latest_values
from .claude_cli import ClaudeReader, ReaderError, parse_output

logger = logging.getLogger(__name__)

# Symbols whose judgement is kept. A reading for a name the trader left an
# hour ago is a reading nothing will ask for again.
MAX_SYMBOLS = 20


class SetupAIService:
    """One judgement per symbol, produced on request."""

    def __init__(self, settings: SetupAISettings, *, container):
        self._settings = settings
        self._reader = ClaudeReader(settings)
        # The container rather than six injected services: this reads from
        # nearly everything the terminal has, and threading each one through
        # would be a longer constructor than it is a class.
        self._container = container
        self._cache: dict[str, Judgement] = {}
        self._running: dict[str, asyncio.Task[Judgement]] = {}
        self._order: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    async def judge(self, symbol: str, *, force: bool = False) -> dict:
        """The panel's payload: a judgement, or the reason there is not one.

        Always a dict rather than a raise. "The CLI is not installed", "the
        chart has not loaded yet" and "the reader timed out" are all ordinary
        states of the world, and a panel that says which one is far more use
        than an error banner.
        """
        blocked = self._blocked()
        if blocked is not None:
            return blocked

        snapshot = self.snapshot(symbol)
        if snapshot is None or snapshot.price is None:
            return _unavailable("no-data", f"No live chart for {symbol} to judge yet.")

        held = self._cache.get(symbol)
        if held is not None and not force:
            return _ready(held, snapshot.price)

        running = self._running.get(symbol)
        if running is None:
            running = asyncio.create_task(self._read(symbol, snapshot))
            self._running[symbol] = running

        try:
            result = await asyncio.shield(running)
        except (JudgementError, ReaderError) as exc:
            return _unavailable("failed", str(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Setup judgement failed for %s: %s", symbol, exc)
            return _unavailable("failed", "The reader could not be run.")
        return _ready(result, self._price(symbol))

    def _blocked(self) -> dict | None:
        """Why no judgement can happen at all, before a snapshot is built."""
        if not self._settings.enabled:
            return _unavailable("off", "Setup judgements are switched off in settings.")
        if self._reader.resolve_binary() is None:
            return _unavailable(
                "no-cli", f"The {self._settings.command!r} CLI was not found on this machine."
            )
        return None

    def peek(self, symbol: str) -> Judgement | None:
        return self._cache.get(symbol)

    def snapshot(self, symbol: str) -> Snapshot | None:
        """One moment, assembled from everything the terminal holds.

        Every part is optional and each is fetched behind its own guard: the
        judge is told "unknown" for anything missing, which is a state the
        prompt handles explicitly, and one absent service must not cost the
        panel the other five.
        """
        container = self._container
        info = _safe(lambda: container.symbol_info.build(symbol)) or {}
        values = _safe(lambda: self._latest_values(symbol)) or {}
        price = self._price(symbol)

        return Snapshot(
            symbol=symbol,
            now=now_epoch(),
            price=price,
            info=info,
            quote=_safe(lambda: self._quote(symbol)) or {},
            levels=_safe(lambda: self._levels(values, price)) or [],
            headroom=_safe(lambda: self._headroom(values, price)),
            regime=_safe(lambda: (container.regime_payload() or {}).get("regime")),
            news=_safe(lambda: self._news(symbol)),
            values=values,
        )

    # ── the pieces ─────────────────────────────────────────────────────

    def _timeframe(self) -> Timeframe:
        """The chart's own timeframe, so the levels match what is drawn."""
        return Timeframe(self._container.state.timeframe)

    def _price(self, symbol: str) -> float | None:
        update = _safe(
            lambda: self._container.market_data.build_update(symbol, self._timeframe())
        )
        if update and update.get("bar"):
            return update["bar"].get("c")
        return None

    def _latest_values(self, symbol: str) -> dict:
        """Every indicator's current value — the levels and WRVOL alike.

        The same series the chart draws from, read at its right edge. This is
        why the level ladder in the prompt is the ladder in the sidebar and
        not a second computation that could disagree with it.
        """
        return latest_values(
            self._container.market_data.series(symbol, self._timeframe())
        )

    def _quote(self, symbol: str) -> dict:
        quote = self._container.quotes.get(symbol)
        if quote is None:
            return {}
        return {
            "bid": quote.bid,
            "ask": quote.ask,
            "bid_size": quote.bid_size,
            "ask_size": quote.ask_size,
        }

    def _level_specs(self) -> list:
        """The specs that draw a price line, in the sidebar's own definition.

        The same two groups the frontend's ``isKeyLevel`` uses, so the ladder
        the judge reads is the ladder the trader is looking at.
        """
        return [spec for spec in self._container.specs if spec.group in _LEVEL_GROUPS]

    def _levels(self, values: dict, price: float | None) -> list[dict]:
        """The ladder, nearest the price first.

        Sorted by distance rather than by value because the prompt is cut at
        a dozen rows: what matters is the levels around the price, not the
        top of a list that starts at the all-time high.
        """
        rows = []
        for spec in self._level_specs():
            value = values.get(spec.id)
            # NaN passes `isinstance(x, float)` and every comparison against
            # it is False, so an unguarded one would reach the prompt as a
            # level with a real-looking price.
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                continue
            rows.append({"id": spec.id, "label": spec.label, "value": float(value)})
        if price:
            rows.sort(key=lambda row: abs(row["value"] / price - 1))
        else:
            rows.sort(key=lambda row: -row["value"])
        return rows

    def _headroom(self, values: dict, price: float | None) -> dict | None:
        """The nearest level overhead — what decides how far this can run.

        None means the ladder is empty and nothing is known; a row with no
        label means blue sky, which is a different and much stronger claim.
        """
        if not price:
            return None
        above = [row for row in self._levels(values, price) if row["value"] > price]
        if not above:
            return {"label": "", "value": None, "percent": None}
        nearest = min(above, key=lambda row: row["value"])
        return {
            "label": nearest["label"],
            "value": nearest["value"],
            "percent": (nearest["value"] / price - 1) * 100,
        }

    def _news(self, symbol: str) -> dict | None:
        """The news reading, if one is already held.

        Deliberately ``peek`` and not a fetch: the judge should not spawn a
        second process behind the first, and a setup read is worth having
        with the catalyst marked unknown. The panel prompts for the news tab
        instead, which is also where the reasoning behind that score lives.
        """
        brief = self._container.news_ai.peek(symbol)
        return brief.to_dict() if brief is not None else None

    # ── running one ────────────────────────────────────────────────────

    async def _read(self, symbol: str, snapshot: Snapshot) -> Judgement:
        try:
            stdout = await self._reader.run(
                prompt=build_prompt(snapshot),
                schema=SCHEMA,
                system_prompt=SYSTEM_PROMPT,
            )
            judgement = to_judgement(
                parse_output(stdout),
                symbol=symbol,
                price=snapshot.price,
                generated_at=int(now_epoch()),
                model=self._settings.model,
            )
        finally:
            self._running.pop(symbol, None)
        self._cache[symbol] = judgement
        self._remember(symbol)
        return judgement

    def _remember(self, symbol: str) -> None:
        if symbol in self._order:
            self._order.remove(symbol)
        self._order.append(symbol)
        while len(self._order) > MAX_SYMBOLS:
            self._cache.pop(self._order.pop(0), None)


_LEVEL_GROUPS = frozenset({"key_levels", "daily_ma"})


def _safe(call):
    """A part of the snapshot, or None. One absent service is not a failure."""
    try:
        return call()
    except Exception as exc:
        logger.debug("setup snapshot part unavailable: %s", exc)
        return None


def _ready(judgement: Judgement, price: float | None) -> dict:
    return {
        "status": "ready",
        "available": True,
        "judgement": judgement.to_dict(price_now=price, now=now_epoch()),
    }


def _unavailable(status: str, note: str) -> dict:
    return {"status": status, "available": False, "note": note, "judgement": None}
