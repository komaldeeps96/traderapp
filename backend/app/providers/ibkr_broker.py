"""Order entry through IBKR — the one part of this app that spends money.

**A second TWS connection, on its own client id.** The market-data client next
door is ``readonly=True`` and runs scanners, tick-by-tick streams and
pacing-limited history through a reconnect loop, so it is the one that drops
and returns. This client does almost nothing, so it stays connected and a
history storm next door cannot disturb order state. IBKR allows 32 clients.

**It never connects with ``trading.enabled`` false**, the default, set
explicitly in every test settings object like ``alpaca.news_stream``.

Two IBKR behaviours that cost real money to rediscover:

- **``readonly`` is a TWS checkbox, not a library argument.** ``ib_async``'s
  ``readonly=`` only skips the client's own open-order fetch (``ib.py:2057``).
  Global Configuration → API → Settings → "Read-Only API" is what rejects
  orders; ``read_only_note`` is what the panel shows when TWS says so.
- **Orders are visible per client id.** This client sees only the orders it
  placed, so an order entered by hand in TWS is out of ``cancel_all``'s reach.
  Binding manual orders would mean ``clientId 0`` (``ib.py:2046``), putting
  every manual order within reach of this app's cancel button. Positions are
  account-wide, which is why the position sold from is IBKR's number and never
  our own fill arithmetic.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..core.settings import TradingSettings

logger = logging.getLogger(__name__)

# Positions fan out as "something changed"; the container reads the whole
# list back off the broker. A list of a few names costs less to send than a
# diff costs to reason about — the same call the watchlist makes.
PositionHandler = Callable[[], Awaitable[None]]
OrderHandler = Callable[[dict], Awaitable[None]]
StatusHandler = Callable[[], Awaitable[None]]

# Tags every order this app places, so its own can be told from anything else.
ORDER_REF = "traderapp"

# TWS answers an order on a read-only API with 321, its generic "error
# validating request", so the message is what identifies it.
VALIDATION_ERROR = 321
# Order-not-found on a cancel race: noise rather than a fault.
CANCEL_RACE_CODES = frozenset({10147, 10148})
# TWS's own numbering: 1100-1102 are connectivity notices, and warnings run
# from 2100 (2100-2169 in the v9.72 table; 2174 and 2176 arrived later). Both
# arrive on errorEvent and reject nothing.
CONNECTION_NOTICES = frozenset({1100, 1101, 1102})
WARNINGS = range(2100, 2200)
# "Order Canceled" — also TWS's answer to a cancel this client asked for.
ORDER_CANCELLED = 202

# How long a sell fill may wait for IBKR's position report before it stops
# counting against what can be sold. TWS sends both within a second; the bound
# only stops a report that arrives out of order from pinning shares for good.
UNREPORTED_FILL_SECONDS = 10.0


def _import_ib():
    try:
        from ib_async import IB, LimitOrder, Stock  # noqa: PLC0415

        return IB, Stock, LimitOrder
    except ImportError:  # pragma: no cover - exercised only without the extra
        return None


@dataclass(slots=True)
class _UnreportedFill:
    at: float
    shares: int


class IBKRBroker:
    """Places orders, and reports positions and order state as they change."""

    def __init__(self, settings: TradingSettings, clock: Callable[[], float] = time.monotonic):
        self._settings = settings
        self._clock = clock
        self._ib = None
        self._stock = None
        self._limit_order = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._should_run = False
        self._connect_lock = asyncio.Lock()
        self._contracts: dict[str, object] = {}
        self._pending: set[asyncio.Task] = set()

        self._account: str = settings.account
        # Positions as IBKR reports them, per symbol. The panel sells from
        # this and never from our own fills: the account can be traded from
        # TWS at the same time as from here.
        self._positions: dict[str, int] = {}
        self._avg_cost: dict[str, float] = {}
        self._unrealized: dict[str, float] = {}
        # Whether a position snapshot has arrived at all. A sell button must
        # not read "no position" merely because the first push has not landed.
        self._positions_known = False
        # Sell fills not yet folded into a position report, oldest first.
        self._unreported_sells: dict[str, list[_UnreportedFill]] = {}
        self._seen_executions: set[str] = set()
        # Orders cancel_all asked TWS to cancel; their 202 is an answer, not a fault.
        self._cancelling: set[int] = set()
        self._last_error: str | None = None
        self._read_only = False
        # Set only once the handlers are attached, the account has resolved
        # and the opening position snapshot is in. See is_available.
        self._ready = False

        self._position_handlers: list[PositionHandler] = []
        self._order_handlers: list[OrderHandler] = []
        self._status_handlers: list[StatusHandler] = []

    # ── handlers ───────────────────────────────────────────────────────

    def on_position(self, handler: PositionHandler) -> None:
        self._position_handlers.append(handler)

    def on_order(self, handler: OrderHandler) -> None:
        self._order_handlers.append(handler)

    def on_status_change(self, handler: StatusHandler) -> None:
        self._status_handlers.append(handler)

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        if not self._settings.enabled:
            logger.info("Trading disabled by configuration; no broker connection")
            return

        imported = _import_ib()
        if imported is None:  # pragma: no cover - exercised only without the extra
            logger.warning("Trading enabled but 'ib-async' is not installed; no order entry")
            return

        ib_cls, self._stock, self._limit_order = imported
        self._ib = ib_cls()
        self._loop = asyncio.get_running_loop()
        self._should_run = True
        self._reconnect_task = asyncio.create_task(self._connect_loop())
        logger.warning(
            "ORDER ENTRY ARMED — %s:%s (%s), cap $%s per order",
            self._settings.host,
            self._settings.port,
            "paper" if self._settings.is_paper else "LIVE",
            self._settings.max_order_dollars,
        )

    async def stop(self) -> None:
        self._should_run = False
        self._ready = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None
        if self._ib is not None and self._ib.isConnected():
            self._detach()
            self._ib.disconnect()
        self._contracts.clear()
        self._unreported_sells.clear()
        self._cancelling.clear()

    @property
    def is_available(self) -> bool:
        """Connected **and** set up — both, deliberately.

        ``ib_async`` marks the socket connected partway through
        ``connectAsync``, while it is still fetching positions and orders — a
        ~300ms window in which ``isConnected()`` is True but handlers are not
        attached, the account has not resolved and no position has arrived.

        An order sent then goes out with no account and nothing listening for
        its fills, and the strip draws FLAT on an account that is long. The
        window opens exactly when TWS comes back mid-session.
        """
        return bool(self._ib is not None and self._ib.isConnected() and self._ready)

    @property
    def socket_connected(self) -> bool:
        """The raw socket state, without the setup. Only the connect loop
        should care: everything else wants ``is_available``."""
        return bool(self._ib is not None and self._ib.isConnected())

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    @property
    def account(self) -> str:
        return self._account

    @property
    def read_only(self) -> bool:
        """True once TWS has rejected an order for its read-only setting.

        Not knowable at connect time: TWS accepts the connection either way and
        only objects when an order arrives, so this latches on the first
        rejection.
        """
        return self._read_only

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def positions_known(self) -> bool:
        return self._positions_known

    async def _connect_loop(self) -> None:
        attempt = 0
        while self._should_run:
            if self.is_available:
                await asyncio.sleep(1.0)
                continue

            attempt += 1
            async with self._connect_lock:
                try:
                    if not self.socket_connected:
                        await asyncio.wait_for(
                            self._ib.connectAsync(
                                self._settings.host,
                                self._settings.port,
                                clientId=self._settings.client_id,
                                account=self._settings.account,
                                # The order path. See the module docstring: what
                                # actually enforces read-only is TWS's own
                                # checkbox, not this argument.
                                readonly=False,
                            ),
                            timeout=self._settings.connect_timeout_seconds,
                        )
                    self._finish_setup()
                except Exception as exc:
                    # A socket that connected but did not set up reports itself
                    # unavailable for good, so it is dropped and built again.
                    if self.socket_connected:
                        self._ib.disconnect()
                    delay = min(2 ** min(attempt, 5), self._settings.max_reconnect_delay_seconds)
                    logger.info("Broker unavailable (%s); retrying in %.1fs", exc, delay)
                else:
                    attempt = 0
                    await self._emit_status()
                    continue
            await asyncio.sleep(delay)

    def _finish_setup(self) -> None:
        """Resolve the account, attach the handlers, adopt the positions.

        Idempotent, and the only thing that sets ``_ready``.
        """
        if self._ready:
            return
        if not self._account:
            accounts = self._ib.managedAccounts()
            self._account = accounts[0] if len(accounts) == 1 else ""
        self._attach()
        self._seed_positions()
        self._ready = True
        logger.info(
            "Broker ready (%s:%s, account %s)",
            self._settings.host,
            self._settings.port,
            self._account or "?",
        )

    def _attach(self) -> None:
        ib = self._ib
        # A setup that failed partway may have added some of these, and
        # eventkit runs a listener once per add. Detaching a listener that was
        # never attached is a no-op there.
        self._detach()
        ib.disconnectedEvent += self._on_disconnected
        ib.orderStatusEvent += self._on_order_status
        ib.execDetailsEvent += self._on_execution
        ib.positionEvent += self._on_position
        ib.updatePortfolioEvent += self._on_portfolio
        ib.errorEvent += self._on_error

    def _detach(self) -> None:
        ib = self._ib
        ib.disconnectedEvent -= self._on_disconnected
        ib.orderStatusEvent -= self._on_order_status
        ib.execDetailsEvent -= self._on_execution
        ib.positionEvent -= self._on_position
        ib.updatePortfolioEvent -= self._on_portfolio
        ib.errorEvent -= self._on_error

    def _on_disconnected(self) -> None:
        logger.warning("Broker connection lost; order entry is unavailable")
        self._ready = False
        # Deliberately NOT cleared: the positions are still open at IBKR, and
        # blanking them here would draw a flat account on a dropped socket.
        # They are marked stale by is_available being False instead.
        self._schedule(self._emit_status())

    def _seed_positions(self) -> None:
        """Adopt whatever ib_async already collected on connect.

        ``reqPositionsAsync`` runs inside ``connectAsync`` regardless of the
        readonly flag (``ib.py:2056``), so the opening snapshot is already paid
        for.
        """
        for position in self._ib.positions(self._account or ""):
            self._absorb_position(position.contract, position.position, position.avgCost)
        self._positions_known = True
        self._schedule(self._emit_positions())

    def _schedule(self, coro) -> None:
        """Run a coroutine on the main loop from any thread."""
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

    # ── positions ──────────────────────────────────────────────────────

    def _absorb_position(self, contract, size: float, avg_cost: float) -> str | None:
        symbol = getattr(contract, "symbol", None)
        if not symbol or getattr(contract, "secType", "STK") != "STK":
            return None
        symbol = symbol.upper()
        # IBKR reports position as a float because some products are
        # fractional. Ours never are; truncating toward zero keeps a short
        # negative and a long long.
        shares = int(size)
        previous = self._positions.get(symbol)
        self._positions[symbol] = shares
        self._avg_cost[symbol] = avg_cost
        if previous is not None and shares < previous:
            self._settle_sells(symbol, previous - shares)
        return symbol

    def position(self, symbol: str) -> int:
        """Shares held long. Negative for a short, which this app never opens
        but the account may hold from elsewhere."""
        return self._positions.get(symbol.upper(), 0)

    def committed_to_sells(self, symbol: str) -> int:
        """Shares of the position this client's sells have already claimed.

        The unfilled remainder of working sells, plus fills IBKR has not yet
        folded into the position it reports. Without the second, a sell that
        filled a moment ago still reads as held and a second ALL opens a short.
        """
        symbol = symbol.upper()
        working = sum(
            max(0, int(trade.order.totalQuantity) - int(trade.orderStatus.filled))
            for trade in self._our_trades()
            if trade.order.action == "SELL" and str(trade.contract.symbol).upper() == symbol
        )
        return working + self._unreported(symbol)

    def _unreported(self, symbol: str) -> int:
        fills = self._unreported_sells.get(symbol)
        if not fills:
            return 0
        cutoff = self._clock() - UNREPORTED_FILL_SECONDS
        fills[:] = [fill for fill in fills if fill.at >= cutoff]
        return sum(fill.shares for fill in fills)

    def _settle_sells(self, symbol: str, shares: int) -> None:
        """A position report that fell by ``shares`` has taken in that many sold."""
        fills = self._unreported_sells.get(symbol, [])
        while fills and shares > 0:
            taken = min(fills[0].shares, shares)
            fills[0].shares -= taken
            shares -= taken
            if fills[0].shares == 0:
                fills.pop(0)

    def positions(self) -> list[dict]:
        """Every non-flat stock position, for the rail under the buttons."""
        return [
            {
                "symbol": symbol,
                "shares": shares,
                "committed": self.committed_to_sells(symbol),
                "avg_cost": round(self._avg_cost.get(symbol, 0.0), 4),
                "unrealized": round(self._unrealized.get(symbol, 0.0), 2),
            }
            for symbol, shares in sorted(self._positions.items())
            if shares
        ]

    def _on_position(self, position) -> None:
        if self._absorb_position(position.contract, position.position, position.avgCost):
            self._schedule(self._emit_positions())

    def _on_portfolio(self, item) -> None:
        """``updatePortfolioEvent`` — position, average cost and unrealised
        P&L together, pushed on every change to any of them."""
        symbol = self._absorb_position(item.contract, item.position, item.averageCost)
        if symbol is None:
            return
        self._unrealized[symbol] = float(getattr(item, "unrealizedPNL", 0.0) or 0.0)
        self._positions_known = True
        self._schedule(self._emit_positions())

    # ── orders ─────────────────────────────────────────────────────────

    async def _contract(self, symbol: str):
        cached = self._contracts.get(symbol)
        if cached is not None:
            return cached
        try:
            contract = self._stock(symbol, "SMART", "USD")
            await self._ib.qualifyContractsAsync(contract)
        except Exception as exc:
            logger.warning("Broker could not qualify %s: %s", symbol, exc)
            return None
        self._contracts[symbol] = contract
        return contract

    async def place(self, *, symbol: str, side: str, shares: int, limit: float) -> dict:
        """Send one marketable limit order. Returns what was sent, or a fault.

        No sizing or price arithmetic here: this puts a plan
        ``services/trading.py`` has already checked against the cap and the
        position on the wire.
        """
        if not self._settings.enabled:
            return {"ok": False, "message": "Trading is disabled."}
        if not self.is_available:
            return {"ok": False, "message": "TWS is not connected."}
        if shares <= 0 or limit <= 0:
            return {"ok": False, "message": "Nothing to send."}

        contract = await self._contract(symbol)
        if contract is None:
            return {"ok": False, "message": f"IBKR does not know {symbol}."}

        order = self._limit_order(
            side,
            shares,
            limit,
            tif=self._settings.tif,
            # Not optional for this workflow: without it a limit order simply
            # sits unfilled outside 09:30-16:00, and small-cap momentum runs
            # pre-market. It is also why these are limits and not markets —
            # TWS refuses market orders outside regular hours.
            outsideRth=self._settings.outside_rth,
            account=self._account or "",
            orderRef=ORDER_REF,
        )
        try:
            trade = self._ib.placeOrder(contract, order)
        except Exception as exc:
            logger.exception("placeOrder failed for %s", symbol)
            return {"ok": False, "message": str(exc)}

        logger.warning(
            "ORDER SENT %s %s x%s limit %s (id %s)",
            side,
            symbol,
            shares,
            limit,
            trade.order.orderId,
        )
        self._schedule(self._emit_order(trade))
        return {"ok": True, **self._order_wire(trade)}

    async def cancel_all(self) -> int:
        """Cancel every order this client has working. Returns how many.

        Only this client's orders; one entered by hand in TWS is on a different
        client id and out of reach. See the module docstring.
        """
        if not self.is_available:
            return 0
        cancelled = 0
        for trade in self._our_trades():
            order_id = int(trade.order.orderId)
            try:
                self._ib.cancelOrder(trade.order)
            except Exception:
                logger.exception("cancelOrder failed for order %s", order_id)
                continue
            self._cancelling.add(order_id)
            cancelled += 1
        if cancelled:
            logger.warning("CANCEL ALL — %s working order(s)", cancelled)
        return cancelled

    def working_orders(self) -> list[dict]:
        if not self.is_available:
            return []
        return [self._order_wire(trade) for trade in self._our_trades()]

    def _our_trades(self) -> list:
        """This app's orders that are still working."""
        if self._ib is None:
            return []
        return [
            trade
            for trade in self._ib.openTrades()
            if getattr(trade.order, "orderRef", "") == ORDER_REF
        ]

    def _order_wire(self, trade) -> dict:
        status = trade.orderStatus
        return {
            "order_id": int(trade.order.orderId),
            "symbol": str(trade.contract.symbol).upper(),
            "side": str(trade.order.action),
            "shares": int(trade.order.totalQuantity),
            "limit": float(trade.order.lmtPrice),
            "status": str(status.status),
            "filled": int(status.filled),
            "avg_fill": round(float(status.avgFillPrice or 0.0), 4),
            "message": str(getattr(trade, "advancedError", "") or "") or None,
            "at": int(time.time()),
        }

    def _on_order_status(self, trade) -> None:
        self._schedule(self._emit_order(trade))

    def _on_execution(self, trade, fill) -> None:
        execution = fill.execution
        if execution.side == "SLD" and execution.execId not in self._seen_executions:
            self._seen_executions.add(execution.execId)
            symbol = str(fill.contract.symbol).upper()
            self._unreported_sells.setdefault(symbol, []).append(
                _UnreportedFill(self._clock(), int(execution.shares))
            )
        self._schedule(self._emit_order(trade))

    def _on_error(self, req_id, code, message, _contract) -> None:
        """TWS's error channel, which also carries connection notices.

        A rejection has to reach the strip: an order that silently did not go is
        the failure this panel is built to avoid.
        """
        if code == VALIDATION_ERROR and "read-only" in str(message).lower():
            self._read_only = True
            self._last_error = (
                "TWS is in read-only mode. Untick Global Configuration → "
                "API → Settings → Read-Only API."
            )
        elif self._is_noise(req_id, code):
            return
        else:
            self._last_error = f"IBKR {code}: {message}"
        logger.warning("Broker error %s: %s (req %s)", code, message, req_id)
        self._schedule(self._emit_status())

    def _is_noise(self, req_id: int, code: int) -> bool:
        """A notice, a warning, or the answer to something this client asked."""
        return (
            code in CONNECTION_NOTICES
            or code in WARNINGS
            or code in CANCEL_RACE_CODES
            or (code == ORDER_CANCELLED and req_id in self._cancelling)
        )

    def clear_error(self) -> None:
        self._last_error = None

    # ── fan-out ────────────────────────────────────────────────────────

    async def _emit_positions(self) -> None:
        await _fan_out(self._position_handlers)

    async def _emit_order(self, trade) -> None:
        await _fan_out(self._order_handlers, self._order_wire(trade))

    async def _emit_status(self) -> None:
        await _fan_out(self._status_handlers)


async def _fan_out(handlers: list, *args) -> None:
    # One failing listener must not starve the rest, nor fail unseen.
    for handler in list(handlers):
        try:
            await handler(*args)
        except Exception:
            logger.exception("Broker listener %r failed", handler)
