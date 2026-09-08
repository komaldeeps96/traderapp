"""The broker connection's guards.

Not the order path — that needs TWS — but the states around it, which are
where the expensive mistakes live: reporting a connection that is not yet
usable, double-firing handlers across a reconnect, and letting anything at
all happen while the master switch is off.
"""

from __future__ import annotations

import pytest

from app.core.settings import TradingSettings
from app.providers.ibkr_broker import IBKRBroker


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
        for name in self.EVENTS:
            setattr(self, name, FakeEvent())

    def isConnected(self) -> bool:
        return self._connected

    def managedAccounts(self) -> list[str]:
        return self._accounts

    def positions(self, _account=""):
        return self._positions

    def openTrades(self):
        return []


def build(ib: FakeIB, **overrides) -> IBKRBroker:
    broker = IBKRBroker(TradingSettings(enabled=True, **overrides))
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


def test_several_managed_accounts_leaves_the_account_unset() -> None:
    """Guessing which of several accounts to trade is not a thing to guess.
    IBKR treats a blank account on a multi-account login as an error, which
    is a refusal the user can act on; picking one silently is not."""
    broker = build(FakeIB(accounts=("U1", "U2")))
    broker._finish_setup()
    assert broker.account == ""


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
    broker._on_error(1, 2148, "Order rejected - reason: read only API", None)
    assert broker.read_only is True
    assert "Read-Only API" in broker.last_error


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
