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
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

from ..core.clock import NY_TZ
from ..core.settings import IBKRSettings, ScannerSettings
from ..domain.bars import Bar
from ..domain.news import extract_tickers
from ..domain.quotes import Quote
from ..domain.scanner import ScannerConfig
from ..domain.timeframes import Timeframe
from ..market.bar_builder import Trade
from ..market.conditions import TradeKind, classify_conditions
from ..market.resample import bucket_start
from .base import MarketDataProvider
from .ibkr_scanner import IBKRScannerMixin, ScannerHandler, _clean
from .market_lines import MarketLines

logger = logging.getLogger(__name__)

# "Last" is IBKR's last-sale-eligible slice of the tape; "AllLast" is the whole
# thing. The slice, because IBKR's own bars are built from it and those bars are
# this app's baseline — matching it live keeps 10s and 1m indicators consistent.
# It is also ~5x cheaper in messages.
#
# The cost: odd lots are ~21-26% of shares on a small-cap gapper, so volume, and
# therefore RVOL and float rotation, sit that far below a SIP-based screener.
# app/market/conditions.py holds the Alpaca side of the same decision.
TICK_TYPE = "Last"

# Generic ticks each owner of a symbol's market-data line reads; the line
# carries the union (see market_lines.py). The chart: 236 shortable (borrow
# tier and pool), 292 live news. The scanner: 233 per-trade prints, 293 day
# trade count, 294/295 IBKR's own trade and volume rates per minute.
CHART_TICKS = frozenset({"236", "292"})
CHART_OWNER = "chart"

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


# (symbol, raw headline row) for a live headline off generic tick 292.
NewsHandler = Callable[[str, dict], Awaitable[None]]


class _CancelAckFilter(logging.Filter):
    """Drop TWS's acknowledgement of scanner cancels *we* requested.

    A scanner restart cancels the previous subscription first, and TWS confirms
    with error 162 "API scanner subscription cancelled", which ib_async logs at
    ERROR. That is an ack; every other 162 still logs.
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

    Days stop being the right unit once a window runs to years: TWS rejects a
    duration of fourteen thousand days but accepts the same window in years.
    """
    if span <= 86_400:
        return f"{span} S"
    days = max(1, span // 86_400)
    if days <= 365:
        return f"{days} D"
    return f"{-(-days // 365)} Y"


class IBKRProvider(IBKRScannerMixin, MarketDataProvider):
    name = "ibkr"

    def __init__(self, settings: IBKRSettings, scanner_settings: ScannerSettings, budget=None):
        super().__init__()
        self._settings = settings
        self._scanner_settings = scanner_settings
        # ProviderBudget from core.api_budget covering historical-data
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
        # Last book sent per symbol. The quote line also updates on every trade
        # print, and an unchanged book is not worth a message.
        self._last_quote: dict[str, tuple[float, float, float, float]] = {}
        self._lines = MarketLines(lambda: self._ib)
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
        # Per symbol, not per tier: the trade buffer behind the sliding-window
        # metrics, and which tiers list the symbol. The line itself is in
        # self._lines, shared with the chart.
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
            self._detach()
            if self._ib.isConnected():
                self._ib.disconnect()
        self._contracts.clear()
        self._streams.clear()
        self._lines.reset()
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
                    self._attach()
                    # The router re-routes on this, under its lock; applying the
                    # streams here as well races a ticker switch into two
                    # subscriptions on one Ticker.
                    await self._emit_status()
                    continue
                except Exception as exc:
                    delay = min(2 ** min(attempt, 5), self._settings.max_reconnect_delay_seconds)
                    logger.info(
                        "IBKR unavailable (%s); retrying in %ss", exc, int(delay)
                    )
            await asyncio.sleep(delay)

    def _attach(self) -> None:
        # eventkit runs a listener once per add, and the IB object outlives a
        # reconnect, so each connect detaches before it attaches.
        self._detach()
        self._ib.disconnectedEvent += self._on_disconnected
        # Live headlines arrive on this one event for every subscribed contract
        # at once — see _on_news_tick for why attribution is done from the text.
        self._ib.tickNewsEvent += self._on_news_tick

    def _detach(self) -> None:
        self._ib.disconnectedEvent -= self._on_disconnected
        self._ib.tickNewsEvent -= self._on_news_tick

    def _on_disconnected(self) -> None:
        logger.warning("IBKR connection lost; falling back until it returns")
        self._connected_event.clear()
        # TWS dropped every subscription with the connection, and ib_async its
        # tickers; nothing held for them is valid on the next connect.
        self._streams.clear()
        self._lines.reset()
        self._borrow.clear()
        self._halt_state.clear()
        self._last_quote.clear()
        self._drop_scanners()
        self._schedule(self._emit_status())

    @property
    def is_starting_up(self) -> bool:
        """True while the first connection may still be moments away.

        A server restart races its own history loads against the TWS handshake;
        inside this window, wait a beat for the real-time source rather than
        silently loading delayed data.
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

        Not all ib_async callbacks are guaranteed to arrive on the event loop,
        so this tolerates both cases.
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
            elif isinstance(timestamp, date):
                # Daily and weekly bars come dated, not timed: the session's New
                # York day, anchored where every other source puts that bar.
                midnight = datetime.combine(timestamp, datetime.min.time(), tzinfo=NY_TZ)
                epoch = bucket_start(midnight.timestamp(), timeframe)
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
            # Kept so a cancel can take it off again: ib_async reuses the
            # Ticker when the symbol comes back, and a second add doubles it.
            on_tick = functools.partial(self._on_tick, symbol)
            ticker.updateEvent += on_tick

            # The top-of-book quote, the borrow read and live news ride one
            # ordinary market-data line, shared with the scanner's for the symbol.
            self._lines.acquire(symbol, contract, CHART_OWNER, CHART_TICKS, self._on_quote)

            self._streams[symbol] = {"ticker": ticker, "contract": contract, "on_tick": on_tick}
            logger.info("IBKR streaming %s", symbol)

    def _cancel_stream(self, symbol: str) -> None:
        stream = self._streams.pop(symbol, None)
        self._borrow.pop(symbol, None)
        self._halt_state.pop(symbol, None)
        self._last_quote.pop(symbol, None)
        if not stream:
            return
        stream["ticker"].updateEvent -= stream["on_tick"]
        try:
            self._ib.cancelTickByTickData(stream["contract"], TICK_TYPE)
        except Exception as exc:
            logger.warning("IBKR could not cancel ticks for %s: %s", symbol, exc)
        self._lines.release(symbol, CHART_OWNER)

    def borrow_status(self, symbol: str) -> tuple[float | None, float | None] | None:
        """Latest (tier, shortable shares) for a streamed symbol, if seen."""
        return self._borrow.get(symbol)

    # ── news ───────────────────────────────────────────────────────────
    #
    # The one research feed this login is entitled to: eight providers, thirty
    # days of history, live headlines on generic tick 292 and full bodies.
    # Fundamentals on the same connection answer error 10358.

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

    @property
    def has_history_budget(self) -> bool:
        """Whether a bar request would go now rather than wait for pacing."""
        return self._budget is None or self._budget.used() < self._budget.limit

    async def fetch_historical_news(self, symbol: str, days: int, limit: int) -> list[dict]:
        """Recent headlines for a symbol, from every entitled provider.

        ``reqHistoricalNews`` wants the provider codes joined with ``+`` and
        answers nothing for an empty list, so a login with no news subscription
        returns early.
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
        # Not charged to the budget: it models bar pacing, and headlines spending
        # it starve the chart's first paint.
        try:
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

        ``NewsTick`` carries no contract — ib_async's wrapper receives the
        request id and drops it — so the only thing tying a headline to a
        company is the trailing ``>CELU`` marker. Failing that, a single
        streamed symbol is unambiguous. With several streaming and no marker the
        headline is dropped rather than guessed; the backfill picks it up.
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
        book = (bid, ask, bid_size, ask_size)
        if self._last_quote.get(symbol) == book:
            return
        self._last_quote[symbol] = book
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
            # Defence in depth: IBKR already applied last-sale eligibility on
            # "Last", but running the same rule as the Alpaca stream means a
            # failover cannot change the meaning of a bar. IBKR packs conditions
            # as one string of single characters.
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
                    Trade(
                        time=epoch,
                        price=price,
                        size=size,
                        price_forming=price_forming,
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
        # An unknown or ambiguous symbol comes back unqualified, not raised.
        if not getattr(contract, "conId", 0):
            logger.warning("IBKR could not qualify %s", symbol)
            return None
        self._contracts[symbol] = contract
        return contract

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

    Historical news carries a ``datetime``, the live 292 tick epoch
    milliseconds as a string. A headline with no usable time sorts to the bottom
    rather than to 1970 mid-list.
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
