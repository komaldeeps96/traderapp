"""Pushes chart updates on a fixed cadence.

Trades and quotes arrive far faster than a chart can usefully redraw, so
updates are coalesced: the loop wakes on an interval and sends at most one
message per watched chart — and one quote per watched symbol — and only when
that data actually changed since the last send.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from ..domain.protocol import api_usage_message, quote_message, tape_message
from ..domain.timeframes import Timeframe
from .api_budget import ApiBudget
from .hub import SubscriptionHub
from .market_data import MarketDataService
from .quotes import QuoteService
from .symbol_info import SymbolInfoService
from .tape import TapeService

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 1.0

# Most prints one tick may carry per symbol. A halt resuming can put several
# hundred on the tape in a second; past this the oldest are dropped rather
# than queued, because a tape is read from the top and the newest rows are
# the ones the reader is looking at. The client's own list is bounded too.
MAX_PRINTS_PER_TICK = 250


class ChartBroadcaster:
    def __init__(
        self,
        hub: SubscriptionHub,
        market_data: MarketDataService,
        quotes: QuoteService | None = None,
        symbol_info: SymbolInfoService | None = None,
        api_budget: ApiBudget | None = None,
        tape: TapeService | None = None,
        interval: float = DEFAULT_INTERVAL,
    ):
        self._hub = hub
        self._market = market_data
        self._quotes = quotes
        self._info = symbol_info
        self._api_budget = api_budget
        self._tape = tape
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._sent: dict[tuple[str, Timeframe], int] = {}
        self._sent_quotes: dict[str, int] = {}
        self._sent_info: dict[str, int] = {}
        self._sent_tape: dict[str, int] = {}
        self._sent_api: dict | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("broadcast tick failed")

    def tick(self) -> int:
        """Send one round of updates. Returns how many charts were pushed.

        Exposed separately from the loop so tests can drive it deterministically
        instead of waiting on wall-clock time.
        """
        pairs = self._hub.pairs()
        sent = 0

        for symbol, timeframe in pairs:
            revision = self._market.revision(symbol)
            key = (symbol, timeframe)
            if self._sent.get(key) == revision:
                continue

            message = self._market.build_update(symbol, timeframe)
            if message is None:
                continue
            self._hub.send_to_pair(symbol, timeframe, message)
            self._sent[key] = revision
            sent += 1

        symbols = {symbol for symbol, _ in pairs}
        sent += self._tick_quotes(symbols)
        sent += self._tick_tape(symbols)
        sent += self._tick_info(symbols)
        sent += self._tick_api()

        for key in [k for k in self._sent if k not in pairs]:
            self._sent.pop(key, None)
        return sent

    def _tick_api(self) -> int:
        """Budget meters: sent whenever the window contents change.

        The counts move both when a request lands and when one ages out of
        the window, so this compares the whole snapshot rather than keying
        on a revision.
        """
        if self._api_budget is None:
            return 0
        snapshot = self._api_budget.snapshot()
        if snapshot == self._sent_api:
            return 0
        self._sent_api = snapshot
        self._hub.broadcast(api_usage_message(snapshot))
        return 1

    def _tick_quotes(self, symbols: set[str]) -> int:
        if self._quotes is None:
            return 0
        sent = 0
        for symbol in symbols:
            revision = self._quotes.revision(symbol)
            if revision == 0 or self._sent_quotes.get(symbol) == revision:
                continue
            quote = self._quotes.get(symbol)
            if quote is None:
                continue
            self._hub.send_to_symbol(symbol, quote_message(symbol, quote))
            self._sent_quotes[symbol] = revision
            sent += 1

        for symbol in [s for s in self._sent_quotes if s not in symbols]:
            self._sent_quotes.pop(symbol, None)
        return sent

    def _tick_tape(self, symbols: set[str]) -> int:
        """Prints that landed since the last tick, per symbol.

        The cursor is per symbol and shared by every client on it, so a client
        that subscribed between two ticks is sent rows it already has in its
        opening backlog. That overlap is the cheap half of the trade: the
        client drops anything at or below the sequence it holds, and the
        alternative is a cursor per connection.
        """
        if self._tape is None:
            return 0
        sent = 0
        for symbol in symbols:
            revision = self._tape.revision(symbol)
            cursor = self._sent_tape.get(symbol, 0)
            if revision in (0, cursor):
                continue
            # A sequence that went backwards means the service evicted this
            # symbol's buffer and started it again. Nothing after the gap
            # joins onto what the client holds, so the batch is a replacement
            # rather than an extension.
            restarted = revision < cursor
            prints = self._tape.recent(symbol) if restarted else self._tape.since(symbol, cursor)
            self._sent_tape[symbol] = revision
            if not prints:
                continue
            self._hub.send_to_symbol(
                symbol,
                tape_message(symbol, prints[-MAX_PRINTS_PER_TICK:], reset=restarted),
            )
            sent += 1

        for symbol in [s for s in self._sent_tape if s not in symbols]:
            self._sent_tape.pop(symbol, None)
        return sent

    def _tick_info(self, symbols: set[str]) -> int:
        """Top-panel numbers: keyed to the same revision as the bars.

        Volume-derived fields only change when a trade lands, so the market
        revision is exactly the right change detector.
        """
        if self._info is None:
            return 0
        sent = 0
        for symbol in symbols:
            # Wait for history: an info strip with a zero day-volume flashing
            # before the load lands reads as data, and wrong data at that.
            if not self._market.is_loaded(symbol):
                continue
            revision = self._market.revision(symbol)
            if self._sent_info.get(symbol) == revision:
                continue
            message = self._info.build(symbol)
            if message is None:
                continue
            self._hub.send_to_symbol(symbol, message)
            self._sent_info[symbol] = revision
            sent += 1

        for symbol in [s for s in self._sent_info if s not in symbols]:
            self._sent_info.pop(symbol, None)
        return sent
