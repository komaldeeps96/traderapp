"""How fast a name is climbing the scanner.

Rank *level* says what is busiest right now; rank *velocity* says what is
becoming busy, and it moves first. A name that jumps four or five places is
being discovered — the leaderboard reacts before the alert fires, so the
delta is a leading read on the same event.

Positions come from our own trade-rate ordering rather than IBKR's scan
rank. IBKR reranks roughly twice a minute and its rank disagrees with the
order we display, so a delta on it would describe a list nobody is looking
at.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .rolling import WindowedHistory


@dataclass(frozen=True, slots=True)
class RankVelocity:
    """Places gained since the baseline, and who was not there at all."""

    # symbol -> places gained. Positive means it moved *up* the list, which
    # is the direction a reader cares about, so the sign is flipped relative
    # to the raw index.
    deltas: dict[str, int]
    # Present now, absent a window ago. Entering the visible list at all is
    # itself the signal, so these are reported apart from a numeric delta.
    entered: frozenset[str]


class RankTracker:
    """Rolling positional history for one scanner ordering."""

    def __init__(
        self, window_seconds: float, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._history: WindowedHistory[dict[str, int]] = WindowedHistory(
            window_seconds, clock=clock
        )

    def reset(self) -> None:
        """Forget everything.

        Called when the filters change: positions under the old scan are not
        comparable with positions under the new one, and carrying them over
        would report a jump that never happened.
        """
        self._history.clear()

    def observe(self, symbols: Sequence[str]) -> RankVelocity:
        """Record the current order and measure it against a window ago."""
        positions = {symbol: index for index, symbol in enumerate(symbols)}
        baseline = self._history.push(positions)

        if baseline is None:
            # Still filling the window. No baseline means no claim.
            return RankVelocity(deltas={}, entered=frozenset())

        deltas: dict[str, int] = {}
        entered: set[str] = set()
        for symbol, position in positions.items():
            previous = baseline.get(symbol)
            if previous is None:
                entered.add(symbol)
            elif previous != position:
                deltas[symbol] = previous - position
        return RankVelocity(deltas=deltas, entered=frozenset(entered))
