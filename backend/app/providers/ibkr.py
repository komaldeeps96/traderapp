"""Interactive Brokers via TWS / IB Gateway.

``ib_async`` is an optional dependency and is imported lazily, so the whole
application — and its test suite — runs without it installed. When TWS is not
reachable the provider simply reports itself unavailable and the router falls
back to Alpaca.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from ..core.settings import IBKRSettings, ScannerSettings
from ..domain.bars import Bar
from ..domain.quotes import Quote
from ..domain.scanner import ScannerConfig, ScannerRow
from ..domain.timeframes import Timeframe
from ..market.bar_builder import Trade
from ..market.conditions import TradeKind, classify_conditions
from .base import MarketDataProvider

logger = logging.getLogger(__name__)

# "Last" is IBKR's last-sale-eligible slice of the tape; "AllLast" is the
# whole thing. We take the slice, because IBKR's own bars are built from it
# and those bars are this app's baseline.
#
# Measured on a small-cap gapper: recording the full tape alongside
# reqRealTimeBars(5), IBKR's bars reproduce the tape *minus odd lots* to
# within 0.1% (1.001) while the whole tape overshoots volume by 26.6%
# (1.266). Its 5s bars, its historical bars and this stream therefore all
# agree, and so does the TWS window beside us. Since the 10s history *is*
# IBKR bars and the minute base is resampled from it, matching that slice
# live is what keeps 10s and 1m indicators consistent across the whole 10s
# window rather than only where one source reaches.
#
# It is also markedly cheaper: over equal windows "Last" delivered 744 prints
# against "AllLast"'s 3,781 — roughly a fifth of the messages to parse,
# classify and fold, per symbol.
#
# The cost, accepted knowingly: odd lots are ~21-26% of shares on a small-cap
# gapper, so volume — and therefore RVOL and float rotation — sits that far
# below any SIP-based screener. app/market/conditions.py holds the Alpaca
# side of the same decision.
TICK_TYPE = "Last"

_BAR_SIZE = {
    Timeframe.S10: "10 secs",
    Timeframe.M1: "1 min",
    Timeframe.M5: "5 mins",
    Timeframe.M15: "15 mins",
    Timeframe.H1: "1 hour",
    Timeframe.D1: "1 day",
    Timeframe.W1: "1 week",
}

# IBKR rejects historical requests spanning more than this per bar size, so
# anything longer is fetched in chunks walking backwards from the end.
_MAX_REQUEST_SECONDS = {
    Timeframe.S10: 14_400,  # 4 hours of 10-second bars per request
}
# Courtesy gap between chunked requests, well inside IBKR pacing rules.
_CHUNK_PAUSE_SECONDS = 0.15

# Per-row scanner metrics are kept over these trailing windows.
TRADE_WINDOW_1M = 60
TRADE_WINDOW_5M = 300
TRADE_BUFFER_MAX_AGE = 360

ScannerHandler = Callable[[list[ScannerRow]], Awaitable[None]]


class _CancelAckFilter(logging.Filter):
    """Drop TWS's acknowledgement of scanner cancels *we* requested.

    Every scanner restart cancels the previous subscription first; TWS
    confirms with error code 162 reading "API scanner subscription
    cancelled", which ib_async logs at ERROR level. That is an ack, not a
    failure — and every other 162 (real historical-data errors) still logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "API scanner subscription cancelled" not in record.getMessage()


def _import_ib():
    try:
        from ib_async import IB, ScannerSubscription, Stock  # noqa: PLC0415
    except ImportError:  # pragma: no cover - exercised only without the extra
        return None
    logging.getLogger("ib_async.wrapper").addFilter(_CancelAckFilter())
    return IB, Stock, ScannerSubscription


class IBKRProvider(MarketDataProvider):
    name = "ibkr"

    def __init__(self, settings: IBKRSettings, scanner_settings: ScannerSettings, budget=None):
        super().__init__()
        self._settings = settings
        self._scanner_settings = scanner_settings
        # ProviderBudget from services.api_budget covering historical-data
        # pacing; optional so tests can run the provider bare.
        self._budget = budget
        self._ib = None
        self._stock = None
        self._scanner_subscription_cls = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._should_run = False
        self._connected_event = asyncio.Event()
        self._started_at = 0.0
        self._connect_lock = asyncio.Lock()
        self._contracts: dict[str, object] = {}
        self._streams: dict[str, object] = {}
        self._symbols: set[str] = set()
        self._pending: set[asyncio.Future] = set()

        self._scanner_handlers: list[ScannerHandler] = []
        self._scanner_data = None
        self._scanner_config: ScannerConfig | None = None
        self._scanner_last_emit = 0.0
        self._scanner_started_at: float | None = None
        self._scanner_streams: dict[str, dict] = {}
        self._scanner_raw: list = []
        self._scanner_refresh_task: asyncio.Task | None = None

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        if not self._settings.enabled:
            logger.info("IBKR disabled by configuration")
            return

        imported = _import_ib()
        if imported is None:
            logger.warning(
                "IBKR enabled but 'ib-async' is not installed "
                "(pip install -e '.[ibkr]'); using Alpaca only"
            )
            return

        ib_cls, self._stock, self._scanner_subscription_cls = imported
        self._ib = ib_cls()
        self._loop = asyncio.get_running_loop()
        self._should_run = True
        self._started_at = time.monotonic()
        self._reconnect_task = asyncio.create_task(self._connect_loop())

    async def stop(self) -> None:
        self._should_run = False
        self._connected_event.clear()
        if self._reconnect_task:
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None

        await self.stop_scanner()
        if self._ib is not None:
            with contextlib.suppress(Exception):
                self._ib.disconnectedEvent -= self._on_disconnected
            if self._ib.isConnected():
                self._ib.disconnect()
        self._contracts.clear()
        self._streams.clear()
        self._symbols.clear()

    @property
    def is_available(self) -> bool:
        return bool(self._ib is not None and self._ib.isConnected())

    async def _connect_loop(self) -> None:
        attempt = 0
        while self._should_run:
            if self.is_available:
                await asyncio.sleep(1.0)
                continue

            attempt += 1
            async with self._connect_lock:
                if self.is_available:
                    continue
                try:
                    await asyncio.wait_for(
                        self._ib.connectAsync(
                            self._settings.host,
                            self._settings.port,
                            clientId=self._settings.client_id,
                            readonly=True,
                        ),
                        timeout=self._settings.connect_timeout_seconds,
                    )
                    logger.info(
                        "IBKR connected (%s:%s)", self._settings.host, self._settings.port
                    )
                    attempt = 0
                    self._connected_event.set()
                    self._ib.disconnectedEvent += self._on_disconnected
                    await self._emit_status()
                    # Re-establish streams that were routed elsewhere while down.
                    await self._apply_streams(self._symbols)
                    continue
                except Exception as exc:
                    delay = min(2 ** min(attempt, 5), self._settings.max_reconnect_delay_seconds)
                    logger.info(
                        "IBKR unavailable (%s); retrying in %ss", exc, int(delay)
                    )
            await asyncio.sleep(delay)

    def _on_disconnected(self) -> None:
        logger.warning("IBKR connection lost; falling back until it returns")
        self._connected_event.clear()
        self._streams.clear()
        self._schedule(self._emit_status())

    @property
    def is_starting_up(self) -> bool:
        """True while the first connection may still be moments away.

        A server restart races its own history loads against the TWS
        handshake; inside this window it is worth waiting a beat for the
        real-time source instead of silently loading delayed data.
        """
        return (
            self._should_run
            and self._ib is not None
            and not self.is_available
            and time.monotonic() - self._started_at < 15.0
        )

    # The caller is the failover path, which budgets this wait explicitly
    # rather than wrapping the call in its own `asyncio.timeout`.
    async def wait_available(self, timeout: float) -> bool:  # noqa: ASYNC109
        """Wait briefly for the connection; False when it does not come."""
        if self.is_available:
            return True
        if not self._should_run or self._ib is None:
            return False
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout)
        except TimeoutError:
            return False
        return self.is_available

    def _schedule(self, coro) -> None:
        """Run a coroutine on the main loop from any thread.

        ib_async delivers most events on the event loop, but not all of its
        callbacks are guaranteed to, so this tolerates both cases.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is loop:
            task = loop.create_task(coro)
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)
        else:
            asyncio.run_coroutine_threadsafe(coro, loop)

    # ── history ────────────────────────────────────────────────────────

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        if not self.is_available:
            return []

        contract = await self._contract(symbol)
        if contract is None:
            return []

        span = max(int((end - start).total_seconds()), 60)
        chunk_limit = _MAX_REQUEST_SECONDS.get(timeframe)

        if chunk_limit is None or span <= chunk_limit:
            duration = f"{span} S" if span <= 86_400 else f"{max(1, span // 86_400)} D"
            # An empty endDateTime means "now" to TWS and sidesteps clock
            # skew, but only when the caller actually wants now — a window
            # ending in the past (the 10s background slice) must say so, or
            # TWS silently serves the most recent bars instead.
            ends_now = (datetime.now(UTC) - end).total_seconds() < 60
            bars = await self._request_bars(
                symbol, contract, timeframe, "" if ends_now else end, duration
            )
        else:
            bars = await self._fetch_chunked(symbol, contract, timeframe, start, end, chunk_limit)

        logger.info("IBKR: %s %s -> %d bars", symbol, timeframe.value, len(bars))
        return bars

    async def _fetch_chunked(
        self,
        symbol: str,
        contract,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        chunk_limit: int,
    ) -> list[Bar]:
        """Walk backwards from ``end`` in requests IBKR will accept.

        Overnight chunks legitimately come back empty, so an empty response
        does not stop the walk; only reaching ``start`` does.
        """
        by_time: dict[int, Bar] = {}
        chunk_end = end

        while chunk_end > start:
            chunk_start = max(start, chunk_end - timedelta(seconds=chunk_limit))
            span = max(int((chunk_end - chunk_start).total_seconds()), 60)
            chunk = await self._request_bars(
                symbol, contract, timeframe, chunk_end, f"{span} S"
            )
            for bar in chunk:
                by_time[bar.time] = bar
            chunk_end = chunk_start
            if chunk_end > start:
                await asyncio.sleep(_CHUNK_PAUSE_SECONDS)

        return [by_time[t] for t in sorted(by_time)]

    async def _request_bars(
        self,
        symbol: str,
        contract,
        timeframe: Timeframe,
        end: datetime | str,
        duration: str,
    ) -> list[Bar]:
        # Historical requests are the paced resource; streaming lines are not.
        if self._budget is not None:
            await self._budget.acquire()
        try:
            raw = await self._ib.reqHistoricalDataAsync(
                contract,
                endDateTime=end,
                durationStr=duration,
                barSizeSetting=_BAR_SIZE[timeframe],
                whatToShow="TRADES",
                useRTH=False,
                formatDate=2,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("IBKR history failed for %s: %s", symbol, exc)
            return []

        intraday = timeframe not in (Timeframe.D1, Timeframe.W1)
        bars: list[Bar] = []
        for item in raw or []:
            timestamp = item.date
            if isinstance(timestamp, datetime):
                epoch = int(
                    timestamp.replace(tzinfo=timestamp.tzinfo or UTC).timestamp()
                )
            else:
                continue
            # TWS gap-fills intervals with no trades: a flat zero-volume bar
            # repeating the last print. The live builder never creates such
            # bars, so history must not either — on a quiet tape they bury
            # the real candles in hundreds of invisible placeholders.
            if intraday and not item.volume and not item.barCount:
                continue
            bars.append(
                Bar(
                    time=epoch,
                    open=float(item.open),
                    high=float(item.high),
                    low=float(item.low),
                    close=float(item.close),
                    volume=float(item.volume or 0),
                    trades=float(item.barCount or 0),
                )
            )
        return bars

    # ── streaming ──────────────────────────────────────────────────────

    async def set_stream_symbols(self, symbols: set[str]) -> None:
        self._symbols = set(symbols)
        if self.is_available:
            await self._apply_streams(self._symbols)

    async def _apply_streams(self, symbols: set[str]) -> None:
        for symbol in list(self._streams):
            if symbol not in symbols:
                self._cancel_stream(symbol)

        for symbol in symbols:
            if symbol in self._streams:
                continue
            contract = await self._contract(symbol)
            if contract is None:
                continue
            try:
                ticker = self._ib.reqTickByTickData(contract, TICK_TYPE, numberOfTicks=0)
            except Exception as exc:
                logger.warning("IBKR tick subscription failed for %s: %s", symbol, exc)
                continue
            ticker.updateEvent += functools.partial(self._on_tick, symbol)

            # A second, ordinary market data line carries the top-of-book
            # quote for the bid/ask/spread readout.
            quote_ticker = None
            try:
                quote_ticker = self._ib.reqMktData(contract, genericTickList="", snapshot=False)
                quote_ticker.updateEvent += functools.partial(self._on_quote, symbol)
            except Exception as exc:
                logger.debug("IBKR quote subscription failed for %s: %s", symbol, exc)

            self._streams[symbol] = {
                "ticker": ticker,
                "contract": contract,
                "quote_ticker": quote_ticker,
            }
            logger.info("IBKR streaming %s", symbol)

    def _cancel_stream(self, symbol: str) -> None:
        stream = self._streams.pop(symbol, None)
        if not stream:
            return
        with contextlib.suppress(Exception):
            self._ib.cancelTickByTickData(stream["contract"], TICK_TYPE)
        # The market data line is shared per contract inside ib_async, so it
        # is only cancelled when the scanner is not also displaying this row.
        if stream.get("quote_ticker") is not None and symbol not in self._scanner_streams:
            with contextlib.suppress(Exception):
                self._ib.cancelMktData(stream["contract"])

    def _on_quote(self, symbol: str, ticker) -> None:
        bid = _clean(getattr(ticker, "bid", None))
        ask = _clean(getattr(ticker, "ask", None))
        if not bid or not ask or bid <= 0 or ask <= 0:
            return
        # IBKR reports US stock top-of-book sizes in round lots.
        bid_size = (_clean(getattr(ticker, "bidSize", None)) or 0) * 100
        ask_size = (_clean(getattr(ticker, "askSize", None)) or 0) * 100
        self._schedule(
            self._emit_quote(
                symbol,
                Quote(
                    bid=bid,
                    ask=ask,
                    bid_size=bid_size,
                    ask_size=ask_size,
                    time=time.time(),
                ),
            )
        )

    def _on_tick(self, symbol: str, ticker) -> None:
        prints = getattr(ticker, "tickByTicks", None)
        if not prints:
            return
        for tick in list(prints):
            price = float(getattr(tick, "price", 0) or 0)
            size = float(getattr(tick, "size", 0) or 0)
            if price <= 0 or size <= 0:
                continue
            # IBKR has already applied last-sale eligibility on "Last", so
            # this is defence in depth rather than the primary filter — but
            # it costs one set intersection and it is the same rule the
            # Alpaca stream runs, so a failover cannot change the meaning of
            # a bar. IBKR packs conditions as one string of single characters.
            kind = classify_conditions(getattr(tick, "specialConditions", "") or "")
            if kind is TradeKind.SKIP:
                continue
            # Past-limit and unreported are IBKR-specific flags with no SIP
            # condition code; a print carrying either is not a market price.
            attribs = getattr(tick, "tickAttribLast", None)
            price_forming = kind is TradeKind.PRICE_FORMING and not (
                getattr(attribs, "pastLimit", False) or getattr(attribs, "unreported", False)
            )
            moment = getattr(tick, "time", None)
            epoch = moment.timestamp() if moment else datetime.now(UTC).timestamp()
            self._schedule(
                self._emit_trade(
                    symbol,
                    Trade(time=epoch, price=price, size=size, price_forming=price_forming),
                )
            )
        prints.clear()

    async def _contract(self, symbol: str):
        cached = self._contracts.get(symbol)
        if cached is not None:
            return cached
        try:
            contract = self._stock(symbol, "SMART", "USD")
            await self._ib.qualifyContractsAsync(contract)
        except Exception as exc:
            logger.warning("IBKR could not qualify %s: %s", symbol, exc)
            return None
        self._contracts[symbol] = contract
        return contract

    # ── scanner ────────────────────────────────────────────────────────

    def on_scanner(self, handler: ScannerHandler) -> None:
        self._scanner_handlers.append(handler)

    async def start_scanner(self, config: ScannerConfig) -> bool:
        if not self.is_available or self._scanner_subscription_cls is None:
            return False

        await self.stop_scanner()
        subscription = self._scanner_subscription_cls(
            numberOfRows=config.number_of_rows,
            instrument=self._scanner_settings.instrument,
            locationCode=self._scanner_settings.location_code,
            scanCode=config.scan_code,
        )
        if config.above_price is not None:
            subscription.abovePrice = config.above_price
        if config.below_price is not None:
            subscription.belowPrice = config.below_price
        if config.above_volume is not None:
            subscription.aboveVolume = config.above_volume
        # IBKR's scanner takes market cap in MILLIONS of dollars; our config
        # carries plain dollars like everything else in the app.
        if config.market_cap_above is not None:
            subscription.marketCapAbove = config.market_cap_above / 1e6
        if config.market_cap_below is not None:
            subscription.marketCapBelow = config.market_cap_below / 1e6

        # Percent change has no dedicated subscription field; it rides in the
        # generic filter list. Not every scan code honours it, so rows are
        # filtered again after the fact in _process_scanner.
        filter_options = []
        if config.change_perc_above is not None:
            filter_options.append(_tag_value("changePercAbove", str(config.change_perc_above)))

        # Stock type must go through the filter list too. `ScannerSubscription`
        # has a `stockTypeFilter` attribute and setting it does nothing at all
        # — measured: a 2x leveraged ETF stayed at rank 1 with the field set,
        # and disappeared the moment the same value was passed as `stkTypes`.
        # The failure is silent, which is why the codes are validated on the
        # way in (see ScannerSettings.exclude_stock_types).
        #
        # One tag carrying a comma-separated list. Repeating the tag once per
        # type silently loses all but one of them.
        excluded = self._scanner_settings.exclude_stock_types
        if excluded:
            filter_options.append(
                _tag_value("stkTypes", ",".join(f"exc:{code}" for code in excluded))
            )

        kwargs = {"scannerSubscriptionFilterOptions": filter_options} if filter_options else {}
        try:
            self._scanner_last_emit = 0.0
            self._scanner_data = self._ib.reqScannerSubscription(subscription, **kwargs)
            self._scanner_data.updateEvent += self._on_scanner_update
        except Exception as exc:
            logger.warning("IBKR scanner failed to start: %s", exc)
            self._scanner_data = None
            return False
        self._scanner_config = config
        self._scanner_started_at = time.monotonic()
        if self._scanner_refresh_task is None or self._scanner_refresh_task.done():
            self._scanner_refresh_task = asyncio.create_task(self._scanner_refresh_loop())

        logger.info(
            "IBKR scanner subscribed: %s (price %s-%s, vol>%s, mcap %s-%s, chg>%s, %d rows) "
            "— waiting on first results",
            config.scan_code,
            config.above_price,
            config.below_price,
            config.above_volume,
            config.market_cap_above,
            config.market_cap_below,
            config.change_perc_above,
            config.number_of_rows,
        )
        return True

    async def stop_scanner(self) -> None:
        if self._scanner_refresh_task is not None:
            self._scanner_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scanner_refresh_task
            self._scanner_refresh_task = None
        if self._scanner_data is not None:
            data, self._scanner_data = self._scanner_data, None
            with contextlib.suppress(Exception):
                data.updateEvent -= self._on_scanner_update
                self._ib.cancelScannerSubscription(data)
        self._scanner_raw = []
        for symbol in list(self._scanner_streams):
            self._cancel_scanner_stream(symbol)

    def _on_scanner_update(self, rows) -> None:
        # IBKR pushes a fresh ranking only every ~30 seconds. The membership
        # is remembered here; emission is throttled, and the refresh loop
        # re-reads the live tickers in between so the columns never wait for
        # the next ranking to fill in.
        self._scanner_raw = list(rows)
        now = time.monotonic()
        if now - self._scanner_last_emit < self._scanner_settings.min_refresh_seconds:
            return
        self._scanner_last_emit = now
        self._schedule(self._process_scanner(self._scanner_raw))

    async def _scanner_refresh_loop(self) -> None:
        """Re-read the per-row tickers between IBKR's ranking pushes.

        The scan decides membership roughly twice a minute; prices, rates
        and the trade-rate sort live on the market-data lines, which stream
        continuously. Without this loop the columns of a fresh scan sit
        blank until the *next* ranking arrives.
        """
        interval = self._scanner_settings.min_refresh_seconds
        while True:
            await asyncio.sleep(interval)
            if not self._scanner_raw or self._scanner_data is None:
                continue
            now = time.monotonic()
            if now - self._scanner_last_emit < interval:
                continue
            self._scanner_last_emit = now
            try:
                await self._process_scanner(self._scanner_raw)
            except Exception:
                logger.exception("scanner refresh failed")

    async def _process_scanner(self, raw_rows: list) -> None:
        self._sync_scanner_streams(raw_rows)
        now = time.time()
        rows: list[ScannerRow] = []

        for entry in raw_rows:
            contract = entry.contractDetails.contract
            symbol = contract.symbol
            stream = self._scanner_streams.get(symbol)
            ticker = stream["ticker"] if stream else None

            last = _clean(getattr(ticker, "last", None)) if ticker else None
            close = _clean(getattr(ticker, "close", None)) if ticker else None
            price = last if last is not None else close
            # Tick 8 counts *lots*, not shares. Measured against the same
            # day's bars: x100 lands within a few percent, and the residual
            # is odd lots — this tick carries them, IBKR's bars do not, so
            # the two run 5-27% apart on a small cap by design.
            lots = _clean(getattr(ticker, "volume", None)) if ticker else None
            volume = lots * 100 if lots is not None else None
            vwap = _clean(getattr(ticker, "vwap", None)) if ticker else None
            trade_count = _clean(getattr(ticker, "tradeCount", None)) if ticker else None
            trade_rate = _clean(getattr(ticker, "tradeRate", None)) if ticker else None
            volume_rate = _clean(getattr(ticker, "volumeRate", None)) if ticker else None

            pct_change = None
            if price is not None and close:
                pct_change = (price - close) / close * 100.0

            # Re-apply the percent filter: subscription filterOptions are
            # honoured inconsistently across scan codes.
            threshold = (
                self._scanner_config.change_perc_above if self._scanner_config else None
            )
            if threshold is not None and pct_change is not None and pct_change < threshold:
                continue

            trades = stream["trades"] if stream else ()
            window_1m = [t for t in trades if now - t[0] <= TRADE_WINDOW_1M]
            window_5m = [t for t in trades if now - t[0] <= TRADE_WINDOW_5M]

            # IBKR's own per-minute rates (ticks 294/295) are authoritative —
            # they match TWS's Trades/Min column. Counting RTVolume prints
            # undercounts badly on a hot tape, because the market data line
            # conflates trades inside each ~250ms update; the window count
            # survives only as the warm-up fallback.
            trades_1m = int(trade_rate) if trade_rate is not None else len(window_1m)
            if volume_rate is not None and price is not None:
                dollar_vol_1m = volume_rate * price
            else:
                dollar_vol_1m = sum(p * s for _, p, s in window_1m)

            rows.append(
                ScannerRow(
                    rank=entry.rank,
                    symbol=symbol,
                    exchange=contract.exchange or "",
                    price=price,
                    pct_change=pct_change,
                    volume=volume,
                    trades_1m=trades_1m,
                    trades_5m=len(window_5m),
                    dollar_vol_1m=dollar_vol_1m,
                    dollar_vol_5m=sum(p * s for _, p, s in window_5m),
                    trades_day=trade_count,
                    dollar_vol_day=(volume * vwap) if volume and vwap else None,
                )
            )

        # A sane default order only. The real ranking needs history this
        # provider does not keep, and happens in ScannerService — which also
        # re-sorts, so this just decides what a cold start looks like.
        # ``trades_5m`` is deliberately not a tiebreaker: it counts prints off
        # the market-data line, which is unreliable in both directions.
        rows.sort(key=lambda row: (row.trades_1m, row.dollar_vol_1m), reverse=True)

        if self._scanner_started_at is not None:
            elapsed = time.monotonic() - self._scanner_started_at
            self._scanner_started_at = None
            logger.info(
                "IBKR scanner first results: %d rows, %.1fs after subscribe", len(rows), elapsed
            )

        for handler in self._scanner_handlers:
            try:
                await handler(rows)
            except Exception:
                logger.exception("scanner handler failed")

    def _sync_scanner_streams(self, raw_rows: list) -> None:
        """One market data line per visible row.

        Rows that survive a refresh keep their trade buffer — that continuity
        is the whole point of a sliding window.
        """
        wanted = {
            entry.contractDetails.contract.symbol: entry.contractDetails.contract
            for entry in raw_rows
        }

        for symbol in list(self._scanner_streams):
            if symbol not in wanted:
                self._cancel_scanner_stream(symbol)

        for symbol, contract in wanted.items():
            if symbol in self._scanner_streams:
                continue
            try:
                # 233 = per-trade prints (RTVolume), 293 = day trade count,
                # 294/295 = IBKR's own trade-rate and volume-rate per minute —
                # the same numbers TWS's Trades/Min and Vlm/Mn columns show.
                ticker = self._ib.reqMktData(
                    contract, genericTickList="233,293,294,295", snapshot=False
                )
            except Exception as exc:
                logger.debug("scanner market data failed for %s: %s", symbol, exc)
                continue
            ticker.updateEvent += functools.partial(self._on_scanner_tick, symbol)
            self._scanner_streams[symbol] = {
                "contract": contract,
                "ticker": ticker,
                "trades": deque(),
            }

    def _on_scanner_tick(self, symbol: str, ticker) -> None:
        stream = self._scanner_streams.get(symbol)
        if stream is None:
            return
        trades = stream["trades"]
        now = time.time()
        for tick in getattr(ticker, "ticks", ()) or ():
            price = _clean(getattr(tick, "price", None))
            size = _clean(getattr(tick, "size", None))
            if price and size and size > 0:
                trades.append((now, price, size))

        cutoff = now - TRADE_BUFFER_MAX_AGE
        while trades and trades[0][0] < cutoff:
            trades.popleft()

    def _cancel_scanner_stream(self, symbol: str) -> None:
        stream = self._scanner_streams.pop(symbol, None)
        if stream is None:
            return
        # Shared line: keep it if the chart's quote readout still uses it.
        chart_stream = self._streams.get(symbol)
        if chart_stream is not None and chart_stream.get("quote_ticker") is not None:
            return
        with contextlib.suppress(Exception):
            self._ib.cancelMktData(stream["contract"])


def _tag_value(tag: str, value: str):
    try:
        from ib_async import TagValue  # noqa: PLC0415 — optional dependency
    except ImportError:  # pragma: no cover - exercised only without the extra
        from collections import namedtuple  # noqa: PLC0415

        TagValue = namedtuple("TagValue", ["tag", "value"])
    return TagValue(tag, value)


def _clean(value: object) -> float | None:
    """IBKR uses NaN for "no value"."""
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number
