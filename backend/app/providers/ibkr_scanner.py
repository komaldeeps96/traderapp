"""IBKR's market scanners: one subscription per tier, and the per-row trade
metrics behind them. A mixin on IBKRProvider, sharing its connection and its
one market-data line per symbol (market_lines.py)."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable

from ..domain.scanner import ScannerConfig, ScannerRow

logger = logging.getLogger(__name__)

SCANNER_TICKS = frozenset({"233", "293", "294", "295"})
# Per-row scanner metrics are kept over these trailing windows.
TRADE_WINDOW_1M = 60
TRADE_WINDOW_5M = 300
TRADE_BUFFER_MAX_AGE = 360
ScannerHandler = Callable[[list[ScannerRow]], Awaitable[None]]


class IBKRScannerMixin:
    """The scanner half of IBKRProvider; the connection is that class's."""

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

        # Stock type must go through the filter list: `ScannerSubscription`'s
        # `stockTypeFilter` attribute is silently ignored and only `stkTypes`
        # takes effect, which is why the codes are validated on the way in (see
        # ScannerSettings.exclude_stock_types). One tag carrying a
        # comma-separated list — repeating the tag loses all but one.
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
            if callback is not None:
                data.updateEvent -= callback
            try:
                self._ib.cancelScannerSubscription(data)
            except Exception as exc:
                logger.warning("IBKR scanner[%s] cancel failed: %s", scanner_id, exc)
        self._scanner_raw.pop(scanner_id, None)
        owned = [
            symbol
            for symbol, stream in self._scanner_streams.items()
            if scanner_id in stream["owners"]
        ]
        for symbol in owned:
            self._release_scanner_stream(scanner_id, symbol)

    def _drop_scanners(self) -> None:
        """Forget every scan without asking TWS, which let them go with the
        connection. Rows held from before the drop would otherwise keep being
        re-emitted, read as a running scan, and never be restarted."""
        for task in self._scanner_refresh_tasks.values():
            task.cancel()
        self._scanner_refresh_tasks.clear()
        self._scanner_data.clear()
        self._scanner_update_cbs.clear()
        self._scanner_raw.clear()
        self._scanner_streams.clear()

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

        The scan decides membership roughly twice a minute; prices, rates and
        the trade-rate sort stream continuously on the market-data lines.
        Without this loop a fresh scan's columns sit blank until the next
        ranking.
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
        # Queued work can land after the scan stopped or the connection went;
        # it must neither reopen market-data lines nor emit rows for it.
        if scanner_id not in self._scanner_data or not self.is_available:
            return
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
            # downstream is keyed per symbol and both entries read the same
            # ticker, so the second is the same row at a worse rank.
            if symbol in seen:
                continue
            seen.add(symbol)
            stream = self._scanner_streams.get(symbol)
            ticker = self._lines.ticker(symbol) if stream else None

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

            # IBKR's per-minute rates (ticks 294/295) are authoritative and
            # match TWS's Trades/Min. Counting RTVolume prints undercounts on a
            # hot tape — the market-data line conflates trades inside each
            # ~250ms update — so the window count is only the warm-up fallback.
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

        # A default order only; the real ranking needs history this provider
        # does not keep and happens in ScannerService, which re-sorts. So this
        # decides a cold start. ``trades_5m`` is not a tiebreaker: it counts
        # prints off the market-data line, unreliable in both directions.
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
        """One market-data line per visible row, shared with every other tier
        and the chart that want the symbol (see market_lines.py).

        Rows surviving a refresh keep their trade buffer, which is the point of
        a sliding window.
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
            if stream is not None and scanner_id in stream["owners"]:
                continue
            ticker = self._lines.acquire(
                symbol, contract, _scanner_owner(scanner_id), SCANNER_TICKS, self._on_scanner_tick
            )
            if ticker is None:
                continue
            if stream is None:
                stream = self._scanner_streams[symbol] = {"trades": deque(), "owners": set()}
            stream["owners"].add(scanner_id)

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
        """Drop one tier's claim on a symbol. The line itself goes only when
        nothing else — another tier, or the chart — still holds it."""
        stream = self._scanner_streams.get(symbol)
        if stream is None:
            return
        stream["owners"].discard(scanner_id)
        self._lines.release(symbol, _scanner_owner(scanner_id))
        if not stream["owners"]:
            del self._scanner_streams[symbol]


def _scanner_owner(scanner_id: str) -> str:
    return f"scanner:{scanner_id}"


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
