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

import logging
from collections.abc import Callable

from ..core.clock import now_epoch
from ..domain.bars import Bar
from ..domain.sessions import Session, ny_date, session_of
from ..domain.timeframes import Timeframe
from ..market.store import BarStore
from ..providers.yahoo import YahooFloatProvider
from .corporate_actions import ReverseSplitService
from .pullback import measure as measure_pullback
from .tv import TVDataService

logger = logging.getLogger(__name__)

FIVE_MINUTES = 300


# Listing ages beyond this are not reported: the daily window is years deep,
# so only a young history is evidence of a young listing. Generous next to
# the frontend's flag threshold, so the display decides, not the fetch.
RECENT_LISTING_DAYS = 400

BorrowLookup = Callable[[str], tuple[float | None, float | None] | None]
HaltLookup = Callable[[str], tuple[bool, int]]


def _tier2_band_percent(prev_close: float) -> float | None:
    """Band width as a fraction, or ``None`` for the fixed 15-cent band."""
    if prev_close > 3.0:
        return 0.10
    if prev_close >= 0.75:
        return 0.20
    return None


class SymbolInfoService:
    def __init__(
        self,
        store: BarStore,
        tv: TVDataService,
        borrow: BorrowLookup | None = None,
        halts: HaltLookup | None = None,
        splits: ReverseSplitService | None = None,
        yahoo: YahooFloatProvider | None = None,
    ):
        self._store = store
        self._tv = tv
        # (tier, shortable shares) for a streamed symbol — IBKR generic tick
        # 236, threaded in as a callable so this service stays provider-blind.
        self._borrow = borrow
        # (halted now, halts today) from the HaltTracker.
        self._halts = halts
        self._splits = splits
        self._yahoo = yahoo

    async def prefetch(self, symbol: str) -> None:
        """Warm every reference cache; called at subscribe time.

        Failures stay independent: a Yahoo outage must not cost the float
        and market cap that TradingView would have answered with.
        """
        for warm in (self._warm_tv, self._warm_splits, self._warm_yahoo):
            try:
                await warm(symbol)
            except Exception:
                logger.debug("reference prefetch failed", exc_info=True)

    async def _warm_tv(self, symbol: str) -> None:
        await self._tv.get_stats(symbol)

    async def _warm_splits(self, symbol: str) -> None:
        if self._splits is not None:
            await self._splits.prefetch(symbol)

    async def _warm_yahoo(self, symbol: str) -> None:
        if self._yahoo is not None:
            await self._yahoo.prefetch(symbol)

    def build(self, symbol: str) -> dict | None:
        """The ``info`` message payload, or ``None`` with nothing to say."""
        minute_bars = self._store.get(symbol, Timeframe.M1)
        daily_bars = self._store.get(symbol, Timeframe.D1)
        stats = self._tv.peek_stats(symbol)

        if not minute_bars and stats is None:
            return None

        day_volume, pm_volume, last_price, today_bars = self._session_volumes(minute_bars)
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
            "all_time_high": stats.all_time_high if stats else None,
            "description": stats.description if stats else "",
            "exchange": stats.exchange if stats else "",
            "sector": stats.sector if stats else "",
            "day_volume": day_volume,
            "pm_volume": pm_volume,
            "prev_close": prev_close,
            "rel_vol": (day_volume / avg_vol_10d) if day_volume and avg_vol_10d else None,
            "float_rotation": (day_volume / float_shares) if day_volume and float_shares else None,
            "pm_float_rotation": (pm_volume / float_shares) if pm_volume and float_shares else None,
            "listed_days": self._listed_days(daily_bars),
            "generated_at": int(now_epoch()),
        }
        borrow = self._borrow(symbol) if self._borrow is not None else None
        payload["shortable"] = borrow[0] if borrow else None
        payload["shortable_shares"] = borrow[1] if borrow else None

        halted, halts_today = self._halts(symbol) if self._halts is not None else (False, 0)
        payload["halted"] = halted
        payload["halts_today"] = halts_today

        split = self._splits.peek(symbol) if self._splits is not None else None
        payload["reverse_split_ratio"] = split.ratio if split else None
        payload["reverse_split_days"] = (
            (ny_date(now_epoch()) - split.ex_date).days if split else None
        )

        payload["yahoo_float"] = (
            self._yahoo.peek_float(symbol) if self._yahoo is not None else None
        )

        pullback = measure_pullback(today_bars)
        payload["pullback_depth_pct"] = pullback.depth_percent if pullback else None
        payload["pullback_vol_ratio"] = pullback.volume_ratio if pullback else None
        payload["pullback_bars"] = pullback.bars_since_high if pullback else None
        payload["pullback_leg_pct"] = pullback.leg_percent if pullback else None

        payload.update(self._halt_bands(minute_bars, prev_close, last_price))
        return payload

    @staticmethod
    def _listed_days(daily_bars: list[Bar]) -> int | None:
        """Age of the daily history — a listing age, within the fetch window.

        The daily fetch reaches back years; a history that starts weeks ago
        starts there because the symbol did. Only young readings are reported:
        near the window edge the number measures the fetch, not the listing,
        and a long-listed name would otherwise carry a large lie.
        """
        if not daily_bars:
            return None
        days = (ny_date(now_epoch()) - ny_date(daily_bars[0].time)).days
        return days if days <= RECENT_LISTING_DAYS else None

    @staticmethod
    def _session_volumes(
        minute_bars: list[Bar],
    ) -> tuple[float, float, float | None, list[Bar]]:
        """Today's volume, its pre-market share, last price, today's bars.

        Today's bars come back in time order so the pullback measure can
        walk them directly; the day boundary matters there too, because a
        leg must not straddle the overnight gap.
        """
        if not minute_bars:
            return 0.0, 0.0, None, []
        today = ny_date(minute_bars[-1].time)
        day_volume = 0.0
        pm_volume = 0.0
        today_bars: list[Bar] = []
        for bar in reversed(minute_bars):
            if ny_date(bar.time) != today:
                break
            today_bars.append(bar)
            day_volume += bar.volume
            if session_of(bar.time) is Session.PREMARKET:
                pm_volume += bar.volume
        today_bars.reverse()
        return day_volume, pm_volume, minute_bars[-1].close, today_bars

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
