"""One TWS market-data line per symbol, shared by everything that wants one.

ib_async keeps one Ticker per contract and maps it to the *latest* ``reqMktData``
request id (``wrapper.startTicker``), so a second request on a contract orphans
the first: ``cancelMktData`` then cancels only the second, and the first line
leaks against TWS's ~100-line cap. So each symbol gets one request carrying
every owner's generic ticks, re-issued when that set grows, and one listener.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

TickHandler = Callable[[str, object], None]


@dataclass
class _Line:
    contract: object
    ticker: object
    ticks: frozenset[str]
    listener: Callable
    owners: dict[str, tuple[frozenset[str], TickHandler]] = field(default_factory=dict)


class MarketLines:
    def __init__(self, ib: Callable[[], object]) -> None:
        # A getter: the provider builds its IB object only once it starts.
        self._ib = ib
        self._lines: dict[str, _Line] = {}

    def ticker(self, symbol: str):
        line = self._lines.get(symbol)
        return line.ticker if line else None

    def owners(self, symbol: str) -> set[str]:
        line = self._lines.get(symbol)
        return set(line.owners) if line else set()

    def acquire(
        self,
        symbol: str,
        contract,
        owner: str,
        ticks: frozenset[str],
        handler: TickHandler,
    ):
        """Hold ``symbol``'s line for ``owner``; returns its ticker, or None."""
        line = self._lines.get(symbol)
        if line is None:
            ticker = self._request(contract, ticks)
            if ticker is None:
                return None
            listener = functools.partial(self._dispatch, symbol)
            ticker.updateEvent += listener
            line = _Line(contract, ticker, ticks, listener)
            self._lines[symbol] = line
        line.owners[owner] = (ticks, handler)
        wanted = frozenset().union(*(owned for owned, _ in line.owners.values()))
        if not wanted <= line.ticks:
            self._reissue(line, wanted)
        return line.ticker

    def release(self, symbol: str, owner: str) -> None:
        """Let go of ``symbol`` for ``owner``; the last owner cancels the line.

        A line is not narrowed when a wider owner leaves: that would cost a
        re-request for ticks nobody reads.
        """
        line = self._lines.get(symbol)
        if line is None or line.owners.pop(owner, None) is None or line.owners:
            return
        del self._lines[symbol]
        line.ticker.updateEvent -= line.listener
        self._cancel(line.contract)

    def reset(self) -> None:
        """The connection went. TWS dropped every line with it and ib_async its
        tickers, so there is nothing left to cancel or detach."""
        self._lines.clear()

    def _dispatch(self, symbol: str, ticker) -> None:
        line = self._lines.get(symbol)
        if line is None:
            return
        # Tiers sharing one handler hear each update once, not once per tier.
        for handler in {handler for _, handler in line.owners.values()}:
            handler(symbol, ticker)

    def _request(self, contract, ticks: frozenset[str]):
        try:
            return self._ib().reqMktData(
                contract, genericTickList=",".join(sorted(ticks)), snapshot=False
            )
        except Exception as exc:
            logger.warning("IBKR market data failed for %s: %s", contract.symbol, exc)
            return None

    def _cancel(self, contract) -> None:
        try:
            self._ib().cancelMktData(contract)
        except Exception as exc:
            logger.warning("IBKR could not cancel market data for %s: %s", contract.symbol, exc)

    def _reissue(self, line: _Line, ticks: frozenset[str]) -> None:
        # Cancelled first: a second request alongside would orphan the first.
        self._cancel(line.contract)
        ticker = self._request(line.contract, ticks)
        if ticker is None:
            return
        if ticker is not line.ticker:
            line.ticker.updateEvent -= line.listener
            ticker.updateEvent += line.listener
            line.ticker = ticker
        line.ticks = ticks
