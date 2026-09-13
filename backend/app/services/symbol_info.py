"""The numbers above the chart: float, rotation, relative volume, halt bands.

Derived from TradingView reference stats (float, market cap, 10-day average
volume) and our own bars (today's volume, pre-market volume, previous close).
Float rotation is cumulative volume over float; relative volume is today
against the 10-day average.

LULD halt bands follow the exchange rule for Tier 2 stocks: the percentage is
set by the *previous close* (10% above $3, 20% from $0.75–$3, 15 cents below)
and the reference price is a rolling five-minute mean.

The band *width* ships alongside the levels: it is a property of the name for
the whole session, fixed by the previous close, not of the moment.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta

from ..core.clock import now_epoch, to_ny
from ..domain.bars import Bar
from ..domain.dilution import SHELF_LOOKBACK_DAYS, DilutionRead, ShelfCapacity, shelf_capacity
from ..domain.dilution import measure as measure_dilution
from ..domain.sessions import Session, ny_date, session_of
from ..domain.timeframes import Timeframe
from ..market.store import BarStore
from ..providers.edgar import EdgarProvider
from ..providers.yahoo import YahooFloatProvider
from .corporate_actions import ReverseSplitService
from .halts import HaltState
from .pullback import measure as measure_pullback
from .tv import TVDataService

logger = logging.getLogger(__name__)

FIVE_MINUTES = 300

# LULD Appendix A, Tier 2, as amended in 2020 (Amendment 18). Below $0.75 the
# band is the lesser of 15 cents and 75%, so under $0.20 the percentage binds.
# Nothing doubles at the open; at or below $3.00 the band doubles from 15:35 to
# the close.
SUB_DOLLAR_BAND = 0.15
SUB_DOLLAR_PERCENT = 0.75
CLOSING_DOUBLE_FROM = 15 * 3600 + 35 * 60
CLOSE = 16 * 3600

CALM = HaltState(halted=False, count=0, halted_at=None, resumed_at=None)


# Listing ages beyond this are not reported: the daily window is years deep,
# so only a young history is evidence of a young listing. Generous next to
# the frontend's flag threshold, so the display decides, not the fetch.
RECENT_LISTING_DAYS = 400

BorrowLookup = Callable[[str], tuple[float | None, float | None] | None]
HaltLookup = Callable[[str], HaltState]


def _tier2_band_percent(prev_close: float) -> float | None:
    """Band width as a fraction, or ``None`` below $0.75, where it is the lesser
    of 15 cents and 75% of the reference."""
    if prev_close > 3.0:
        return 0.10
    if prev_close >= 0.75:
        return 0.20
    return None


def _closing_doubled(prev_close: float, moment: float) -> bool:
    """Whether ``moment`` is in the closing window where a <= $3 band doubles."""
    if prev_close > 3.0:
        return False
    local = to_ny(moment)
    return CLOSING_DOUBLE_FROM <= local.hour * 3600 + local.minute * 60 < CLOSE


class SymbolInfoService:
    def __init__(
        self,
        store: BarStore,
        tv: TVDataService,
        borrow: BorrowLookup | None = None,
        halts: HaltLookup | None = None,
        splits: ReverseSplitService | None = None,
        yahoo: YahooFloatProvider | None = None,
        edgar: EdgarProvider | None = None,
    ):
        self._store = store
        self._tv = tv
        # (tier, shortable shares) for a streamed symbol — IBKR generic tick
        # 236, threaded in as a callable so this service stays provider-blind.
        self._borrow = borrow
        # The HaltTracker's per-symbol state: halted now, halts today, and
        # the transition times the reopen read is measured against.
        self._halts = halts
        self._splits = splits
        self._yahoo = yahoo
        self._edgar = edgar
        # symbol -> (facts, filings, read). The documents themselves are held,
        # not their id(): a freed payload's id can be reused by its replacement.
        self._dilution_cache: dict[str, tuple[object, object, DilutionRead | None]] = {}

    async def prefetch(self, symbol: str) -> None:
        """Warm every reference cache; called at subscribe time.

        Failures stay independent: one source being down must not cost the
        fields another would have answered with.
        """
        for warm in (self._warm_tv, self._warm_splits, self._warm_yahoo, self._warm_edgar):
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

    async def _warm_edgar(self, symbol: str) -> None:
        if self._edgar is not None:
            await self._edgar.prefetch(symbol)

    @staticmethod
    def _lookback_high(
        daily_bars: list[Bar], today_bars: list[Bar], today: date
    ) -> float | None:
        """The highest price of the last ``SHELF_LOOKBACK_DAYS`` calendar days.

        Both bases, because neither is enough: the daily store is strictly
        historical and would leave out the run that moves the number, and the
        minute base reaches back days rather than months.
        """
        floor = today - timedelta(days=SHELF_LOOKBACK_DAYS)
        highs = [bar.high for bar in daily_bars if ny_date(bar.time) >= floor]
        highs.extend(bar.high for bar in today_bars)
        return max(highs) if highs else None

    def _live_shelf(self, symbol: str, read: DilutionRead | None) -> ShelfCapacity | None:
        """Baby-shelf capacity at the price the rule would actually use.

        The float *share count* comes from TradingView, not the XBRL cover
        figure, which is a dollar amount priced months ago. Reported float is
        passed through only for contrast.
        """
        stats = self._tv.peek_stats(symbol)
        if stats is None or read is None:
            return None
        daily_bars = self._store.get(symbol, Timeframe.D1)
        _, _, _, today_bars = self._session_volumes(self._store.get(symbol, Timeframe.M1))
        high = self._lookback_high(daily_bars, today_bars, ny_date(now_epoch()))
        return shelf_capacity(
            stats.float_shares,
            high,
            read.public_float.value if read.public_float else None,
        )

    def dilution(self, symbol: str) -> DilutionRead | None:
        """The dilution read from the warmed EDGAR caches, without I/O.

        Memoised against the identity of the cached EDGAR documents rather than
        a clock: ``build`` runs on every broadcast tick and the read changes
        only when the provider swaps the whole payload on refresh.
        """
        if self._edgar is None:
            return None
        facts = self._edgar.peek_facts(symbol)
        filings = self._edgar.peek_filings(symbol)
        cached = self._dilution_cache.get(symbol)
        if cached is not None and cached[0] is facts and cached[1] is filings:
            read = cached[2]
        else:
            read = measure_dilution(facts, filings)
            self._dilution_cache[symbol] = (facts, filings, read)
        # Attached outside the memo: the shelf capacity is priced off the
        # tape, and caching it against the filings would freeze it at
        # whatever the stock was worth when the documents last changed.
        return read.with_live_shelf(self._live_shelf(symbol, read)) if read else None

    def _dilution_summary(self, symbol: str) -> dict | None:
        """The compact block the info strip's chip needs.

        Only what the always-visible chip renders: the verdict, the two numbers
        behind it, and the warrant strike the frontend compares against the live
        price. The full read is a REST call away.
        """
        read = self.dilution(symbol)
        if read is None:
            return None
        return {
            "tone": read.tone.value,
            "warrant_overhang": read.warrant_overhang,
            "warrant_strike": read.warrant_strike.value if read.warrant_strike else None,
            "runway_months": read.runway_months,
            "reasons": list(read.reasons),
        }

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
            # Rides the same TradingView row as the float and market cap
            # above, so it costs nothing here — and a scheduled report is
            # the one calendar entry that changes what a position is worth
            # holding overnight.
            "earnings_next": stats.earnings_next if stats else None,
            "generated_at": int(now_epoch()),
        }
        borrow = self._borrow(symbol) if self._borrow is not None else None
        payload["shortable"] = borrow[0] if borrow else None
        payload["shortable_shares"] = borrow[1] if borrow else None

        halt = self._halts(symbol) if self._halts is not None else CALM
        payload["halted"] = halt.halted
        payload["halts_today"] = halt.count
        # Stamped on the server clock, like ``generated_at`` beside them, so
        # the elapsed time the frontend renders never crosses two clocks.
        payload["halt_halted_at"] = int(halt.halted_at) if halt.halted_at else None
        payload["halt_resumed_at"] = int(halt.resumed_at) if halt.resumed_at else None

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

        payload["dilution"] = self._dilution_summary(symbol)

        payload.update(self._halt_bands(minute_bars, prev_close, last_price))
        return payload

    @staticmethod
    def _listed_days(daily_bars: list[Bar]) -> int | None:
        """Age of the daily history — a listing age, within the fetch window.

        The daily fetch reaches back years, so a history starting weeks ago
        starts there because the symbol did. Only young readings are reported —
        near the window edge the number measures the fetch, not the listing.
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

        Today's bars come back in time order so the pullback measure can walk
        them directly, and the day boundary keeps a leg from straddling the
        overnight gap.
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
        empty = {
            "halt_ref": None,
            "halt_up": None,
            "halt_down": None,
            "halt_active": False,
            "halt_band_pct": None,
            "halt_band_cents": None,
        }
        if prev_close is None or last_price is None or not minute_bars:
            return empty

        active = session_of(now_epoch()) is Session.REGULAR

        cutoff = minute_bars[-1].time - FIVE_MINUTES
        window = [bar.close for bar in minute_bars[-6:] if bar.time > cutoff]
        reference = sum(window) / len(window) if window else last_price

        # Read off the market's clock, the last bar, rather than this machine's.
        factor = 2 if _closing_doubled(prev_close, minute_bars[-1].time) else 1
        percent = _tier2_band_percent(prev_close)
        if percent is None and SUB_DOLLAR_PERCENT * reference >= SUB_DOLLAR_BAND:
            width = SUB_DOLLAR_BAND * factor
            band_pct, band_cents = None, SUB_DOLLAR_BAND * 100 * factor
        else:
            fraction = (percent if percent is not None else SUB_DOLLAR_PERCENT) * factor
            width = reference * fraction
            band_pct, band_cents = fraction * 100, None

        return {
            "halt_ref": round(reference, 4),
            "halt_up": round(reference + width, 4),
            "halt_down": round(max(reference - width, 0.0), 4),
            "halt_active": active,
            # Exactly one of the two is set: the band is a percentage or a
            # fixed number of cents, never both.
            "halt_band_pct": band_pct,
            "halt_band_cents": band_cents,
        }
