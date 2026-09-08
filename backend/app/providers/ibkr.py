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
from ..domain.news import extract_tickers
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
    Timeframe.M30: "30 mins",
    Timeframe.H1: "1 hour",
    Timeframe.H4: "4 hours",
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
# (symbol, raw headline row) for a live headline off generic tick 292.
NewsHandler = Callable[[str, dict], Awaitable[None]]

# One market-data stream can serve every scanner tier that wants the
# symbol. ib_async's own client-side ticker cache is keyed by contract hash
# alone (wrapper.startTicker), and a second reqMktData call on a contract
# already tracked *overwrites* the reqId a later cancelMktData would act on
# — cancelling whichever tier subscribed most recently rather than the one
# that asked to stop, and leaking the other's line on the TWS side forever.
# Refcounting ownership here, rather than letting each tier open its own
# line, is what keeps a symbol near a market-cap boundary — briefly visible
# to two tiers at once — from tripping that.


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


def _duration_string(span: int) -> str:
    """TWS duration string for a window of ``span`` seconds.

    Days stop being the right unit once a window runs to years: the daily
    base now asks for four decades so that one Alpaca page comes back full,
    and TWS rejects a duration of fourteen thousand days where it accepts
    the same window written in years.
    """
    if span <= 86_400:
        return f"{span} S"
    days = max(1, span // 86_400)
    if days <= 365:
        return f"{days} D"
    return f"{-(-days // 365)} Y"


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
        # Latest shortable reads per focused symbol, from generic tick 236 on
        # the quote line: (tier, shares). Tier is IBKR's 0-3 magnitude —
        # above 2.5 easy to borrow, 1.5-2.5 locate required, below 1.5 none.
        self._borrow: dict[str, tuple[float | None, float | None]] = {}
        # Last halt state emitted per symbol, so the halted tick — which
        # rides every quote update — only fans out on a transition.
        self._halt_state: dict[str, bool] = {}
        self._symbols: set[str] = set()
        self._pending: set[asyncio.Future] = set()
        self._news_handlers: list[NewsHandler] = []
        # (code, name) for the entitled feeds. Fetched once: entitlements do
        # not change inside a session.
        self._news_providers: list[tuple[str, str]] | None = None

        # Keyed by scanner_id — one entry per concurrently-running tier.
        self._scanner_handlers: dict[str, list[ScannerHandler]] = {}
        self._scanner_data: dict[str, object] = {}
        self._scanner_config: dict[str, ScannerConfig] = {}
        self._scanner_last_emit: dict[str, float] = {}
        self._scanner_started_at: dict[str, float | None] = {}
        self._scanner_raw: dict[str, list] = {}
        self._scanner_refresh_tasks: dict[str, asyncio.Task] = {}
        # Two separately-constructed functools.partial objects are never
        # `==`, so the exact callback each tier's updateEvent was given has
        # to be kept around to detach it again symmetrically.
        self._scanner_update_cbs: dict[str, Callable] = {}
        # NOT keyed by scanner_id: one market-data line per symbol, shared
        # across every tier that currently wants it. See the module-level
        # comment by ScannerHandler for why.
        self._scanner_streams: dict[str, dict] = {}

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

        for scanner_id in list(self._scanner_data):
            await self.stop_scanner(scanner_id)
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
                    # Live headlines arrive on this one event for every
                    # subscribed contract at once — see _on_news_tick for why
                    # attribution is done from the headline text.
                    self._ib.tickNewsEvent += self._on_news_tick
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
            duration = _duration_string(span)
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
                # 236 = shortable: delivers the borrow tier (tick 46) and
                # the locate pool size (tick 89) on the same line.
                # 292 = news: live headlines from the entitled feeds, which is
                # the one fundamentals-adjacent thing this account does get.
                quote_ticker = self._ib.reqMktData(
                    contract, genericTickList="236,292", snapshot=False
                )
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
        self._borrow.pop(symbol, None)
        self._halt_state.pop(symbol, None)
        if not stream:
            return
        with contextlib.suppress(Exception):
            self._ib.cancelTickByTickData(stream["contract"], TICK_TYPE)
        # The market data line is shared per contract inside ib_async, so it
        # is only cancelled when the scanner is not also displaying this row.
        if stream.get("quote_ticker") is not None and symbol not in self._scanner_streams:
            with contextlib.suppress(Exception):
                self._ib.cancelMktData(stream["contract"])

    def borrow_status(self, symbol: str) -> tuple[float | None, float | None] | None:
        """Latest (tier, shortable shares) for a streamed symbol, if seen."""
        return self._borrow.get(symbol)

    # ── news ───────────────────────────────────────────────────────────
    #
    # The one research feed this login is entitled to. Eight providers
    # (Briefing.com and Dow Jones), thirty days of history, live headlines on
    # generic tick 292 and full article bodies — while every fundamentals
    # request on the same connection answers error 10358.

    def on_news(self, handler: NewsHandler) -> None:
        """Register for live headlines. Called once, at wiring time."""
        self._news_handlers.append(handler)

    async def fetch_news_providers(self) -> list[tuple[str, str]]:
        """(code, name) for every feed this login can read, cached per run."""
        if self._news_providers is not None:
            return self._news_providers
        if not self.is_available:
            return []
        try:
            providers = await self._ib.reqNewsProvidersAsync()
        except Exception as exc:
            logger.warning("IBKR news providers unavailable: %s", exc)
            return []
        self._news_providers = [(entry.code, entry.name) for entry in providers]
        return self._news_providers

    async def fetch_historical_news(self, symbol: str, days: int, limit: int) -> list[dict]:
        """Recent headlines for a symbol, from every entitled provider.

        ``reqHistoricalNews`` wants the provider codes joined with ``+`` and
        answers nothing at all for an empty list, so a login with no news
        subscription returns early rather than making a request that cannot
        succeed.
        """
        providers = await self.fetch_news_providers()
        if not providers or not self.is_available:
            return []
        contract = await self._contract(symbol)
        if contract is None:
            return []

        codes = "+".join(code for code, _ in providers)
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        try:
            if self._budget is not None:
                await self._budget.acquire()
            rows = await self._ib.reqHistoricalNewsAsync(
                contract.conId,
                providerCodes=codes,
                startDateTime=start.strftime("%Y-%m-%d %H:%M:%S"),
                endDateTime=end.strftime("%Y-%m-%d %H:%M:%S"),
                totalResults=limit,
            )
        except Exception as exc:
            logger.warning("IBKR historical news failed for %s: %s", symbol, exc)
            return []
        return [_news_row(row) for row in rows or []]

    async def fetch_news_article(self, provider_code: str, article_id: str) -> str:
        """The article body, as the HTML fragment the wire sends."""
        if not self.is_available:
            return ""
        try:
            article = await self._ib.reqNewsArticleAsync(provider_code, article_id)
        except Exception as exc:
            logger.warning("IBKR article %s/%s failed: %s", provider_code, article_id, exc)
            return ""
        return article.articleText or ""

    def _on_news_tick(self, news_tick) -> None:
        """A live headline from tick 292.

        Attribution is the awkward part. ``NewsTick`` carries no contract —
        ib_async's wrapper receives the request id and drops it — so the only
        thing on the wire tying a headline to a company is the trailing
        ``>CELU`` marker. Failing that, a single streamed symbol is
        unambiguous: the headline arrived on that line and there is nowhere
        else it could belong. With several symbols streaming and no marker the
        headline is dropped rather than guessed onto the wrong chart; the
        thirty-day backfill picks it up on the next panel load.
        """
        headline = getattr(news_tick, "headline", "") or ""
        symbol = self._news_symbol(headline)
        if symbol is None:
            return
        row = {
            "article_id": getattr(news_tick, "articleId", "") or "",
            "provider": getattr(news_tick, "providerCode", "") or "",
            "headline": headline,
            "time": _news_epoch(getattr(news_tick, "timeStamp", None)),
        }
        for handler in self._news_handlers:
            self._schedule(handler(symbol, row))

    def _news_symbol(self, headline: str) -> str | None:
        if not headline:
            return None
        marked = extract_tickers(headline)
        for ticker in marked:
            if ticker in self._symbols:
                return ticker
        if not marked and len(self._symbols) == 1:
            return next(iter(self._symbols))
        return None

    def _on_quote(self, symbol: str, ticker) -> None:
        # Borrow reads ride the same line but are not gated on a valid book —
        # tick 236 lands whether or not the BBO is populated yet.
        tier = _clean(getattr(ticker, "shortable", None))
        shares = _clean(getattr(ticker, "shortableShares", None))
        if tier is not None or shares is not None:
            self._borrow[symbol] = (tier, shares)

        # IBKR's halted magnitude: -1 unknown, 0 trading, 1 general halt,
        # 2 volatility halt. Emitted only on a change of state.
        halted_raw = _clean(getattr(ticker, "halted", None))
        if halted_raw is not None and halted_raw >= 0:
            is_halted = halted_raw >= 1
            if self._halt_state.get(symbol) != is_halted:
                self._halt_state[symbol] = is_halted
                self._schedule(self._emit_halt(symbol, is_halted))

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
            special = str(getattr(tick, "specialConditions", "") or "").strip()
            kind = classify_conditions(special)
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
                    Trade(
                        time=epoch,
                        price=price,
                        size=size,
                        price_forming=price_forming,
                        # IBKR names the venue ("NASDAQ", "ARCA", "FINRA")
                        # where Alpaca sends one CTA character. Neither is
                        # translated; the tape shows what the source said.
                        exchange=str(getattr(tick, "exchange", "") or ""),
                        # One string of single characters, unlike Alpaca's list.
                        conditions=tuple(special) if special else (),
                    ),
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

    def on_scanner(self, scanner_id: str, handler: ScannerHandler) -> None:
        self._scanner_handlers.setdefault(scanner_id, []).append(handler)

    async def start_scanner(self, scanner_id: str, config: ScannerConfig) -> bool:
        if not self.is_available or self._scanner_subscription_cls is None:
            return False

        await self.stop_scanner(scanner_id)
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
        # Trades per minute. IBKR honours this natively — measured on a live
        # scan, >=500 cut ten rows to two and >=5000 to none — but like
        # changePercAbove it rides the generic filter list rather than a
        # subscription field, so rows are re-checked in _process_scanner.
        if config.above_trade_rate is not None:
            filter_options.append(_tag_value("tradeRateAbove", str(config.above_trade_rate)))

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
            self._scanner_last_emit[scanner_id] = 0.0
            data = self._ib.reqScannerSubscription(subscription, **kwargs)
            callback = functools.partial(self._on_scanner_update, scanner_id)
            data.updateEvent += callback
            self._scanner_data[scanner_id] = data
            self._scanner_update_cbs[scanner_id] = callback
        except Exception as exc:
            logger.warning("IBKR scanner[%s] failed to start: %s", scanner_id, exc)
            self._scanner_data.pop(scanner_id, None)
            return False
        self._scanner_config[scanner_id] = config
        self._scanner_started_at[scanner_id] = time.monotonic()
        task = self._scanner_refresh_tasks.get(scanner_id)
        if task is None or task.done():
            self._scanner_refresh_tasks[scanner_id] = asyncio.create_task(
                self._scanner_refresh_loop(scanner_id)
            )

        logger.info(
            "IBKR scanner[%s] subscribed: %s (price %s-%s, trades/min>%s, mcap %s-%s, "
            "chg>%s, %d rows) "
            "— waiting on first results",
            scanner_id,
            config.scan_code,
            config.above_price,
            config.below_price,
            config.above_trade_rate,
            config.market_cap_above,
            config.market_cap_below,
            config.change_perc_above,
            config.number_of_rows,
        )
        return True

    async def stop_scanner(self, scanner_id: str) -> None:
        task = self._scanner_refresh_tasks.pop(scanner_id, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        data = self._scanner_data.pop(scanner_id, None)
        callback = self._scanner_update_cbs.pop(scanner_id, None)
        if data is not None:
            with contextlib.suppress(Exception):
                if callback is not None:
                    data.updateEvent -= callback
                self._ib.cancelScannerSubscription(data)
        self._scanner_raw.pop(scanner_id, None)
        owned = [
            symbol
            for symbol, stream in self._scanner_streams.items()
            if scanner_id in stream["owners"]
        ]
        for symbol in owned:
            self._release_scanner_stream(scanner_id, symbol)

    def _on_scanner_update(self, scanner_id: str, rows) -> None:
        # IBKR pushes a fresh ranking only every ~30 seconds. The membership
        # is remembered here; emission is throttled, and the refresh loop
        # re-reads the live tickers in between so the columns never wait for
        # the next ranking to fill in.
        self._scanner_raw[scanner_id] = list(rows)
        now = time.monotonic()
        last_emit = self._scanner_last_emit.get(scanner_id, 0.0)
        if now - last_emit < self._scanner_settings.min_refresh_seconds:
            return
        self._scanner_last_emit[scanner_id] = now
        self._schedule(self._process_scanner(scanner_id, self._scanner_raw[scanner_id]))

    async def _scanner_refresh_loop(self, scanner_id: str) -> None:
        """Re-read the per-row tickers between IBKR's ranking pushes.

        The scan decides membership roughly twice a minute; prices, rates
        and the trade-rate sort live on the market-data lines, which stream
        continuously. Without this loop the columns of a fresh scan sit
        blank until the *next* ranking arrives.
        """
        interval = self._scanner_settings.min_refresh_seconds
        while True:
            await asyncio.sleep(interval)
            raw = self._scanner_raw.get(scanner_id)
            if not raw or scanner_id not in self._scanner_data:
                continue
            now = time.monotonic()
            if now - self._scanner_last_emit.get(scanner_id, 0.0) < interval:
                continue
            self._scanner_last_emit[scanner_id] = now
            try:
                await self._process_scanner(scanner_id, raw)
            except Exception:
                logger.exception("scanner[%s] refresh failed", scanner_id)

    async def _process_scanner(self, scanner_id: str, raw_rows: list) -> None:
        self._sync_scanner_streams(scanner_id, raw_rows)
        now = time.time()
        rows: list[ScannerRow] = []
        seen: set[str] = set()
        config = self._scanner_config.get(scanner_id)
        threshold = config.change_perc_above if config else None
        rate_floor = config.above_trade_rate if config else None

        for entry in raw_rows:
            contract = entry.contractDetails.contract
            symbol = contract.symbol
            # A scan can return one symbol under two contracts. Everything
            # downstream is keyed per symbol — the stream table above, the
            # rank-velocity map, the frontend's table rows — and both entries
            # read the same ticker anyway, so the second is the same row at a
            # worse rank. Emitting it doubled symbols on the scanner panel.
            if symbol in seen:
                continue
            seen.add(symbol)
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
            if threshold is not None and pct_change is not None and pct_change < threshold:
                continue

            # And the trade rate, for the same reason. Only when a rate has
            # actually arrived: it comes on ticks 294/295 a moment after the
            # row does, and treating "not yet known" as "too slow" would empty
            # the panel for the first seconds of every subscription.
            if rate_floor is not None and trade_rate is not None and trade_rate < rate_floor:
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

        started_at = self._scanner_started_at.get(scanner_id)
        if started_at is not None:
            elapsed = time.monotonic() - started_at
            self._scanner_started_at[scanner_id] = None
            logger.info(
                "IBKR scanner[%s] first results: %d rows, %.1fs after subscribe",
                scanner_id,
                len(rows),
                elapsed,
            )

        for handler in self._scanner_handlers.get(scanner_id, []):
            try:
                await handler(rows)
            except Exception:
                logger.exception("scanner[%s] handler failed", scanner_id)

    def _sync_scanner_streams(self, scanner_id: str, raw_rows: list) -> None:
        """One market data line per visible row, shared across every tier
        that currently wants the symbol (see the module comment by
        ScannerHandler for why streams aren't one-per-tier).

        Rows that survive a refresh keep their trade buffer — that continuity
        is the whole point of a sliding window.
        """
        wanted = {
            entry.contractDetails.contract.symbol: entry.contractDetails.contract
            for entry in raw_rows
        }

        owned = [
            symbol
            for symbol, stream in self._scanner_streams.items()
            if scanner_id in stream["owners"] and symbol not in wanted
        ]
        for symbol in owned:
            self._release_scanner_stream(scanner_id, symbol)

        for symbol, contract in wanted.items():
            stream = self._scanner_streams.get(symbol)
            if stream is not None:
                stream["owners"].add(scanner_id)
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
                "owners": {scanner_id},
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

    def _release_scanner_stream(self, scanner_id: str, symbol: str) -> None:
        """Drop one tier's claim on a symbol's market-data line.

        Only actually cancels once every owning tier has let go — the
        refcounting that keeps a symbol straddling two tiers' market-cap
        bands from each fighting the other over reqMktData/cancelMktData on
        the same contract.
        """
        stream = self._scanner_streams.get(symbol)
        if stream is None:
            return
        stream["owners"].discard(scanner_id)
        if stream["owners"]:
            return
        del self._scanner_streams[symbol]
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


def _news_row(row) -> dict:
    """One ``reqHistoricalNews`` result, flattened for the news service."""
    return {
        "article_id": getattr(row, "articleId", "") or "",
        "provider": getattr(row, "providerCode", "") or "",
        "headline": getattr(row, "headline", "") or "",
        "time": _news_epoch(getattr(row, "time", None)),
    }


def _news_epoch(value: object) -> int:
    """Epoch seconds from whatever the news path hands over.

    Historical news carries a ``datetime``; the live 292 tick carries epoch
    milliseconds as a string. Both arrive here, and a headline with no usable
    time sorts to the bottom rather than to 1970 in the middle of the list.
    """
    if isinstance(value, datetime):
        stamped = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(stamped.timestamp())
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    # Milliseconds if it is far past any plausible epoch-seconds timestamp.
    return number // 1000 if number > 10_000_000_000 else number
