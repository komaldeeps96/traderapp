"""Watches the focused symbol's EDGAR trail for an offering landing mid-session.

This is the payoff of having the filing trail at all. A shelf takedown priced
into a spike you are long is the most expensive surprise in this style of
trading, and it is public the moment EDGAR accepts it — usually well before it
reaches a headline. Polling one company's submissions document once a minute
costs a single request against a ten-per-second allowance.

Only dilution and distress filings raise an alert. A Form 4 and a routine 8-K
are worth a row in the panel and nothing more; waking a trader mid-trade for
an insider's tax withholding would train them to ignore the thing that
matters.

The first poll after a symbol is opened establishes the baseline rather than
alerting. Everything in the trail is by definition already filed, and opening
a chart on a company that raised last week must not fire an alarm about it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from ..domain.filings import Filing, FilingKind

logger = logging.getLogger(__name__)

# The kinds worth interrupting for.
ALERT_KINDS = frozenset({FilingKind.DILUTION, FilingKind.DISTRESS})

FilingAlert = Callable[[str, Filing], Awaitable[None]]


class FilingWatchService:
    """Polls one symbol at a time — whichever chart is open."""

    def __init__(self, edgar, poll_seconds: float = 60.0):
        self._edgar = edgar
        self._poll_seconds = poll_seconds
        self._symbol: str | None = None
        # symbol -> accession numbers already seen. Keyed by symbol so
        # switching away and back does not replay the baseline as alerts.
        self._seen: dict[str, set[str]] = {}
        self._handlers: list[FilingAlert] = []
        self._task: asyncio.Task | None = None

    def on_alert(self, handler: FilingAlert) -> None:
        self._handlers.append(handler)

    async def start(self) -> None:
        if self._edgar is None or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def watch(self, symbol: str) -> None:
        """Follow a different symbol. Cheap: the poll picks it up next tick."""
        self._symbol = symbol

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_seconds)
            symbol = self._symbol
            if symbol is None:
                continue
            try:
                await self._poll(symbol)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("filing poll failed for %s", symbol, exc_info=True)

    async def _poll(self, symbol: str) -> None:
        rows = await self._edgar.refresh_filings(symbol)
        if not rows:
            return
        known = self._seen.get(symbol)
        current = {row.accession for row in rows}
        if known is None:
            # First sight of this symbol: everything here is already history.
            self._seen[symbol] = current
            return

        fresh = [row for row in rows if row.accession not in known and row.kind in ALERT_KINDS]
        self._seen[symbol] = current | known
        for row in fresh:
            logger.info("filing alert %s %s — %s", symbol, row.form, row.note)
            for handler in self._handlers:
                await handler(symbol, row)
