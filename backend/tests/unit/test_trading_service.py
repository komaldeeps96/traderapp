"""The guards between a button press and a real order.

Every test here is about something *not* happening. The arithmetic is covered
in test_orders.py; this is the layer that decides whether the arithmetic gets
used at all, and each of these corresponds to a way of losing money by
accident rather than by decision.
"""

from __future__ import annotations

import asyncio

from app.core.settings import TradingSettings
from app.domain.quotes import Quote
from app.services.quotes import QuoteService
from app.services.trading import TradingService


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeBroker:
    """The broker's surface, without a socket.

    Records what it was asked to send, so a test can assert on the *quantity
    and price that reached the wire* rather than on the plan that preceded
    them — the plan being right and the order being wrong is the failure that
    matters here.
    """

    def __init__(self, *, connected: bool = True, positions: dict[str, int] | None = None):
        self.is_available = connected
        self.account = "DU1234"
        self.read_only = False
        self.last_error: str | None = None
        self.positions_known = True
        self._positions = positions or {}
        self.committed: dict[str, int] = {}
        self.sent: list[dict] = []
        self.cancelled = 0
        self.fail_with: str | None = None
        self.on_place = None

    def position(self, symbol: str) -> int:
        return self._positions.get(symbol.upper(), 0)

    def committed_to_sells(self, symbol: str) -> int:
        return self.committed.get(symbol.upper(), 0)

    def positions(self) -> list[dict]:
        return [{"symbol": s, "shares": n} for s, n in self._positions.items() if n]

    def working_orders(self) -> list[dict]:
        return []

    def clear_error(self) -> None:
        self.last_error = None

    async def place(self, *, symbol, side, shares, limit):
        if self.on_place is not None:
            await self.on_place()
        if self.fail_with:
            return {"ok": False, "message": self.fail_with}
        order = {"symbol": symbol, "side": side, "shares": shares, "limit": limit}
        self.sent.append(order)
        if side == "SELL":
            # Working, or filled and not yet reported as a position change:
            # either way the real broker counts these shares as claimed.
            self.committed[symbol] = self.committed.get(symbol, 0) + shares
        return {"ok": True, "order_id": len(self.sent), **order}

    async def cancel_all(self) -> int:
        self.cancelled += 1
        return 2


def quote(bid: float, ask: float, time: float = 0.0) -> Quote:
    return Quote(bid=bid, ask=ask, bid_size=10, ask_size=10, time=time)


def build(
    *,
    enabled: bool = True,
    connected: bool = True,
    positions: dict[str, int] | None = None,
    bid_ask: tuple[float, float] | None = (4.25, 4.27),
    clock: FakeClock | None = None,
    feed_delayed: bool = False,
    feed_live: bool = True,
    halted: bool = False,
    quote_age: float = 0.0,
    **overrides,
) -> tuple[TradingService, FakeBroker]:
    broker = FakeBroker(connected=connected, positions=positions)
    quotes = QuoteService()
    if bid_ask is not None:
        quotes._latest["WETO"] = quote(*bid_ask, time=-quote_age)
    settings = TradingSettings(enabled=enabled, **overrides)
    service = TradingService(
        broker,
        quotes,
        settings,
        clock=clock or FakeClock(),
        feed_delayed=lambda: feed_delayed,
        feed_live=lambda: feed_live,
        halted=lambda _symbol: halted,
        wall_clock=lambda: 0.0,
    )
    return service, broker


def hold_placement(broker: FakeBroker) -> tuple[asyncio.Event, asyncio.Event]:
    """Make the next placement wait: returns (started, release)."""
    started, release = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        started.set()
        await release.wait()

    broker.on_place = hold
    return started, release


# ── the switch ─────────────────────────────────────────────────────────


async def test_nothing_is_sent_while_trading_is_disabled() -> None:
    """The master switch, which is off by default and off in every test
    settings object. It is checked here as well as in the broker, because two
    independent refusals is the point of a switch that guards real money."""
    service, broker = build(enabled=False)
    result = await service.buy("WETO", 25)
    assert result == {"ok": False, "message": "Trading is disabled."}
    assert broker.sent == []


async def test_nothing_is_sent_while_tws_is_down() -> None:
    service, broker = build(connected=False)
    result = await service.buy("WETO", 25)
    assert not result["ok"]
    assert "not connected" in result["message"]
    assert broker.sent == []


# ── the cap ────────────────────────────────────────────────────────────


async def test_an_amount_over_the_cap_is_refused_for_what_it_asked_for() -> None:
    """Checked before sizing as well as after. A button configured larger than
    the ceiling should be refused for the amount it asked for, not silently
    accepted because it happened to round down to something affordable."""
    service, broker = build(max_order_dollars=60)
    result = await service.buy("WETO", 500)
    assert not result["ok"]
    assert "cap" in result["message"]
    assert broker.sent == []


async def test_the_cap_also_catches_a_plan_that_grows_past_it_at_the_limit() -> None:
    """Six shares of a $10.00 ask is $60.00, which fits — but the order goes
    out at the $10.05 limit, which does not. The ceiling bounds the worst
    case, so five go."""
    service, broker = build(bid_ask=(9.99, 10.00), max_order_dollars=60)
    assert (await service.buy("WETO", 60))["ok"]
    assert broker.sent[0]["shares"] * broker.sent[0]["limit"] <= 60


# ── long only ──────────────────────────────────────────────────────────


async def test_selling_flat_sends_nothing() -> None:
    service, broker = build(positions={})
    result = await service.sell("WETO", 1.0)
    assert not result["ok"]
    assert broker.sent == []


async def test_a_sell_never_exceeds_the_position_ibkr_reports() -> None:
    """The property that makes a short impossible. Not a disabled button — a
    rule, enforced on the quantity that reaches the wire."""
    service, broker = build(positions={"WETO": 14})
    await service.sell("WETO", 1.0)
    assert broker.sent[-1]["shares"] == 14
    assert broker.sent[-1]["side"] == "SELL"


async def test_two_alls_in_a_row_cannot_open_a_short() -> None:
    """IBKR's position only falls once the fill is reported, so the first ALL's
    shares have to stay claimed until then. A second ALL, outside the repeat
    window, finds nothing left to sell."""
    clock = FakeClock()
    service, broker = build(positions={"WETO": 100}, clock=clock)
    assert (await service.sell("WETO", 1.0))["ok"]
    clock.advance(5)
    second = await service.sell("WETO", 1.0)
    assert not second["ok"]
    assert "working sell" in second["message"]
    assert [order["shares"] for order in broker.sent] == [100]


async def test_a_sell_takes_its_fraction_of_the_unclaimed_shares() -> None:
    service, broker = build(positions={"WETO": 14})
    broker.committed["WETO"] = 4
    await service.sell("WETO", 0.5)
    assert broker.sent[-1]["shares"] == 5


async def test_a_short_position_is_not_covered_by_the_sell_buttons() -> None:
    """An account short from elsewhere is not something these buttons act on:
    selling into it would deepen the short, and buying it back is not what a
    percentage-of-position button means."""
    service, broker = build(positions={"WETO": -40})
    result = await service.sell("WETO", 0.5)
    assert not result["ok"]
    assert broker.sent == []


async def test_a_fraction_that_floors_to_nothing_sends_nothing() -> None:
    service, broker = build(positions={"WETO": 3})
    result = await service.sell("WETO", 0.25)
    assert not result["ok"]
    assert broker.sent == []


# ── the double-click ───────────────────────────────────────────────────


async def test_a_double_click_sends_one_order_not_two() -> None:
    """The most likely way to spend $100 on a $50 button. TWS acknowledges in
    milliseconds, so by the second click the first order is already placed;
    the second is refused for arriving inside the repeat window."""
    service, broker = build()
    first = await service.buy("WETO", 25)
    second = await service.buy("WETO", 25)
    assert first["ok"]
    assert not second["ok"]
    assert "double-click" in second["message"]
    assert len(broker.sent) == 1


async def test_a_second_decision_after_the_window_is_placed() -> None:
    clock = FakeClock()
    service, broker = build(clock=clock)
    await service.buy("WETO", 25)
    clock.advance(1.01)
    assert (await service.buy("WETO", 25))["ok"]
    assert len(broker.sent) == 2


async def test_the_window_is_per_side() -> None:
    """Selling straight after buying is a decision, not a double-click."""
    service, broker = build(positions={"WETO": 14})
    await service.buy("WETO", 25)
    assert (await service.sell("WETO", 0.5))["ok"]
    assert [order["side"] for order in broker.sent] == ["BUY", "SELL"]


async def test_the_window_is_per_symbol() -> None:
    service, _ = build()
    service._quotes._latest["AAPL"] = quote(20.0, 20.01)
    await service.buy("WETO", 25)
    assert (await service.buy("AAPL", 25))["ok"]


async def test_a_refused_order_does_not_start_the_window() -> None:
    """Retrying a rejected order at once is exactly what a user should be able to do."""
    service, broker = build()
    broker.fail_with = "rejected"
    assert not (await service.buy("WETO", 25))["ok"]
    broker.fail_with = None
    assert (await service.buy("WETO", 25))["ok"]


async def test_a_zero_window_switches_the_guard_off() -> None:
    service, broker = build(repeat_guard_seconds=0)
    await service.buy("WETO", 25)
    await service.buy("WETO", 25)
    assert len(broker.sent) == 2


async def test_a_second_window_cannot_slip_in_while_the_first_is_being_placed() -> None:
    """Qualifying a contract awaits the network, so another window's order can
    arrive before the first has even reached TWS."""
    service, broker = build()
    started, release = hold_placement(broker)
    first = asyncio.create_task(service.buy("WETO", 25))
    await started.wait()
    second = await service.buy("WETO", 25)
    release.set()

    assert (await first)["ok"]
    assert not second["ok"]
    assert "in flight" in second["message"]
    assert len(broker.sent) == 1


async def test_the_in_flight_guard_releases_after_a_broker_failure() -> None:
    """A raising broker must not wedge a symbol shut for the session — which
    would mean being unable to sell a position you are in."""
    service, broker = build(positions={"WETO": 14})
    broker.fail_with = "boom"
    assert not (await service.sell("WETO", 1.0))["ok"]
    broker.fail_with = None
    assert (await service.sell("WETO", 1.0))["ok"]


async def test_the_in_flight_guard_is_per_symbol_not_global() -> None:
    """Being unable to exit AAPL because a WETO order is in flight would be a
    guard that costs more than it saves."""
    service, broker = build(positions={"WETO": 14, "AAPL": 5})
    service._quotes._latest["AAPL"] = quote(200.0, 200.1)
    started, release = hold_placement(broker)
    held = asyncio.create_task(service.sell("WETO", 1.0))
    await started.wait()
    # Only the WETO order is held open; the AAPL one must go straight through.
    broker.on_place = None
    other = await service.sell("AAPL", 1.0)
    release.set()
    await held
    assert other["ok"]


# ── what actually reaches the wire ─────────────────────────────────────


async def test_the_quantity_is_recomputed_here_from_the_freshest_quote() -> None:
    """The client sends dollars and never a share count. This is the whole
    reason: the quote that sizes the order is the one held at the moment of
    the click, not one a sleeping tab remembered."""
    clock = FakeClock()
    service, broker = build(bid_ask=(4.25, 4.27), clock=clock)
    await service.buy("WETO", 25)
    assert broker.sent[-1] == {"symbol": "WETO", "side": "BUY", "shares": 5, "limit": 4.32}

    await service._quotes.handle_quote("WETO", Quote(bid=8.50, ask=8.55, bid_size=1, ask_size=1, time=1))
    clock.advance(2)
    await service.buy("WETO", 25)
    assert broker.sent[-1] == {"symbol": "WETO", "side": "BUY", "shares": 2, "limit": 8.60}


async def test_an_order_on_the_delayed_feed_is_refused() -> None:
    """With IBKR's data gone and Alpaca on delayed_sip, the book is fifteen
    minutes old: a marketable limit priced off it rests or fills far off."""
    service, broker = build(feed_delayed=True, positions={"WETO": 14})
    assert "delayed" in (await service.buy("WETO", 25))["message"]
    assert "delayed" in (await service.sell("WETO", 1.0))["message"]
    assert broker.sent == []


async def test_an_order_without_a_quote_is_refused_rather_than_priced_at_zero() -> None:
    service, broker = build(bid_ask=None)
    result = await service.buy("WETO", 25)
    assert not result["ok"]
    assert broker.sent == []


# ── the refusal note ───────────────────────────────────────────────────


async def test_a_refusal_is_left_on_the_state_the_strip_draws() -> None:
    """During a move nobody is reading a log. An order that silently did not
    go is the failure this panel exists to remove, so the reason sits on the
    strip until the next action."""
    service, _ = build(positions={})
    await service.sell("WETO", 1.0)
    assert service.state()["note"] == "No position to sell."


async def test_a_successful_order_clears_the_previous_refusal() -> None:
    service, _ = build(positions={"WETO": 14})
    await service.sell("WETO", 0.25 / 100)  # floors to nothing
    assert service.state()["note"] is not None
    await service.sell("WETO", 1.0)
    assert service.state()["note"] is None


async def test_cancel_all_reaches_the_broker_and_clears_the_note() -> None:
    service, broker = build()
    result = await service.cancel_all()
    assert result == {"ok": True, "cancelled": 2}
    assert broker.cancelled == 1


async def test_cancel_all_is_refused_while_trading_is_disabled() -> None:
    service, broker = build(enabled=False)
    assert not (await service.cancel_all())["ok"]
    assert broker.cancelled == 0


# ── the state the strip draws ──────────────────────────────────────────


def test_the_state_says_live_or_paper_from_the_port() -> None:
    live, _ = build(port=7496)
    paper, _ = build(port=7497)
    assert live.state()["paper"] is False
    assert paper.state()["paper"] is True


def test_the_state_carries_the_button_configuration() -> None:
    """The panel draws whatever buttons the settings define rather than three
    hard-coded ones, so changing the amounts is a config change."""
    service, _ = build(buy_dollars=[5, 20], sell_fractions=[0.5, 1.0])
    state = service.state()
    assert state["buy_dollars"] == [5, 20]
    assert state["sell_fractions"] == [0.5, 1.0]


def test_the_state_carries_the_repeat_window_the_strip_mirrors() -> None:
    service, _ = build(repeat_guard_seconds=0.75)
    assert service.state()["repeat_guard_seconds"] == 0.75


# ── what the browser also checks, held here too ────────────────────────


async def test_a_dead_market_data_feed_refuses_the_order() -> None:
    service, broker = build(feed_live=False)
    result = await service.buy("WETO", 25)
    assert not result["ok"]
    assert broker.sent == []


async def test_a_halted_symbol_refuses_both_sides() -> None:
    """A marketable limit placed into a halt rests there and fills at the reopen."""
    service, broker = build(halted=True, positions={"WETO": 14})
    assert not (await service.buy("WETO", 25))["ok"]
    assert not (await service.sell("WETO", 1.0))["ok"]
    assert broker.sent == []


async def test_a_quote_that_stopped_moving_refuses_the_order() -> None:
    """A SELL ALL priced off the last bid before a feed froze rests above the market."""
    service, broker = build(quote_age=60.0, positions={"WETO": 14})
    result = await service.sell("WETO", 1.0)
    assert not result["ok"]
    assert "60s old" in result["message"]
    assert broker.sent == []


async def test_buying_past_the_position_cap_is_refused() -> None:
    """$25 at a 4.32 limit is 5 shares: 66 held makes 71 x 4.32 = $306.72."""
    service, broker = build(positions={"WETO": 66}, max_position_dollars=300)
    result = await service.buy("WETO", 25)
    assert "position cap" in result["message"]
    assert broker.sent == []


async def test_buying_up_to_the_position_cap_goes_through() -> None:
    service, broker = build(positions={"WETO": 60}, max_position_dollars=300)
    assert (await service.buy("WETO", 25))["ok"]
    assert broker.sent[0]["shares"] == 5
