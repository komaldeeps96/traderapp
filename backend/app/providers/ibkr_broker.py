"""Order entry through IBKR — the one part of this app that spends money.

**A second TWS connection, on its own client id.** The market-data provider
next door is ``readonly=True`` and that is a safety property worth keeping;
it is also the client that runs four scanner subscriptions, tick-by-tick
streams and pacing-limited history through a reconnect loop, so it is the one
that goes down and comes back. Order flow does not belong on it. This client
does almost nothing — one contract qualification per symbol, an order now and
then, three event subscriptions — so it stays connected, and a history storm
next door cannot disturb order state. IBKR allows 32 concurrent API clients.

**It never connects with ``trading.enabled`` false**, which is the default and
is set explicitly in every test settings object, the same way
``alpaca.news_stream`` is.

Two things about IBKR that are not obvious and cost real money to rediscover:

- **``readonly`` is a TWS checkbox, not a library argument.** ``ib_async``'s
  ``readonly=`` only skips the client's own open-order fetch (``ib.py:2057``).
  What actually rejects orders is Global Configuration → API → Settings →
  "Read-Only API". With that ticked, everything here fails at the last step.
  ``read_only_note`` is what the panel shows when TWS says so.
- **Orders are visible per client id.** This client sees the orders it placed
  and nobody else's, so an order entered by hand in TWS does not appear here
  and — importantly — is not something ``cancel_all`` can reach. Binding
  manual orders would mean ``clientId 0`` (``ib.py:2046``), which would also
  put every manual order within reach of this app's cancel button. Positions
  are account-wide and always visible, which is why the position this panel
  sells from is IBKR's number and never our own fill arithmetic.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable

from ..core.settings import TradingSettings

logger = logging.getLogger(__name__)

# Positions fan out as "something changed"; the container reads the whole
# list back off the broker. A list of a few names costs less to send than a
# diff costs to reason about — the same call the watchlist makes.
PositionHandler = Callable[[], Awaitable[None]]
OrderHandler = Callable[[dict], Awaitable[None]]
StatusHandler = Callable[[], Awaitable[None]]

# TWS error codes that mean "this connection may not trade". 2148 is the
# read-only rejection; 10147/10148 are order-not-found on a cancel race,
# which is noise rather than a fault.
READ_ONLY_CODES = frozenset({2148})
CANCEL_RACE_CODES = frozenset({10147, 10148})

# Codes TWS sends as connection notices rather than faults. They arrive on
# errorEvent all the same and must not reach the panel as rejections.
INFO_CODES = frozenset({1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2109, 2168, 2169})


def _import_ib():
    try:
        from ib_async import IB, LimitOrder, Stock  # noqa: PLC0415

        return IB, Stock, LimitOrder
    except ImportError:  # pragma: no cover - exercised only without the extra
        return None


class IBKRBroker:
    """Places orders, and reports positions and order state as they change."""

    def __init__(self, settings: TradingSettings):
        self._settings = settings
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
        # ib_async Trade objects for orders this client placed, by order id.
        self._trades: dict[int, object] = {}
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
            with contextlib.suppress(Exception):
                self._detach()
            self._ib.disconnect()
        self._contracts.clear()
        self._trades.clear()

    @property
    def is_available(self) -> bool:
        """Connected **and** set up — both, deliberately.

        ``ib_async`` marks the socket connected partway through
        ``connectAsync``, while it is still fetching positions and orders. That
        leaves a window — measured at ~300ms against live TWS — in which
        ``isConnected()`` is True but our event handlers are not attached, the
        account has not resolved, and no position snapshot has arrived.

        An order sent in that window would go out with no account and, worse,
        with nothing listening for its fills; and the strip would draw FLAT on
        an account that is long. The window opens exactly when TWS comes back
        mid-session, which is precisely when somebody hits a sell button. So
        the panel is told "not connected" until the setup has actually run.
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

        Not knowable at connect time — TWS accepts the connection either way
        and only objects when an order arrives — so this latches on the first
        rejection and the panel explains what to untick.
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
        delay = 1.0
        while self._should_run:
            if self.socket_connected:
                # Connected but not set up: connectAsync was interrupted after
                # the handshake. Finish the job rather than idling on a
                # half-built connection that reports itself unavailable
                # forever.
                if not self._ready:
                    self._finish_setup()
                    await self._emit_status()
                await asyncio.sleep(1.0)
                continue

            attempt += 1
            async with self._connect_lock:
                if self.socket_connected:
                    continue
                try:
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
                except Exception as exc:
                    delay = min(2 ** min(attempt, 5), self._settings.max_reconnect_delay_seconds)
                    logger.info("Broker unavailable (%s); retrying in %ss", exc, int(delay))
                else:
                    attempt = 0
                    self._finish_setup()
                    await self._emit_status()
                    continue
            await asyncio.sleep(delay)

    def _finish_setup(self) -> None:
        """Resolve the account, attach the handlers, adopt the positions.

        Idempotent, and the only thing that sets ``_ready``: the connect loop
        calls it both on a clean connect and on finding a socket that came up
        without it.
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
        # connectAsync may have been interrupted after some of these were
        # added; ib_async's Event is a list, so re-adding would double every
        # callback. Detach first, ignoring what was never there.
        with contextlib.suppress(Exception):
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
        readonly flag (``ib.py:2056``), so the opening snapshot is already
        paid for by the time this runs.
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
        self._positions[symbol] = int(size)
        self._avg_cost[symbol] = avg_cost
        return symbol

    def position(self, symbol: str) -> int:
        """Shares held long. Negative for a short, which this app never opens
        but the account may hold from elsewhere."""
        return self._positions.get(symbol.upper(), 0)

    def positions(self) -> list[dict]:
        """Every non-flat stock position, for the rail under the buttons."""
        return [
            {
                "symbol": symbol,
                "shares": shares,
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

        No sizing and no price arithmetic happens here — this takes a plan
        that ``services/trading.py`` has already checked against the cap and
        against the position, and puts it on the wire.
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
            orderRef="traderapp",
        )
        try:
            trade = self._ib.placeOrder(contract, order)
        except Exception as exc:
            logger.exception("placeOrder failed for %s", symbol)
            return {"ok": False, "message": str(exc)}

        order_id = int(trade.order.orderId)
        self._trades[order_id] = trade
        logger.warning(
            "ORDER SENT %s %s x%s limit %s (id %s)", side, symbol, shares, limit, order_id
        )
        self._schedule(self._emit_order(trade))
        return {"ok": True, **self._order_wire(trade)}

    async def cancel_all(self) -> int:
        """Cancel every order this client has working. Returns how many.

        Only this client's orders — an order entered by hand in TWS is on a
        different client id and is deliberately out of reach. See the module
        docstring.
        """
        if not self.is_available:
            return 0
        cancelled = 0
        for trade in list(self._ib.openTrades()):
            if getattr(trade.order, "orderRef", "") != "traderapp":
                continue
            with contextlib.suppress(Exception):
                self._ib.cancelOrder(trade.order)
                cancelled += 1
        if cancelled:
            logger.warning("CANCEL ALL — %s working order(s)", cancelled)
        return cancelled

    def working_orders(self) -> list[dict]:
        if not self.is_available:
            return []
        return [
            self._order_wire(trade)
            for trade in self._ib.openTrades()
            if getattr(trade.order, "orderRef", "") == "traderapp"
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

    def _on_execution(self, trade, _fill) -> None:
        self._schedule(self._emit_order(trade))

    def _on_error(self, req_id, code, message, _contract) -> None:
        """TWS's error channel, which also carries connection notices.

        A rejection has to reach the strip: during a move nobody is reading a
        log, and an order that silently did not go is the failure this whole
        panel is built to avoid.
        """
        if code in INFO_CODES or code in CANCEL_RACE_CODES:
            return
        if code in READ_ONLY_CODES:
            self._read_only = True
            self._last_error = (
                "TWS is in read-only mode. Untick Global Configuration → "
                "API → Settings → Read-Only API."
            )
        else:
            self._last_error = f"IBKR {code}: {message}"
        logger.warning("Broker error %s: %s (req %s)", code, message, req_id)
        self._schedule(self._emit_status())

    def clear_error(self) -> None:
        self._last_error = None

    # ── fan-out ────────────────────────────────────────────────────────

    async def _emit_positions(self) -> None:
        for handler in list(self._position_handlers):
            with contextlib.suppress(Exception):
                await handler()

    async def _emit_order(self, trade) -> None:
        wire = self._order_wire(trade)
        for handler in list(self._order_handlers):
            with contextlib.suppress(Exception):
                await handler(wire)

    async def _emit_status(self) -> None:
        for handler in list(self._status_handlers):
            with contextlib.suppress(Exception):
                await handler()
