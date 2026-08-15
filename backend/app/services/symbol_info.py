"""The numbers above the chart: float, rotation, relative volume, halt bands.

Everything here is derived from two sources — TradingView reference stats
(float, market cap, 10-day average volume) and our own bars (today's volume,
pre-market volume, previous close). Combining them is what produces the
fields that matter to the momentum workflow: float rotation is cumulative
volume over float; relative volume is today against the 10-day average.

LULD halt bands follow the exchange rule for Tier 2 stocks: the band
percentage is set by the *previous close* (10% above $3, 20% from $0.75–$3,
15 cents below that) and the reference price is a rolling five-minute mean.
Distance to the halt band is a first-class read on a runner — a break that
can only travel seven cents before halting is not a trade.
"""

from __future__ import annotations

from ..core.clock import now_epoch
from ..domain.bars import Bar
from ..domain.sessions import Session, ny_date, session_of
from ..domain.timeframes import Timeframe
from ..market.store import BarStore
from .tv import TVDataService

FIVE_MINUTES = 300


def _tier2_band_percent(prev_close: float) -> float | None:
    """Band width as a fraction, or ``None`` for the fixed 15-cent band."""
    if prev_close > 3.0:
        return 0.10
    if prev_close >= 0.75:
        return 0.20
    return None


class SymbolInfoService:
    def __init__(self, store: BarStore, tv: TVDataService):
        self._store = store
        self._tv = tv

    async def prefetch(self, symbol: str) -> None:
        """Warm the TradingView stats cache; called at subscribe time."""
        await self._tv.get_stats(symbol)

    def build(self, symbol: str) -> dict | None:
        """The ``info`` message payload, or ``None`` with nothing to say."""
        minute_bars = self._store.get(symbol, Timeframe.M1)
        daily_bars = self._store.get(symbol, Timeframe.D1)
        stats = self._tv.peek_stats(symbol)

        if not minute_bars and stats is None:
            return None

        day_volume, pm_volume, last_price = self._session_volumes(minute_bars)
        prev_close = self._previous_close(daily_bars)

        float_shares = stats.float_shares if stats else None
        avg_vol_10d = stats.avg_vol_10d if stats else None

        payload: dict = {
            "type": "info",
            "symbol": symbol,
            "float_shares": float_shares,
            "market_cap": stats.market_cap if stats else None,
            "shares_outstanding": stats.shares_outstanding if stats else None,
            "avg_vol_10d": avg_vol_10d,
            "description": stats.description if stats else "",
            "exchange": stats.exchange if stats else "",
            "sector": stats.sector if stats else "",
            "day_volume": day_volume,
            "pm_volume": pm_volume,
            "prev_close": prev_close,
            "rel_vol": (day_volume / avg_vol_10d) if day_volume and avg_vol_10d else None,
            "float_rotation": (day_volume / float_shares) if day_volume and float_shares else None,
            "pm_float_rotation": (pm_volume / float_shares) if pm_volume and float_shares else None,
            "generated_at": int(now_epoch()),
        }
        payload.update(self._halt_bands(minute_bars, prev_close, last_price))
        return payload

    @staticmethod
    def _session_volumes(minute_bars: list[Bar]) -> tuple[float, float, float | None]:
        """Today's cumulative volume, its pre-market share, and last price."""
        if not minute_bars:
            return 0.0, 0.0, None
        today = ny_date(minute_bars[-1].time)
        day_volume = 0.0
        pm_volume = 0.0
        for bar in reversed(minute_bars):
            if ny_date(bar.time) != today:
                break
            day_volume += bar.volume
            if session_of(bar.time) is Session.PREMARKET:
                pm_volume += bar.volume
        return day_volume, pm_volume, minute_bars[-1].close

    @staticmethod
    def _previous_close(daily_bars: list[Bar]) -> float | None:
        """The last daily close before today — the gap reference."""
        if not daily_bars:
            return None
        today = ny_date(now_epoch())
        for bar in reversed(daily_bars):
            if ny_date(bar.time) < today:
                return bar.close
        return None

    def _halt_bands(
        self,
        minute_bars: list[Bar],
        prev_close: float | None,
        last_price: float | None,
    ) -> dict:
        """LULD band levels around the five-minute mean reference price."""
        empty = {"halt_ref": None, "halt_up": None, "halt_down": None, "halt_active": False}
        if prev_close is None or last_price is None or not minute_bars:
            return empty

        active = session_of(now_epoch()) is Session.REGULAR

        cutoff = minute_bars[-1].time - FIVE_MINUTES
        window = [bar.close for bar in minute_bars[-6:] if bar.time > cutoff]
        reference = sum(window) / len(window) if window else last_price

        percent = _tier2_band_percent(prev_close)
        if percent is None:
            up, down = reference + 0.15, max(reference - 0.15, 0.0)
        else:
            up, down = reference * (1 + percent), reference * (1 - percent)

        return {
            "halt_ref": round(reference, 4),
            "halt_up": round(up, 4),
            "halt_down": round(down, 4),
            "halt_active": active,
        }
