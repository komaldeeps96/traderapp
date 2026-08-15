"""Builds live bars out of individual trade prints.

Both providers reduce to the same shape — a stream of (time, price, size)
trades — so one builder serves IBKR tick-by-tick and Alpaca trade streams
alike, and its rollover behaviour is tested once.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.bars import Bar
from ..domain.timeframes import Timeframe
from .resample import bucket_start


@dataclass(slots=True)
class Trade:
    time: float
    price: float
    size: float
    # Late, average-price and similar prints carry real volume but must not
    # move open/high/low/close — see market/conditions.py.
    price_forming: bool = True


class BarBuilder:
    """Accumulates trades into the in-progress bar for one timeframe."""

    def __init__(self, timeframe: Timeframe):
        self._timeframe = timeframe
        self._current: Bar | None = None
        # Volume-only prints for a period no price-forming trade has opened
        # yet. Held rather than dropped — see add_trade.
        self._pending_period: int | None = None
        self._pending_volume: float = 0.0
        self._pending_trades: int = 0

    @property
    def current(self) -> Bar | None:
        return self._current

    def reset(self) -> None:
        self._current = None
        self._forget_pending()

    def _forget_pending(self) -> None:
        self._pending_period = None
        self._pending_volume = 0.0
        self._pending_trades = 0

    def add_trade(self, trade: Trade) -> Bar | None:
        """Fold a trade in. Returns the previous bar when a period rolls over.

        Trades that arrive for an already-closed period are dropped rather
        than reopening it — out-of-order prints would otherwise resurrect a
        bar the client has already been told is final.

        A non-price-forming print (late report, average-price block, odd
        lot) adds volume to its period's bar but never touches OHLC, and
        never opens a bar of its own — a bar whose open is not a market
        price would poison every indicator built on it.

        When such a print lands before its period has been opened it is held
        rather than dropped, and folded in once a real trade opens the bar.
        Odd lots are the reason: they are the great majority of prints on a
        small-cap gapper, so a minute frequently *begins* with one, and
        discarding those cost ~4% of volume against the published bar.
        """
        if trade.price <= 0 or trade.size < 0:
            return None

        period = bucket_start(trade.time, self._timeframe)
        current = self._current

        if not trade.price_forming:
            if current is not None and period == current.time:
                current.volume += trade.size
                current.trades += 1
            elif current is None or period > current.time:
                # A period we have not opened yet. Later periods supersede
                # any earlier pending one — a period that never saw a real
                # trade has no bar to carry its volume.
                if period != self._pending_period:
                    self._pending_period = period
                    self._pending_volume = 0.0
                    self._pending_trades = 0
                self._pending_volume += trade.size
                self._pending_trades += 1
            return None

        if current is None:
            self._current = self._open(period, trade)
            return None

        if period == current.time:
            current.high = max(current.high, trade.price)
            current.low = min(current.low, trade.price)
            current.close = trade.price
            current.volume += trade.size
            current.trades += 1
            return None

        if period < current.time:
            return None

        completed = current
        self._current = self._open(period, trade)
        return completed

    def adopt(self, bar: Bar) -> None:
        """Seed the in-progress period from an authoritative provider bar.

        Provider minute bars carry consolidated volume that a trade stream
        alone can understate, so when one lands for the period we are building
        it replaces our running totals instead of adding to them.
        """
        period = bucket_start(bar.time, self._timeframe)
        self._forget_pending()
        self._current = Bar(
            time=period,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            trades=bar.trades,
        )

    def _open(self, period: int, trade: Trade) -> Bar:
        volume, trades = trade.size, 1
        if self._pending_period == period:
            volume += self._pending_volume
            trades += self._pending_trades
        self._forget_pending()
        return Bar(
            time=period,
            open=trade.price,
            high=trade.price,
            low=trade.price,
            close=trade.price,
            volume=volume,
            trades=trades,
        )


def build_bars(trades: list[Trade], timeframe: Timeframe) -> list[Bar]:
    """Aggregate a batch of trades into completed bars.

    Used to rebuild 10-second history from a raw trade tape. Input is sorted
    here because the tape may arrive newest-first from a paginated fetch.
    """
    builder = BarBuilder(timeframe)
    bars: list[Bar] = []
    for trade in sorted(trades, key=lambda t: t.time):
        completed = builder.add_trade(trade)
        if completed is not None:
            bars.append(completed)
    if builder.current is not None:
        bars.append(builder.current)
    return bars
