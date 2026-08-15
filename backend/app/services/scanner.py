"""The market scanner.

Scanning is an IBKR feature with no Alpaca equivalent, so unlike charting it
cannot fail over. When TWS is absent the service stays idle and reports why,
and the UI shows that instead of an empty table with no explanation.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ..core.settings import ScannerSettings
from ..domain.scanner import VALID_SCAN_CODES, ScannerConfig, ScannerRow, ScannerState
from ..providers.ibkr import IBKRProvider
from .rank_velocity import RankTracker

logger = logging.getLogger(__name__)

UpdateHandler = Callable[[ScannerState], Awaitable[None]]

UNAVAILABLE_NOTE = "Market scanner requires a running IBKR TWS or Gateway connection."


class ScannerService:
    def __init__(self, ibkr: IBKRProvider, settings: ScannerSettings, tv=None):
        self._ibkr = ibkr
        self._settings = settings
        # TradingView is the only source for float and market cap. Optional so
        # the service still runs bare in tests.
        self._tv = tv
        self._stats_pending: set[str] = set()
        # Strong references to the in-flight reference-stat warms. The event
        # loop keeps only a weak one, so a task nobody holds can be collected
        # mid-await and vanish without running its `finally`.
        self._warming: set[asyncio.Task] = set()
        self._handlers: list[UpdateHandler] = []
        self._state = ScannerState(
            config=ScannerConfig(
                scan_code=settings.scan_code,
                above_price=settings.above_price,
                below_price=settings.below_price,
                above_volume=settings.above_volume,
                market_cap_above=settings.market_cap_above,
                market_cap_below=settings.market_cap_below,
                change_perc_above=settings.change_perc_above,
                number_of_rows=settings.number_of_rows,
            )
        )
        self._ranks = RankTracker(settings.rank_window_seconds)
        ibkr.on_scanner(self._on_rows)

    def on_update(self, handler: UpdateHandler) -> None:
        self._handlers.append(handler)

    @property
    def state(self) -> ScannerState:
        return self._state

    @property
    def available(self) -> bool:
        return self._ibkr.is_available

    def note(self) -> str | None:
        return None if self.available else UNAVAILABLE_NOTE

    async def start(self) -> bool:
        if not self._settings.enabled:
            return False
        if not self.available:
            self._state.running = False
            return False

        started = await self._ibkr.start_scanner(self._state.config)
        self._state.running = started
        return started

    async def stop(self) -> None:
        await self._ibkr.stop_scanner()
        for task in list(self._warming):
            task.cancel()
        self._warming.clear()
        self._stats_pending.clear()
        self._ranks.reset()
        self._state.running = False
        self._state.rows = []
        await self._notify()

    async def configure(self, **overrides: object) -> tuple[bool, str | None]:  # noqa: PLR0911
        """Apply new filters and restart the scan.

        Returns ``(ok, message)``; ``message`` explains any refusal so the
        client can surface it.
        """
        candidate = self._state.config.merged(**overrides)

        if candidate.scan_code not in VALID_SCAN_CODES:
            return False, f"Unknown scan code {candidate.scan_code!r}."
        if (
            candidate.above_price is not None
            and candidate.below_price is not None
            and candidate.below_price < candidate.above_price
        ):
            return False, "Maximum price must not be below the minimum price."
        if (
            candidate.market_cap_above is not None
            and candidate.market_cap_below is not None
            and candidate.market_cap_below < candidate.market_cap_above
        ):
            return False, "Maximum market cap must not be below the minimum."

        unchanged = candidate == self._state.config
        previous = self._state.config
        self._state.config = candidate

        if not self.available:
            self._state.running = False
            await self._notify()
            return False, UNAVAILABLE_NOTE

        if unchanged and self._state.running:
            logger.info("scanner configure: no change, keeping the running scan")
            return True, None

        logger.info(
            "scanner configure: %s -> %s; restarting scan",
            previous.to_dict(),
            candidate.to_dict(),
        )
        started = await self._ibkr.start_scanner(candidate)
        self._state.running = started
        if not started:
            await self._notify()
            return False, "IBKR refused the scanner subscription."

        # The old rows answered the old filters; showing them under the new
        # ones reads as "nothing changed". An empty table with the waiting
        # note is the honest state until the first results land. The rank
        # history goes with them — a position under the old scan compared
        # against one under the new scan is a jump that never happened.
        self._ranks.reset()
        self._state.rows = []
        await self._notify()
        return True, None

    async def refresh_availability(self) -> None:
        """Re-evaluate after the IBKR connection comes or goes."""
        if self.available and self._settings.enabled and not self._state.running:
            await self.start()
        elif not self.available and self._state.running:
            self._ranks.reset()
            self._state.running = False
            self._state.rows = []
            await self._notify()

    async def _on_rows(self, rows: list[ScannerRow]) -> None:
        self._state.rows = self._rank(rows)
        self._state.running = True
        await self._notify()

    def _rank(self, rows: list[ScannerRow]) -> list[ScannerRow]:
        """Order by trade rate, then measure the movement of that order.

        Ordering is plain prints-per-minute — the busiest tape first. Weighting
        it by momentum was tried and dropped: it reshuffled the list
        continuously and made positions hard to hold in the eye.

        Rank velocity is measured last, against the order actually emitted —
        anything else would describe a list nobody sees.
        """
        self._stamp_reference(rows)

        # Dollar volume breaks ties: at equal print rates the name moving
        # real money is the one worth the row. Trade counts from our own
        # print buffer are deliberately not used — they are unreliable in
        # both directions; see the note above the matching sort in
        # `IBKRProvider._process_scanner`.
        rows.sort(key=lambda row: (row.trades_1m, row.dollar_vol_1m), reverse=True)

        velocity = self._ranks.observe([row.symbol for row in rows])
        for row in rows:
            row.rank_delta = velocity.deltas.get(row.symbol)
            row.entered = row.symbol in velocity.entered
        return rows

    def _stamp_reference(self, rows: list[ScannerRow]) -> None:
        """Fill float and market cap from TradingView's cache.

        Read-only and non-blocking: rows emit every few seconds and must not
        wait on an HTTP round trip. A symbol missing from the cache is warmed
        in the background and arrives on a later emission — one fetch per new
        scanner member, then free until its TTL expires.
        """
        if self._tv is None:
            return
        for row in rows:
            stats = self._tv.peek_stats(row.symbol)
            if stats is not None:
                row.float_shares = stats.float_shares
                row.market_cap = stats.market_cap
            elif row.symbol not in self._stats_pending:
                self._stats_pending.add(row.symbol)
                task = asyncio.create_task(self._warm(row.symbol))
                self._warming.add(task)
                task.add_done_callback(self._warming.discard)

    async def _warm(self, symbol: str) -> None:
        try:
            await self._tv.get_stats(symbol)
        except Exception:
            logger.debug("scanner reference stats failed for %s", symbol, exc_info=True)
        finally:
            self._stats_pending.discard(symbol)

    async def _notify(self) -> None:
        for handler in self._handlers:
            try:
                await handler(self._state)
            except Exception:
                logger.exception("scanner update handler failed")
