"""The broker connection's guards.

Not the order path — that needs TWS — but the states around it, which are
where the expensive mistakes live: reporting a connection that is not yet
usable, double-firing handlers across a reconnect, and letting anything at
all happen while the master switch is off.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from types import SimpleNamespace

import pytest

from app.core.settings import TradingSettings
from app.providers.ibkr_broker import UNREPORTED_FILL_SECONDS, IBKRBroker


class FakeEvent:
    """eventkit's Event, to the extent this cares.

    `+=` appends and `-=` removes **every** occurrence, both verified against
    the real one. The comparison is equality, not identity, and that detail is
    the whole reason detach-then-attach works: `self._on_disconnected` is a
    fresh bound-method object on every access, so an identity check would
    never match and every reconnect would double every handler.
    """

    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers = [existing for existing in self.handlers if existing != handler]
        return self


class FakeContract:
    def __init__(self, symbol: str, sec_type: str = "STK"):
        self.symbol = symbol
        self.secType = sec_type


class FakePosition:
    def __init__(self, symbol: str, size: float, avg_cost: float = 0.0, sec_type: str = "STK"):
        self.contract = FakeContract(symbol, sec_type)
        self.position = size
        self.avgCost = avg_cost


class FakeIB:
    EVENTS = (
        "disconnectedEvent",
        "orderStatusEvent",
        "execDetailsEvent",
        "positionEvent",
        "updatePortfolioEvent",
        "errorEvent",
    )

    def __init__(self, *, connected: bool = True, accounts=("U1",), positions=()):
        self._connected = connected
        self._accounts = list(accounts)
        self._positions = list(positions)
        self.trades: list[FakeTrade] = []
        self.cancelled: list[int] = []
        self.disconnects = 0
        for name in self.EVENTS:
            setattr(self, name, FakeEvent())

    def isConnected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self.disconnects += 1
        self._connected = False

    def managedAccounts(self) -> list[str]:
        return self._accounts

    def positions(self, _account=""):
        return self._positions

    def openTrades(self):
        return [trade for trade in self.trades if trade.orderStatus.status not in DONE]

    def cancelOrder(self, order) -> None:
        self.cancelled.append(order.orderId)


# ib_async's OrderStatus.DoneStates.
DONE = frozenset({"Filled", "Cancelled", "ApiCancelled", "Inactive"})


class FakeTrade:
    def __init__(
        self,
        symbol: str,
        action: str,
        quantity: int,
        *,
        filled: int = 0,
        status: str = "Submitted",
        order_id: int = 1,
        ref: str = "traderapp",
    ):
        self.contract = FakeContract(symbol)
        self.order = SimpleNamespace(
            action=action, totalQuantity=quantity, orderId=order_id, orderRef=ref, lmtPrice=1.0
        )
        self.orderStatus = SimpleNamespace(status=status, filled=filled, avgFillPrice=0.0)


def fill(symbol: str, shares: int, *, side: str = "SLD", exec_id: str = "e1"):
    return SimpleNamespace(
        contract=FakeContract(symbol),
        execution=SimpleNamespace(side=side, shares=float(shares), execId=exec_id),
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def build(ib: FakeIB, clock: FakeClock | None = None, **overrides) -> IBKRBroker:
    broker = IBKRBroker(TradingSettings(enabled=True, **overrides), clock=clock or FakeClock())
    broker._ib = ib
    return broker


# ── readiness ──────────────────────────────────────────────────────────


def test_a_connected_socket_is_not_yet_a_usable_broker() -> None:
    """ib_async marks the socket connected partway through connectAsync, while
    it is still fetching positions. An order sent in that window would go out
    with no account and nothing listening for its fills, and the strip would
    draw FLAT on an account that is long — so the panel is told "not
    connected" until the setup has actually run.
    """
    broker = build(FakeIB())
    assert broker.socket_connected is True
    assert broker.is_available is False
    assert broker.positions_known is False


def test_finishing_setup_is_what_makes_it_available() -> None:
    broker = build(FakeIB(positions=[FakePosition("WETO", 14, 4.21)]))
    broker._finish_setup()
    assert broker.is_available is True
    assert broker.account == "U1"
    assert broker.position("WETO") == 14
    assert broker.positions_known is True


def test_a_dropped_connection_stops_it_being_available() -> None:
    ib = FakeIB()
    broker = build(ib)
    broker._finish_setup()
    broker._on_disconnected()
    assert broker.is_available is False
    # Deliberately kept: the positions are still open at IBKR, and blanking
    # them would draw a flat account on a dropped socket.
    ib._connected = False
    assert broker.socket_connected is False


def test_a_reconnect_does_not_double_attach_its_handlers() -> None:
    """Every fill would otherwise be reported twice, and every position event
    applied twice — after exactly the event that makes a reconnect happen."""
    ib = FakeIB()
    broker = build(ib)
    broker._finish_setup()
    broker._on_disconnected()
    broker._ready = False
    broker._finish_setup()
    for name in FakeIB.EVENTS:
        assert len(getattr(ib, name).handlers) == 1, name


def test_setup_is_idempotent() -> None:
    ib = FakeIB()
    broker = build(ib)
    broker._finish_setup()
    broker._finish_setup()
    assert len(ib.orderStatusEvent.handlers) == 1


def test_several_managed_accounts_refuse_to_become_ready() -> None:
    """Which of several accounts to trade is not a thing to guess, and a blank
    account would mix every account's positions under one symbol."""
    broker = build(FakeIB(accounts=("U1", "U2")))
    with pytest.raises(RuntimeError):
        broker._finish_setup()
    assert not broker.is_available
    assert "trading.account" in (broker.last_error or "")


def test_a_configured_account_is_not_overridden() -> None:
    broker = build(FakeIB(accounts=("U1",)), account="U9")
    broker._finish_setup()
    assert broker.account == "U9"


# ── positions ──────────────────────────────────────────────────────────


def test_only_stock_positions_are_adopted() -> None:
    """An option or future on the same underlying is not something these
    buttons can sell, and counting it as shares would size a sell wrongly."""
    broker = build(
        FakeIB(
            positions=[
                FakePosition("WETO", 14, 4.21),
                FakePosition("WETO", 3, 1.10, sec_type="OPT"),
            ]
        )
    )
    broker._finish_setup()
    assert broker.position("WETO") == 14


def test_a_position_is_reported_as_a_whole_number_of_shares() -> None:
    """IBKR reports position as a float because some products are fractional.
    Truncating toward zero keeps a short negative and a long long."""
    ib = FakeIB()
    broker = build(ib)
    broker._finish_setup()
    broker._absorb_position(FakeContract("A"), 14.0, 1.0)
    broker._absorb_position(FakeContract("B"), -40.0, 1.0)
    assert (broker.position("A"), broker.position("B")) == (14, -40)


def test_the_rail_lists_only_names_actually_held() -> None:
    ib = FakeIB()
    broker = build(ib)
    broker._finish_setup()
    broker._absorb_position(FakeContract("HELD"), 14, 4.21)
    broker._absorb_position(FakeContract("CLOSED"), 0, 0.0)
    assert [row["symbol"] for row in broker.positions()] == ["HELD"]


def test_a_symbol_is_matched_case_insensitively() -> None:
    ib = FakeIB()
    broker = build(ib)
    broker._finish_setup()
    broker._absorb_position(FakeContract("weto"), 14, 4.21)
    assert broker.position("WETO") == 14


# ── the switch ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_does_not_connect_while_trading_is_disabled() -> None:
    broker = IBKRBroker(TradingSettings(enabled=False))
    await broker.start()
    assert broker._ib is None
    assert broker.is_available is False
    await broker.stop()


@pytest.mark.asyncio
async def test_place_refuses_while_trading_is_disabled() -> None:
    """A second, independent refusal to the one in TradingService. Two of them
    is the point of a switch that guards real money."""
    broker = IBKRBroker(TradingSettings(enabled=False))
    broker._ib = FakeIB()
    result = await broker.place(symbol="WETO", side="BUY", shares=5, limit=4.32)
    assert result == {"ok": False, "message": "Trading is disabled."}


@pytest.mark.asyncio
async def test_place_refuses_before_the_connection_is_ready() -> None:
    broker = build(FakeIB())
    result = await broker.place(symbol="WETO", side="BUY", shares=5, limit=4.32)
    assert not result["ok"]
    assert "not connected" in result["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("shares", "limit"), [(0, 4.32), (-5, 4.32), (5, 0.0)], ids=[
    "no shares", "negative shares", "no price"
])
async def test_place_sends_nothing_meaningless(shares: int, limit: float) -> None:
    broker = build(FakeIB())
    broker._finish_setup()
    result = await broker.place(symbol="WETO", side="BUY", shares=shares, limit=limit)
    assert not result["ok"]


# ── the read-only checkbox ─────────────────────────────────────────────


def test_a_read_only_rejection_latches_and_explains_the_fix() -> None:
    """The single most likely setup mistake, and invisible from the code side:
    TWS accepts the connection either way and only objects when an order
    arrives, so this cannot be detected until the first one is tried."""
    broker = build(FakeIB())
    broker._finish_setup()
    broker._on_error(
        1,
        321,
        "Error validating request.-'bN' : cause - The API interface is currently in Read-Only mode.",
        None,
    )
    assert broker.read_only is True
    assert "Read-Only API" in broker.last_error


def test_another_validation_error_is_an_ordinary_rejection() -> None:
    """321 is TWS's catch-all for a request it would not validate; only the
    read-only one means the checkbox."""
    broker = build(FakeIB())
    broker._finish_setup()
    broker._on_error(1, 321, "Error validating request.-'cA' : cause - Invalid account", None)
    assert broker.read_only is False
    assert "321" in broker.last_error


def test_connection_notices_are_not_reported_as_rejections() -> None:
    """TWS sends "Market data farm connection is OK" on the error channel.
    A strip that turns red on those would be red all session."""
    broker = build(FakeIB())
    broker._finish_setup()
    for code in (2104, 2106, 2158, 1102):
        broker._on_error(-1, code, "connection is OK", None)
    assert broker.last_error is None


def test_a_cancel_race_is_not_reported_as_a_rejection() -> None:
    """10147 is "order not found" — what a cancel of an order that just filled
    answers. It is a race, not a fault."""
    broker = build(FakeIB())
    broker._finish_setup()
    broker._on_error(1, 10147, "OrderId 3 that needs to be cancelled is not found", None)
    assert broker.last_error is None


def test_a_real_rejection_is_reported_with_its_code() -> None:
    broker = build(FakeIB())
    broker._finish_setup()
    broker._on_error(1, 201, "Order rejected - insufficient funds", None)
    assert "201" in broker.last_error
    assert broker.read_only is False


@pytest.mark.parametrize("code", [2100, 2109, 2119, 2150, 2157, 2174, 2199])
def test_every_tws_warning_is_left_off_the_strip(code: int) -> None:
    """IBKR numbers its warnings 2100-2199. 2109 is "Outside Regular Trading
    Hours is ignored", sent on orders this app places on purpose."""
    broker = build(FakeIB())
    broker._finish_setup()
    broker._on_error(1, code, "a warning", None)
    assert broker.last_error is None


async def test_the_answer_to_our_own_cancel_is_not_a_rejection() -> None:
    ib = FakeIB()
    broker = build(ib)
    broker._finish_setup()
    ib.trades = [FakeTrade("WETO", "BUY", 5, order_id=7)]
    assert await broker.cancel_all() == 1
    broker._on_error(7, 202, "Order Canceled - reason:", None)
    assert broker.last_error is None


def test_a_cancel_nobody_asked_for_is_reported() -> None:
    broker = build(FakeIB())
    broker._finish_setup()
    broker._on_error(9, 202, "Order Canceled - reason: price out of range", None)
    assert "202" in broker.last_error


# ── what a sell may take ───────────────────────────────────────────────


def ready_broker(position: int = 100, clock: FakeClock | None = None) -> tuple[IBKRBroker, FakeIB]:
    ib = FakeIB(positions=[FakePosition("WETO", position, 4.21)])
    broker = build(ib, clock)
    broker._finish_setup()
    return broker, ib


def test_a_working_sell_claims_its_unfilled_shares() -> None:
    broker, ib = ready_broker()
    ib.trades = [FakeTrade("WETO", "SELL", 60, filled=20)]
    assert broker.committed_to_sells("WETO") == 40


def test_buys_other_symbols_and_finished_orders_claim_nothing() -> None:
    broker, ib = ready_broker()
    ib.trades = [
        FakeTrade("WETO", "BUY", 50),
        FakeTrade("AAPL", "SELL", 10),
        FakeTrade("WETO", "SELL", 30, status="Cancelled"),
    ]
    assert broker.committed_to_sells("WETO") == 0


def test_an_order_tws_refused_on_validation_is_not_working() -> None:
    """ib_async leaves a 321 open as ValidationError. Counted, it holds its
    shares as a working sell and ALL refuses until the socket drops."""
    broker, ib = ready_broker()
    ib.trades = [FakeTrade("WETO", "SELL", 100, status="ValidationError")]
    assert broker.committed_to_sells("WETO") == 0
    assert broker.working_orders() == []


def test_a_reconnect_replaces_positions_rather_than_merging_them() -> None:
    """Closed from the phone while disconnected: ib_async omits a flat position,
    so a merge would keep the 14 shares and ALL would open a short."""
    broker, ib = ready_broker(position=14)
    ib._positions = []
    broker._on_disconnected()
    broker._finish_setup()
    assert broker.position("WETO") == 0


def test_another_accounts_position_is_ignored() -> None:
    broker, _ = ready_broker(position=14)
    other = FakePosition("WETO", 500)
    other.account = "U2"
    broker._on_position(other)
    assert broker.position("WETO") == 14


def test_an_accepted_order_clears_the_read_only_latch() -> None:
    broker, _ = ready_broker()
    broker._on_error(1, 321, "The API interface is currently in Read-Only mode.", None)
    assert broker.read_only
    broker._on_order_status(FakeTrade("WETO", "BUY", 1, status="Submitted"))
    assert not broker.read_only


async def test_an_unknown_symbol_is_not_cached_as_a_contract() -> None:
    """ib_async answers an unknown or ambiguous symbol with None, not a raise."""
    broker, ib = ready_broker()
    broker._stock = lambda symbol, _exchange, _currency: FakeContract(symbol)

    async def qualify(*_contracts):
        return [None]

    ib.qualifyContractsAsync = qualify
    assert await broker._contract("ZZZZ") is None
    assert "ZZZZ" not in broker._contracts


def test_an_order_this_app_did_not_place_is_not_counted() -> None:
    broker, ib = ready_broker()
    ib.trades = [FakeTrade("WETO", "SELL", 60, ref="")]
    assert broker.committed_to_sells("WETO") == 0


def test_a_fill_stays_claimed_until_the_position_report_takes_it_in() -> None:
    """The window a second ALL would short through: the order is done, and
    IBKR has not yet said the position fell."""
    broker, _ = ready_broker(100)
    broker._on_execution(FakeTrade("WETO", "SELL", 100, status="Filled"), fill("WETO", 100))
    assert broker.committed_to_sells("WETO") == 100

    broker._absorb_position(FakeContract("WETO"), 0, 0.0)
    assert broker.committed_to_sells("WETO") == 0


def test_a_report_takes_in_only_as_many_shares_as_the_position_fell() -> None:
    broker, _ = ready_broker(100)
    broker._on_execution(FakeTrade("WETO", "SELL", 100, status="Filled"), fill("WETO", 100))
    broker._absorb_position(FakeContract("WETO"), 60, 4.21)
    assert broker.committed_to_sells("WETO") == 60


def test_a_report_that_repeats_the_position_takes_nothing_in() -> None:
    """updatePortfolio and position both report the same number; only a change
    is evidence that a fill has been counted."""
    broker, _ = ready_broker(100)
    broker._on_execution(FakeTrade("WETO", "SELL", 100, status="Filled"), fill("WETO", 100))
    broker._absorb_position(FakeContract("WETO"), 100, 4.21)
    assert broker.committed_to_sells("WETO") == 100


def test_one_execution_reported_twice_counts_once() -> None:
    broker, _ = ready_broker(100)
    trade = FakeTrade("WETO", "SELL", 40, status="Filled")
    broker._on_execution(trade, fill("WETO", 40, exec_id="same"))
    broker._on_execution(trade, fill("WETO", 40, exec_id="same"))
    assert broker.committed_to_sells("WETO") == 40


def test_a_buy_fill_claims_nothing() -> None:
    broker, _ = ready_broker(100)
    broker._on_execution(FakeTrade("WETO", "BUY", 10, status="Filled"), fill("WETO", 10, side="BOT"))
    assert broker.committed_to_sells("WETO") == 0


def test_a_fill_reported_after_its_position_stops_counting_in_time() -> None:
    """The other order of arrival would have the fill claim shares already gone,
    pinning a position bought back later. The bound lets it go."""
    clock = FakeClock()
    broker, _ = ready_broker(100, clock)
    broker._absorb_position(FakeContract("WETO"), 0, 0.0)
    broker._on_execution(FakeTrade("WETO", "SELL", 100, status="Filled"), fill("WETO", 100))
    assert broker.committed_to_sells("WETO") == 100
    clock.now += UNREPORTED_FILL_SECONDS + 1
    assert broker.committed_to_sells("WETO") == 0


def test_the_rail_carries_what_each_position_has_committed() -> None:
    broker, ib = ready_broker(100)
    ib.trades = [FakeTrade("WETO", "SELL", 25)]
    assert broker.positions()[0]["committed"] == 25


# ── fan-out ────────────────────────────────────────────────────────────


async def test_a_failing_listener_is_logged_and_the_rest_still_hear(caplog) -> None:
    broker = build(FakeIB())
    heard: list[bool] = []

    async def broken() -> None:
        raise RuntimeError("listener broke")

    async def fine() -> None:
        heard.append(True)

    broker.on_status_change(broken)
    broker.on_status_change(fine)
    with caplog.at_level(logging.ERROR, logger="app.providers.ibkr_broker"):
        await broker._emit_status()
    assert heard == [True]
    assert "listener broke" in caplog.text


# ── the connect loop ───────────────────────────────────────────────────


async def test_a_setup_that_fails_after_the_handshake_is_torn_down_and_retried() -> None:
    """Connected but not set up reports itself unavailable for good, so the
    socket is dropped and the whole connection built again."""
    ib = FakeIB(connected=False)
    attempts = {"accounts": 0}

    async def connect(*_args, **_kwargs) -> None:
        ib._connected = True

    def accounts() -> list[str]:
        attempts["accounts"] += 1
        if attempts["accounts"] == 1:
            raise RuntimeError("account not resolved yet")
        return ["U1"]

    ib.connectAsync = connect
    ib.managedAccounts = accounts
    broker = build(ib, max_reconnect_delay_seconds=0.01)
    ready = asyncio.Event()

    async def on_status() -> None:
        if broker.is_available:
            ready.set()

    broker.on_status_change(on_status)
    broker._should_run = True
    loop = asyncio.create_task(broker._connect_loop())
    try:
        await asyncio.wait_for(ready.wait(), timeout=5)
    finally:
        broker._should_run = False
        loop.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop
    assert ib.disconnects == 1
    assert broker.account == "U1"
