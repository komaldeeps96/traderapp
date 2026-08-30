"""Trading-halt state, fed by whichever provider notices first.

Two sources report halts and neither is complete on its own. Alpaca's
``statuses`` stream pushes halt and resume events with LULD reason codes,
but only while the websocket is up. IBKR's quote line carries a ``halted``
magnitude on every update, but only for the focused symbol and without a
reason. Both feed the same per-symbol state machine here, which makes the
double-report harmless: a transition is counted once no matter how many sources
report it.

The count answers the question the chart cannot — "how many times has this
thing halted today" — which is the difference between a runner and a
circuit-breaker yo-yo. It resets lazily at the New York date boundary, so
a terminal left open overnight starts the new session at zero.

The transition *times* are kept for a different reason. The reopen is the one
condition in this whole strategy with a large measured effect behind it, and
measuring it needs to know how long ago the tape came back — not merely that
it did. Nothing here judges the reopen; it only records when it happened.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from ..core.clock import now_epoch
from ..domain.sessions import ny_date

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HaltState:
    """What the tracker knows about one symbol, right now."""

    halted: bool
    """Trading is stopped at this instant."""
    count: int
    """Halts so far today, counted on the False→True edge."""
    halted_at: float | None
    """When the current or most recent halt began."""
    resumed_at: float | None
    """When the most recent halt ended; ``None`` until one does."""


@dataclass(slots=True)
class _SymbolHalts:
    halted: bool = False
    count: int = 0
    halted_at: float | None = None
    resumed_at: float | None = None
    day: date = field(default_factory=lambda: ny_date(now_epoch()))


class HaltTracker:
    def __init__(self) -> None:
        self._symbols: dict[str, _SymbolHalts] = {}

    def mark(self, symbol: str, halted: bool) -> None:
        """Record the current halt state; False→True transitions count."""
        state = self._entry(symbol)
        if halted == state.halted:
            return
        now = now_epoch()
        if halted:
            state.count += 1
            state.halted_at = now
            logger.info("halt #%d for %s", state.count, symbol)
        else:
            state.resumed_at = now
            logger.info("%s resumed", symbol)
        state.halted = halted

    def status(self, symbol: str) -> HaltState:
        state = self._entry(symbol)
        return HaltState(
            halted=state.halted,
            count=state.count,
            halted_at=state.halted_at,
            resumed_at=state.resumed_at,
        )

    def _entry(self, symbol: str) -> _SymbolHalts:
        state = self._symbols.get(symbol)
        today = ny_date(now_epoch())
        if state is None:
            state = self._symbols[symbol] = _SymbolHalts(day=today)
        elif state.day != today:
            # New session: the count starts over, but a halt that is still
            # standing from yesterday's close is still standing. Yesterday's
            # resume is not this morning's, so the clock behind the reopen
            # read is cleared with the count.
            state.count = 1 if state.halted else 0
            state.resumed_at = None
            if not state.halted:
                state.halted_at = None
            state.day = today
        return state
