"""Owns loaded market data and turns it into what the chart draws.

One copy of each symbol is held, shared by every subscriber. Derived
timeframes and indicator series are computed lazily and cached against a
per-symbol revision counter, so a burst of trades costs one recompute at the
next broadcast rather than one per trade or one per client.

Loading is two-phase. Phase one fetches only the daily bars and the *viewed*
timeframe's base — one IBKR request for the 10s default — and sends the
snapshot. Phase two backfills the remaining bases and the older 10s hours in
the background, then announces itself so subscribers extend the chart.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from ..core.clock import now_epoch
from ..domain.bars import Bar
from ..domain.protocol import BarUpdate, Snapshot, bar_message, snapshot_message
from ..domain.sessions import ny_date
from ..domain.timeframes import Timeframe
from ..indicators.engine import IndicatorEngine, SeriesMap
from ..indicators.functions import EMPTY_SESSION_LEVELS, SessionLevels, session_levels
from ..indicators.levels import DailyLevelIndex
from ..market.bar_builder import BarBuilder, Trade
from ..market.resample import bucket_start, derive, resample
from ..market.store import BarStore
from ..providers.router import TENSEC_RECENT_SECONDS, TENSEC_WINDOW_SECONDS, FeedRouter

logger = logging.getLogger(__name__)

BackfillHandler = Callable[[str], Awaitable[None]]

# A symbol nobody is watching keeps its bars warm for this long. Flipping
# between the same few runners is the workflow, and reloading the 10s window on
# every flip costs three IBKR requests, a capped Alpaca tape walk and a second
# of blank chart.
KEEP_WARM_SECONDS = 600.0
KEEP_WARM_MAX_SYMBOLS = 8
# A runner prints a few hundred times a second; a load that stalls on the
# request budget must not buffer without end.
EARLY_TRADE_LIMIT = 50_000
MINUTE_BUCKETS = Timeframe.M1.seconds // Timeframe.S10.seconds


class MarketDataService:
    def __init__(
        self,
        router: FeedRouter,
        store: BarStore,
        engine: IndicatorEngine,
    ):
        self._router = router
        self._store = store
        self._engine = engine

        self._loaded: set[str] = set()
        self._builders: dict[str, dict[Timeframe, BarBuilder]] = {}
        self._revisions: dict[str, int] = {}
        self._level_index: dict[str, DailyLevelIndex] = {}
        self._bars_cache: dict[tuple[str, Timeframe], tuple[int, list[Bar]]] = {}
        self._series_cache: dict[tuple[str, Timeframe], tuple[int, SeriesMap]] = {}
        self._loads: dict[str, asyncio.Task] = {}
        self._backfills: dict[str, asyncio.Task] = {}
        self._repairs: dict[str, asyncio.Task] = {}
        self._parked: dict[str, asyncio.Task] = {}
        self._backfill_handlers: list[BackfillHandler] = []
        # Prints that arrive while a symbol loads: the stream starts first.
        self._early_trades: dict[str, list[Trade]] = {}

    async def start(self) -> None:
        self._router.on_trade(self._handle_trade)
        self._router.on_bar(self._handle_bar)

    async def stop(self) -> None:
        """Cancel everything still in flight and wait for it to unwind.

        Loads, backfills, repairs and warm-cache timers are fire-and-forget, so
        shutdown has to collect them: otherwise they are still pending when the
        loop closes, and their ``finally`` blocks never run.
        """
        pending = [
            task
            for group in (self._loads, self._backfills, self._repairs, self._parked)
            for task in group.values()
            if not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for group in (self._loads, self._backfills, self._repairs, self._parked):
            group.clear()

    def on_backfill(self, handler: BackfillHandler) -> None:
        """Called with the symbol after its background history lands."""
        self._backfill_handlers.append(handler)

    # ── loading ────────────────────────────────────────────────────────

    async def ensure_loaded(self, symbol: str, focus: Timeframe = Timeframe.S10) -> bool:
        """Load enough of a symbol to draw ``focus``, once, shared by callers.

        Concurrent callers share the in-flight task and await it shielded, so
        one client disconnecting mid-load does not cancel it for the others. The
        first caller's focus decides the fast path.
        """
        if symbol in self._loaded:
            return True

        if self._unpark(symbol):
            return True

        task = self._loads.get(symbol)
        if task is None or task.done():
            task = asyncio.create_task(self._load(symbol, focus))
            self._loads[symbol] = task

        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Loading %s failed", symbol)
            return False

    def _unpark(self, symbol: str) -> bool:
        """Revive a kept-warm symbol: instant snapshot, one gap repair."""
        expiry = self._parked.pop(symbol, None)
        if expiry is None:
            return False
        expiry.cancel()
        if not self._store.has(symbol, Timeframe.D1) and not self._store.has(symbol, Timeframe.M1):
            return False
        self._loaded.add(symbol)
        self._bump(symbol)
        # The parked window ends where the last client left; one recent-slice
        # fetch closes the gap up to now, silently, after the instant paint.
        self.schedule_recent_repair(symbol)
        logger.info("Revived %s from the warm cache", symbol)
        return True

    async def _load(self, symbol: str, focus: Timeframe) -> bool:
        """Phase one: daily bars plus the focused base, nothing else."""
        base = focus.base
        if base is Timeframe.S10:
            base_task = self._router.fetch_recent_tensec(symbol)
        elif base is Timeframe.M1:
            base_task = self._router.fetch_intraday_fast(symbol)
        else:
            base_task = None  # a daily-family focus needs only the daily fetch

        daily, base_bars = await asyncio.gather(
            self._router.fetch_history(symbol, Timeframe.D1),
            base_task if base_task is not None else _empty(),
            return_exceptions=True,
        )

        daily_bars = daily if isinstance(daily, list) else []
        focus_bars = base_bars if isinstance(base_bars, list) else []

        if not daily_bars and not focus_bars:
            logger.warning("No data returned for %s", symbol)
            self._loads.pop(symbol, None)
            self._early_trades.pop(symbol, None)
            return False

        stamp = now_epoch()
        self._store.replace(symbol, Timeframe.D1, daily_bars, loaded_at=stamp)
        if base_task is not None:
            self._store.replace(symbol, base, focus_bars, loaded_at=stamp)
        self._rebuild_levels(symbol)
        self._loaded.add(symbol)
        await self._replay_early_trades(symbol)
        self._bump(symbol)
        self._loads.pop(symbol, None)

        logger.info(
            "Loaded %s (%s focus): %d base bars, %d daily bars; backfilling the rest",
            symbol,
            focus.value,
            len(focus_bars),
            len(daily_bars),
        )
        self._backfills[symbol] = asyncio.create_task(self._backfill(symbol, base))
        return True

    async def _backfill(self, symbol: str, fast_base: Timeframe) -> None:  # noqa: PLR0912
        """Phase two: whatever phase one skipped, merged in quietly.

        The minute base is never fetched from IBKR: its freshest minutes, which
        a delayed Alpaca feed cannot serve, are resampled from the 10s base
        instead. A ticker switch therefore costs exactly two IBKR historical
        requests. The prior sessions behind them are Alpaca REST pages.
        """
        try:
            recent: list[Bar] | None = None
            if fast_base is not Timeframe.S10:
                # Fetched first here: the older slices are measured from it.
                recent = await self._router.fetch_recent_tensec(symbol)
            edge = self._tensec_edge(
                recent if recent is not None else self._store.get(symbol, Timeframe.S10)
            )
            # Pairs rather than a dict keyed by timeframe: the 10s base is
            # filled by several fetches and merge order matters. `merge` lets
            # incoming bars win, so prior sessions go in first and IBKR's own
            # bars overwrite them where the windows overlap.
            fetches: list[tuple[Timeframe, Awaitable[list[Bar]]]] = [
                (Timeframe.S10, self._router.fetch_prior_tensec(symbol, edge))
            ]
            if fast_base is Timeframe.S10:
                fetches.append((Timeframe.S10, self._router.fetch_earlier_tensec(symbol, edge)))
                fetches.append((Timeframe.M1, self._router.fetch_intraday_fast(symbol)))
            elif fast_base is Timeframe.M1:
                fetches.append((Timeframe.S10, self._router.fetch_earlier_tensec(symbol, edge)))
            else:
                fetches.append((Timeframe.M1, self._router.fetch_intraday_fast(symbol)))
                fetches.append((Timeframe.S10, self._router.fetch_earlier_tensec(symbol, edge)))

            results = await asyncio.gather(
                *(awaitable for _, awaitable in fetches), return_exceptions=True
            )
            merges = [
                (timeframe, result)
                for (timeframe, _), result in zip(fetches, results, strict=True)
            ]
            if recent is not None:
                merges.append((Timeframe.S10, recent))

            landed = False
            for timeframe, result in merges:
                if isinstance(result, list) and result:
                    self._store.merge(
                        symbol, timeframe, self._without_live_edge(symbol, timeframe, result)
                    )
                    landed = True

            if self._refresh_minutes_from_tensec(symbol):
                landed = True

            if not landed or symbol not in self._loaded:
                return
            self._bump(symbol)
            for handler in self._backfill_handlers:
                try:
                    await handler(symbol)
                except Exception:
                    logger.exception("backfill handler failed for %s", symbol)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("backfill failed for %s", symbol)
        finally:
            # A cancelled backfill's cleanup can land after a reload has
            # already registered its successor; only this task's own entry
            # may be removed.
            if self._backfills.get(symbol) is asyncio.current_task():
                self._backfills.pop(symbol, None)

    @staticmethod
    def _tensec_edge(first_paint: list[Bar]) -> datetime | None:
        """Where the older 10s slices are measured back from.

        The first paint is the last four hours that actually traded, so with the
        market shut it ends on Friday; slices measured from the wall clock would
        ask for the weekend and get nothing. ``None`` leaves the router on now.
        """
        if not first_paint:
            return None
        edge = min(first_paint[0].time + TENSEC_RECENT_SECONDS, now_epoch())
        return datetime.fromtimestamp(edge, UTC)

    def _refresh_minutes_from_tensec(self, symbol: str) -> bool:
        """Fold the *live* end of the 10s base into fresh minute bars.

        Six consolidated 10-second bars sum to the consolidated minute, so this
        closes the delayed feed's 15-minute gap without an IBKR request. The
        newest minute is dropped — its final buckets may not exist yet — and the
        live builder owns it anyway.

        These *overwrite* Alpaca's published minutes where both exist, keeping
        both timeframes on one set of numbers. Older minutes keep Alpaca's,
        which read higher on the consolidated tape's convention: the one seam
        this accepts.

        Only the window IBKR actually served is folded — with TWS down that is
        none of it. The rest was rebuilt from Alpaca's tape through our own
        condition filter, so overwriting Alpaca's published minutes there would
        trade an authoritative number for an approximation, closing no gap.
        """
        tensec = self._store.get(symbol, Timeframe.S10)
        native = self._router.native_tensec_since(symbol)
        if not tensec or native is None:
            return False
        # Measured back from the live edge of the 10s base, not the wall clock:
        # it is the same boundary the router fetched against, and it stays true
        # of a series loaded from a fixture.
        cutoff = max(tensec[-1].time - TENSEC_WINDOW_SECONDS, native)
        live = [bar for bar in tensec if bar.time >= cutoff]
        if not live:
            return False
        minutes = resample(live, Timeframe.M1)[:-1]
        if not minutes:
            return False
        self._store.merge(symbol, Timeframe.M1, minutes)
        return True

    async def wait_for_backfill(self, symbol: str) -> None:
        """Block until the background pass settles — for tests."""
        task = self._backfills.get(symbol)
        if task is not None:
            await asyncio.shield(task)

    # ── gap repair ─────────────────────────────────────────────────────

    def schedule_recent_repair(self, symbol: str) -> None:
        """Re-fetch the recent 10s slice and merge it in.

        Called when the real-time source comes (back) online: history loaded
        from the delayed fallback ends fifteen minutes short of the live stream,
        and that seam never heals on its own once the symbol is marked loaded.
        """
        if symbol not in self._loaded:
            return
        existing = self._repairs.get(symbol)
        if existing is not None and not existing.done():
            return
        self._repairs[symbol] = asyncio.create_task(self._repair_recent(symbol))

    async def _repair_recent(self, symbol: str) -> None:
        try:
            bars = await self._router.fetch_recent_tensec(symbol)
            if not bars or symbol not in self._loaded:
                return
            self._store.merge(
                symbol, Timeframe.S10, self._without_live_edge(symbol, Timeframe.S10, bars)
            )
            self._refresh_minutes_from_tensec(symbol)
            self._bump(symbol)
            for handler in self._backfill_handlers:
                try:
                    await handler(symbol)
                except Exception:
                    logger.exception("repair handler failed for %s", symbol)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("recent-slice repair failed for %s", symbol)
        finally:
            if self._repairs.get(symbol) is asyncio.current_task():
                self._repairs.pop(symbol, None)

    async def wait_for_repair(self, symbol: str) -> None:
        """Block until a scheduled repair settles — for tests."""
        task = self._repairs.get(symbol)
        if task is not None:
            await asyncio.shield(task)

    def unload(self, symbol: str) -> None:
        """Stop working a symbol nobody is watching, keeping its bars warm.

        History stays parked so flipping back re-serves it with a single gap
        repair. Memory is reclaimed on expiry, or immediately for the oldest
        symbol when the warm cache is full.

        The revision counter survives eviction: the broadcaster's already-sent
        caches key on it, so it must be monotonic for the life of the process.
        Restarting at 1 would make a fresh load look already delivered.
        """
        was_loaded = symbol in self._loaded
        self._loaded.discard(symbol)
        # Only the hub awaits a load, and it releases a symbol only once no
        # client wants it; finishing would mark it loaded and start a backfill
        # spending IBKR requests on a chart nobody has open.
        load = self._loads.pop(symbol, None)
        if load is not None:
            load.cancel()
        backfill = self._backfills.pop(symbol, None)
        if backfill is not None:
            backfill.cancel()
        repair = self._repairs.pop(symbol, None)
        if repair is not None:
            repair.cancel()
        self._builders.pop(symbol, None)

        if was_loaded and self._store.has(symbol, Timeframe.M1):
            self._park(symbol)
        else:
            self._evict(symbol)

    def _park(self, symbol: str) -> None:
        existing = self._parked.pop(symbol, None)
        if existing is not None:
            existing.cancel()
        self._parked[symbol] = asyncio.create_task(self._expire_parked(symbol))
        # Oldest out when the warm cache is full; dict order is insertion order.
        while len(self._parked) > KEEP_WARM_MAX_SYMBOLS:
            oldest = next(iter(self._parked))
            self._parked.pop(oldest).cancel()
            self._evict(oldest)

    async def _expire_parked(self, symbol: str) -> None:
        try:
            await asyncio.sleep(KEEP_WARM_SECONDS)
        except asyncio.CancelledError:
            raise
        self._parked.pop(symbol, None)
        self._evict(symbol)

    def _evict(self, symbol: str) -> None:
        self._level_index.pop(symbol, None)
        self._store.clear(symbol)
        for cache in (self._bars_cache, self._series_cache):
            for key in [k for k in cache if k[0] == symbol]:
                cache.pop(key, None)

    def _rebuild_levels(self, symbol: str) -> None:
        daily = self._store.get(symbol, Timeframe.D1)
        if daily:
            self._level_index[symbol] = DailyLevelIndex(daily, self._engine.all_level_keys())
        else:
            self._level_index.pop(symbol, None)

    # ── reads ──────────────────────────────────────────────────────────

    def is_loaded(self, symbol: str) -> bool:
        return symbol in self._loaded

    @property
    def loaded_symbols(self) -> set[str]:
        return set(self._loaded)

    @property
    def working_symbols(self) -> set[str]:
        """Loaded, or still loading: everything ``unload`` has a reason to stop."""
        return self._loaded | set(self._loads)

    def revision(self, symbol: str) -> int:
        return self._revisions.get(symbol, 0)

    def bars(self, symbol: str, timeframe: Timeframe) -> list[Bar]:
        revision = self.revision(symbol)
        key = (symbol, timeframe)
        cached = self._bars_cache.get(key)
        if cached and cached[0] == revision:
            return cached[1]

        result = derive(self._base_bars(symbol, timeframe.base), timeframe)
        self._bars_cache[key] = (revision, result)
        return result

    def _base_bars(self, symbol: str, base: Timeframe) -> list[Bar]:
        """The stored base series, with the daily one carried up to now.

        Only the daily base needs this: it is fetched and never streamed, so
        without it the 1D and 1W charts sit at load-time price all session.
        Folding today's minutes in puts the day's candle on the same prices the
        intraday charts draw from.

        Derived on read rather than written back: the daily bars the key levels
        are built from must stay strictly historical, or a level would repaint
        as today traded.
        """
        stored = self._store.get(symbol, base)
        if base is not Timeframe.D1:
            return stored

        today = self._today_from_minutes(symbol)
        if today is None:
            return stored
        if not stored:
            return [today]
        # A minute base whose newest bar predates the newest daily row has
        # nothing to add — the weekend case, and the moment after a load
        # whose minutes have not landed yet.
        if stored[-1].time > today.time:
            return stored
        if stored[-1].time == today.time:
            return [*stored[:-1], _widen(stored[-1], today)]
        return [*stored, today]

    def _today_from_minutes(self, symbol: str) -> Bar | None:
        """The newest session's minute bars folded into one daily bar."""
        minutes = self._store.get(symbol, Timeframe.M1)
        if not minutes:
            return None
        # Integer comparisons against the day's opening stamp rather than a
        # timezone lookup per bar: this runs once per revision, and a session
        # of minutes is hundreds of bars.
        start = bucket_start(minutes[-1].time, Timeframe.D1)
        index = len(minutes)
        while index > 0 and minutes[index - 1].time >= start:
            index -= 1
        folded = resample(minutes[index:], Timeframe.D1)
        return folded[-1] if folded else None

    def series(self, symbol: str, timeframe: Timeframe) -> SeriesMap:
        revision = self.revision(symbol)
        key = (symbol, timeframe)
        cached = self._series_cache.get(key)
        if cached and cached[0] == revision:
            return cached[1]

        bars = self.bars(symbol, timeframe)
        result = self._engine.compute(
            bars,
            timeframe,
            level_index=self._level_index.get(symbol),
            session=self._session_levels(symbol, timeframe, bars),
            minute_bars=self._store.get(symbol, Timeframe.M1),
        )
        self._series_cache[key] = (revision, result)
        return result

    def _session_levels(
        self, symbol: str, timeframe: Timeframe, bars: list[Bar]
    ) -> SessionLevels:
        """Session-boundary prices for the day the chart is showing.

        From the minute base, not the displayed timeframe: the after-hours high
        belongs to the previous session, which the 10s window may not reach.
        """
        if not bars or not timeframe.is_intraday:
            return EMPTY_SESSION_LEVELS
        minutes = self._store.get(symbol, Timeframe.M1)
        if not minutes:
            return EMPTY_SESSION_LEVELS
        return session_levels(minutes, ny_date(bars[-1].time))

    def snapshot(self, symbol: str, timeframe: Timeframe) -> Snapshot | None:
        """The full chart payload, or ``None`` when the symbol has nothing.

        An *empty* snapshot is still sent when the symbol is loaded but this
        base has no history yet (a 10s chart on Alpaca before any trades), so
        the chart fills live rather than reporting the symbol as missing.
        """
        bars = self.bars(symbol, timeframe)
        if not bars and not self._has_any_bars(symbol):
            return None
        return snapshot_message(
            symbol=symbol,
            timeframe=timeframe,
            bars=bars,
            series=self.series(symbol, timeframe),
            source=self._router.active_source,
            delayed=self._router.is_delayed,
            generated_at=int(now_epoch()),
        )

    def build_update(self, symbol: str, timeframe: Timeframe) -> BarUpdate | None:
        """The newest bar plus each indicator's current value."""
        bars = self.bars(symbol, timeframe)
        if not bars:
            return None
        return bar_message(
            symbol=symbol,
            timeframe=timeframe,
            bar=bars[-1],
            series=self._engine.latest(
                bars,
                timeframe,
                self._level_index.get(symbol),
                self._session_levels(symbol, timeframe, bars),
                minute_bars=self._store.get(symbol, Timeframe.M1),
                # The windowed relative volume reaches past the minute base
                # into the daily one for its denominator, so the live value
                # matches the series the snapshot drew.
                daily_bars=self._store.get(symbol, Timeframe.D1),
            ),
        )

    def _has_any_bars(self, symbol: str) -> bool:
        return any(self._store.has(symbol, base) for base in (Timeframe.S10, Timeframe.M1, Timeframe.D1))

    # ── live data ──────────────────────────────────────────────────────

    # Live trades extend both intraday bases in lockstep. The daily store
    # stays a pure history product — today's candle is folded out of the
    # minute base on read instead, see `_base_bars`.
    _LIVE_TIMEFRAMES = (Timeframe.S10, Timeframe.M1)

    async def _handle_trade(self, symbol: str, trade: Trade) -> None:
        if symbol not in self._loaded:
            early = self._early_trades.get(symbol)
            if symbol in self._loads and (early is None or len(early) < EARLY_TRADE_LIMIT):
                self._early_trades.setdefault(symbol, []).append(trade)
            return

        builders = self._builders.setdefault(symbol, {})
        for timeframe in self._LIVE_TIMEFRAMES:
            builder = builders.get(timeframe)
            if builder is None:
                builder = BarBuilder(timeframe)
                # Continue the period already in the store rather than opening
                # a fresh bar mid-period, which would discard its volume so far.
                seed = self._live_seed(symbol, timeframe)
                if seed is not None:
                    builder.adopt(seed)
                builders[timeframe] = builder

            completed = builder.add_trade(trade)
            if completed is not None:
                self._store.upsert(symbol, timeframe, completed)
            current = builder.current
            if current is not None:
                self._store.upsert(symbol, timeframe, current)
        self._bump(symbol)

    def _live_seed(self, symbol: str, timeframe: Timeframe) -> Bar | None:
        """The bar a new builder continues. For the minute, the 10s tail when no
        minute bar reaches that far yet — with a 10s focus the minute base has
        not loaded, and a builder started empty commits the minute short."""
        existing = self._store.get(symbol, timeframe)
        last = existing[-1] if existing else None
        if timeframe is Timeframe.M1:
            tensec = self._store.get(symbol, Timeframe.S10)
            if tensec:
                minute = bucket_start(tensec[-1].time, Timeframe.M1)
                if last is None or last.time < minute:
                    tail = [bar for bar in tensec[-MINUTE_BUCKETS:] if bar.time >= minute]
                    return resample(tail, Timeframe.M1)[-1]
        return last

    async def _replay_early_trades(self, symbol: str) -> None:
        """Apply the prints that arrived during the load, past its last bar."""
        trades = self._early_trades.pop(symbol, [])
        base = Timeframe.S10 if self._store.has(symbol, Timeframe.S10) else Timeframe.M1
        stored = self._store.get(symbol, base)
        after = stored[-1].time + base.seconds if stored else 0
        for trade in trades:
            if trade.time >= after:
                await self._handle_trade(symbol, trade)

    def _without_live_edge(self, symbol: str, timeframe: Timeframe, bars: list[Bar]) -> list[Bar]:
        """``bars`` less the two the live builder owns: a snapshot fetched while
        a period closed holds it half-built, and ``merge`` lets it win."""
        builder = self._builders.get(symbol, {}).get(timeframe)
        current = builder.current if builder is not None else None
        if current is None:
            return bars
        edge = current.time - timeframe.seconds
        return [bar for bar in bars if bar.time < edge]

    async def _handle_bar(self, symbol: str, timeframe: Timeframe, bar: Bar) -> None:
        """Apply a provider's own minute bar where our 10s base does not reach.

        Where it does, the minute stays the sum of its 10s bars: a provider bar
        counts prints our condition filter drops, and on a delayed feed lands
        fifteen minutes late over minutes already built.
        """
        if symbol not in self._loaded or timeframe is not Timeframe.M1:
            return
        tensec = self._store.get(symbol, Timeframe.S10)
        if tensec and tensec[-1].time >= bar.time:
            return

        self._store.upsert(symbol, Timeframe.M1, bar)
        builder = self._builders.get(symbol, {}).get(Timeframe.M1)
        if builder is not None and builder.current is not None and builder.current.time == bar.time:
            builder.adopt(bar)
        self._bump(symbol)

    def touch(self, symbol: str) -> None:
        """Force a re-broadcast — e.g. reference stats arrived out of band."""
        if symbol in self._loaded:
            self._bump(symbol)

    def _bump(self, symbol: str) -> None:
        self._revisions[symbol] = self._revisions.get(symbol, 0) + 1


def _widen(stored: Bar, session: Bar) -> Bar:
    """The fetched day's row extended by the session folded from minutes.

    Extended, never narrowed: the minute base can have seen less of the day than
    the provider's row, so nothing here may shrink a published range.

    Volume takes whichever side counted more. Ours runs on the IBKR-derived
    convention and reads a few percent under the consolidated tape (the seam
    `_refresh_minutes_from_tensec` accepts), so taking the larger holds the
    published number until our own count overtakes it and never walks backwards.

    The close is the newest price either side holds, which is the minute base's.
    The open stays the provider's, since the gap is measured from it.
    """
    return Bar(
        time=stored.time,
        open=stored.open,
        high=max(stored.high, session.high),
        low=min(stored.low, session.low),
        close=session.close,
        volume=max(stored.volume, session.volume),
        trades=max(stored.trades, session.trades),
    )


async def _empty() -> list[Bar]:
    return []
