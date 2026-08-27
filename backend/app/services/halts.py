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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from ..core.clock import now_epoch
from ..domain.sessions import ny_date

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _SymbolHalts:
    halted: bool = False
    count: int = 0
    day: date = field(default_factory=lambda: ny_date(now_epoch()))


class HaltTracker:
    def __init__(self) -> None:
        self._symbols: dict[str, _SymbolHalts] = {}

    def mark(self, symbol: str, halted: bool) -> None:
        """Record the current halt state; False→True transitions count."""
        state = self._entry(symbol)
        if halted and not state.halted:
            state.count += 1
            logger.info("halt #%d for %s", state.count, symbol)
        state.halted = halted

    def status(self, symbol: str) -> tuple[bool, int]:
        """(halted right now, halts so far today)."""
        state = self._entry(symbol)
        return state.halted, state.count

    def _entry(self, symbol: str) -> _SymbolHalts:
        state = self._symbols.get(symbol)
        today = ny_date(now_epoch())
        if state is None:
            state = self._symbols[symbol] = _SymbolHalts(day=today)
        elif state.day != today:
            # New session: the count starts over, but a halt that is still
            # standing from yesterday's close is still standing.
            state.count = 1 if state.halted else 0
            state.day = today
        return state
