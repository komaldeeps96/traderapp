"""Alpaca market data: REST for history, WebSocket for live trades and bars.

Talks to the HTTP and WebSocket APIs directly rather than through
``alpaca-py``. That keeps the dependency list short and, more usefully, makes
every request interceptable in tests — the whole provider is exercised against
recorded responses with no network and no credentials.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx
from websockets.asyncio.client import connect as ws_connect

from ..core.clock import parse_rfc3339, rfc3339
from ..core.settings import AlpacaSettings
from ..domain.bars import Bar
from ..domain.quotes import Quote
from ..domain.timeframes import Timeframe
from ..market.bar_builder import Trade, build_bars
from ..market.conditions import TradeKind, classify_conditions
from .base import MarketDataProvider, ProviderError

logger = logging.getLogger(__name__)

# Alpaca's timeframe vocabulary for the bars endpoint.
_TIMEFRAME_PARAM = {
    Timeframe.M1: "1Min",
    Timeframe.M5: "5Min",
    Timeframe.M15: "15Min",
    Timeframe.H1: "1Hour",
    Timeframe.D1: "1Day",
    Timeframe.W1: "1Week",
}

# Free plans cannot query SIP data inside this window.
DELAYED_WINDOW = timedelta(minutes=15, seconds=30)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class AlpacaProvider(MarketDataProvider):
    name = "alpaca"

    def __init__(self, settings: AlpacaSettings, budget=None):
        super().__init__()
        self._settings = settings
        # ProviderBudget from services.api_budget; optional so tests and
        # scripts can run the provider bare.
        self._budget = budget
        self._client: httpx.AsyncClient | None = None
        self._stream_task: asyncio.Task | None = None
        self._symbols: set[str] = set()
        self._connected = False
        self._closing = False
        self._ws = None
        self._lock = asyncio.Lock()

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        if not self._settings.enabled:
            logger.warning("Alpaca credentials missing; provider disabled")
            return
        self._closing = False
        self._client = httpx.AsyncClient(
            base_url=self._settings.data_url,
            timeout=self._settings.timeout_seconds,
            headers={
                "APCA-API-KEY-ID": self._settings.key_id,
                "APCA-API-SECRET-KEY": self._settings.secret_key,
                "Accept": "application/json",
            },
        )

    async def stop(self) -> None:
        self._closing = True
        if self._stream_task:
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream_task
            self._stream_task = None
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False

    @property
    def is_available(self) -> bool:
        return self._settings.enabled

    @property
    def is_delayed(self) -> bool:
        return self._settings.is_delayed

    @property
    def is_streaming(self) -> bool:
        return self._connected

    # ── history ────────────────────────────────────────────────────────

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        if not self._client:
            raise ProviderError("Alpaca provider not started")

        # Alpaca's bars endpoint bottoms out at one minute; 10-second bars are
        # rebuilt from the raw trade tape instead.
        if timeframe is Timeframe.S10:
            return await self._fetch_tensec(symbol, start, end)

        feed, end = self._resolve_feed_window(end)
        params = {
            "symbols": symbol,
            "timeframe": _TIMEFRAME_PARAM[timeframe],
            "start": rfc3339(start),
            "end": rfc3339(end),
            "limit": self._settings.page_limit,
            # Split-adjusted on every timeframe, so daily key levels stay on
            # the same price scale as the intraday bars they are drawn over.
            "adjustment": "split",
            "feed": feed,
            # Newest-first, one request, no pagination: a single 10k page is
            # days of minute bars and years of dailies, and each extra page
            # is a slot off the request budget for no charting benefit.
            "sort": "desc",
        }

        payload = await self._get("/v2/stocks/bars", params)
        bars = [_parse_bar(raw) for raw in (payload.get("bars") or {}).get(symbol, []) or []]
        bars.reverse()

        logger.info("Alpaca: %s %s -> %d bars", symbol, timeframe.value, len(bars))
        return bars

    async def _fetch_tensec(self, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        """Rebuild 10-second bars from the trade tape.

        Pages are walked newest-first so that when the page cap truncates a
        very heavy tape, what survives is the most recent window — the part a
        10-second chart is actually for. The oldest bar is dropped on
        truncation because its opening trades are missing.
        """
        feed, end = self._resolve_feed_window(end)
        params = {
            "symbols": symbol,
            "start": rfc3339(start),
            "end": rfc3339(end),
            "limit": self._settings.page_limit,
            "feed": feed,
            "sort": "desc",
        }

        trades: list[Trade] = []
        page_token: str | None = None
        truncated = False
        for _page in range(self._settings.max_trade_pages):
            if page_token:
                params["page_token"] = page_token
            payload = await self._get("/v2/stocks/trades", params)
            for raw in (payload.get("trades") or {}).get(symbol, []) or []:
                trade = _parse_trade(symbol, raw)
                if trade is not None:
                    trades.append(trade)
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        else:
            truncated = True

        bars = build_bars(trades, Timeframe.S10)
        if truncated and bars:
            bars = bars[1:]
        logger.info(
            "Alpaca: %s 10s -> %d bars from %d trades%s",
            symbol,
            len(bars),
            len(trades),
            " (truncated)" if truncated else "",
        )
        return bars

    def _resolve_feed_window(self, end: datetime) -> tuple[str, datetime]:
        """Pick the REST feed and clamp the window for delayed entitlements.

        ``delayed_sip`` is a streaming feed name; the bars endpoint takes
        ``sip`` and simply refuses the most recent 15 minutes. Clamping the
        end of the window ourselves turns that refusal into a successful,
        slightly older response.
        """
        feed = self._settings.feed
        if feed == "delayed_sip":
            latest = datetime.now(UTC) - DELAYED_WINDOW
            return "sip", min(end, latest)
        return feed, end

    async def _get(self, path: str, params: dict) -> dict:
        assert self._client is not None
        last_error: Exception | None = None

        for attempt in range(3):
            # Every attempt is a real request against the 200/min allowance.
            if self._budget is not None:
                await self._budget.acquire()
            try:
                response = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            if response.status_code in _RETRYABLE_STATUS:
                last_error = ProviderError(f"Alpaca {response.status_code} on {path}")
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            if response.status_code >= 400:
                raise ProviderError(
                    f"Alpaca {response.status_code} on {path}: {response.text[:300]}"
                )
            return response.json()

        raise ProviderError(f"Alpaca request failed after retries: {last_error}")

    # ── streaming ──────────────────────────────────────────────────────

    async def set_stream_symbols(self, symbols: set[str]) -> None:
        if not self._settings.enabled:
            return

        async with self._lock:
            if symbols == self._symbols:
                return
            added = symbols - self._symbols
            removed = self._symbols - symbols
            self._symbols = set(symbols)

            if not symbols:
                await self._send({"action": "unsubscribe", **_channels(removed)})
                return

            if self._stream_task is None or self._stream_task.done():
                self._stream_task = asyncio.create_task(self._stream_loop())
                return

            if removed:
                await self._send({"action": "unsubscribe", **_channels(removed)})
            if added:
                await self._send({"action": "subscribe", **_channels(added)})

    async def _send(self, payload: dict) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(payload))
        except Exception:
            logger.debug("Alpaca stream send failed", exc_info=True)

    async def _stream_loop(self) -> None:
        """Maintain the market data socket, reconnecting with backoff."""
        url = f"{self._settings.stream_url}/v2/{self._settings.feed}"
        attempt = 0

        while not self._closing:
            try:
                async with ws_connect(url, max_size=4 * 1024 * 1024) as websocket:
                    self._ws = websocket
                    await self._authenticate(websocket)
                    attempt = 0
                    self._connected = True
                    await self._emit_status()

                    if self._symbols:
                        await self._send({"action": "subscribe", **_channels(self._symbols)})

                    async for raw in websocket:
                        await self._handle_frame(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._closing:
                    break
                attempt += 1
                delay = min(2 ** min(attempt, 5), 30)
                logger.warning("Alpaca stream dropped (%s); retrying in %ss", exc, delay)
            finally:
                self._ws = None
                if self._connected:
                    self._connected = False
                    await self._emit_status()

            if self._closing:
                break
            await asyncio.sleep(min(2 ** min(attempt, 5), 30))

    async def _authenticate(self, websocket) -> None:
        await websocket.send(
            json.dumps(
                {
                    "action": "auth",
                    "key": self._settings.key_id,
                    "secret": self._settings.secret_key,
                }
            )
        )
        # The server greets, then answers the auth; read until one or the other
        # resolves so a slow greeting is not mistaken for a failure.
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            for message in _decode(raw):
                kind = message.get("T")
                if kind == "success" and message.get("msg") == "authenticated":
                    logger.info("Alpaca stream authenticated (%s)", self._settings.feed)
                    return
                if kind == "error":
                    raise ProviderError(
                        f"Alpaca stream auth failed: {message.get('msg')} "
                        f"(code {message.get('code')})"
                    )
        raise ProviderError("Alpaca stream auth timed out")

    async def _handle_frame(self, raw: str | bytes) -> None:
        for message in _decode(raw):
            kind = message.get("T")
            if kind == "t":
                trade = _parse_trade(message.get("S", ""), message)
                if trade is not None and trade.time > 0:
                    await self._emit_trade(message["S"], trade)
            elif kind == "q" and "S" in message:
                stamp = message.get("t")
                await self._emit_quote(
                    message["S"],
                    Quote(
                        bid=float(message.get("bp", 0)),
                        ask=float(message.get("ap", 0)),
                        # Alpaca quote sizes are round lots; the wire carries
                        # shares so IBKR and Alpaca read the same on screen.
                        bid_size=float(message.get("bs", 0)) * 100,
                        ask_size=float(message.get("as", 0)) * 100,
                        time=parse_rfc3339(stamp).timestamp() if stamp else time.time(),
                    ),
                )
            elif kind == "b":
                await self._emit_bar(message["S"], Timeframe.M1, _parse_bar(message))
            elif kind == "error":
                logger.error(
                    "Alpaca stream error %s: %s", message.get("code"), message.get("msg")
                )
            elif kind == "subscription":
                logger.info(
                    "Alpaca subscription: trades=%s bars=%s",
                    message.get("trades"),
                    message.get("bars"),
                )


def _channels(symbols: set[str]) -> dict[str, list[str]]:
    """Subscribe to trades, quotes and bars.

    Trades drive the in-progress bar tick by tick; the minute bar that follows
    carries consolidated volume and replaces our running total, so the chart
    is both live and eventually exact. Quotes feed the bid/ask/spread readout.
    """
    listed = sorted(symbols)
    return {"trades": listed, "quotes": listed, "bars": listed}


def _decode(raw: str | bytes) -> list[dict]:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.debug("Alpaca sent undecodable frame")
        return []
    if isinstance(payload, dict):
        return [payload]
    return [item for item in payload if isinstance(item, dict)]


def _parse_trade(symbol: str, raw: dict) -> Trade | None:
    """One tape print, with its sale conditions applied.

    Administrative reprints are dropped; late/average-price/odd-lot prints
    keep their volume but are barred from moving OHLC.
    """
    if not symbol or "p" not in raw:
        return None
    kind = classify_conditions(raw.get("c"))
    if kind is TradeKind.SKIP:
        return None
    stamp = raw.get("t")
    return Trade(
        time=parse_rfc3339(stamp).timestamp() if stamp else 0.0,
        price=float(raw["p"]),
        size=float(raw.get("s", 0)),
        price_forming=kind is TradeKind.PRICE_FORMING,
    )


def _parse_bar(raw: dict) -> Bar:
    return Bar(
        time=int(parse_rfc3339(raw["t"]).timestamp()),
        open=float(raw["o"]),
        high=float(raw["h"]),
        low=float(raw["l"]),
        close=float(raw["c"]),
        volume=float(raw.get("v", 0.0)),
        trades=float(raw.get("n", 0.0)),
    )
