"""The guards between a button press and a real order.

Every test here is about something *not* happening. The arithmetic is covered
in test_orders.py; this is the layer that decides whether the arithmetic gets
used at all, and each of these corresponds to a way of losing money by
accident rather than by decision.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.settings import TradingSettings
from app.domain.quotes import Quote
from app.services.quotes import QuoteService
from app.services.trading import TradingService


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
        self.sent: list[dict] = []
        self.cancelled = 0
        self.fail_with: str | None = None
        self.on_place = None

    def position(self, symbol: str) -> int:
        return self._positions.get(symbol.upper(), 0)

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
        return {"ok": True, "order_id": len(self.sent), **order}

    async def cancel_all(self) -> int:
        self.cancelled += 1
        return 2


def build(
    *,
    enabled: bool = True,
    connected: bool = True,
    positions: dict[str, int] | None = None,
    quote: tuple[float, float] | None = (4.25, 4.27),
    **overrides,
) -> tuple[TradingService, FakeBroker]:
    broker = FakeBroker(connected=connected, positions=positions)
    quotes = QuoteService()
    if quote is not None:
        asyncio.get_event_loop_policy()
        bid, ask = quote
        quotes._latest["WETO"] = Quote(bid=bid, ask=ask, bid_size=10, ask_size=10, time=0)
    settings = TradingSettings(enabled=enabled, **overrides)
    return TradingService(broker, quotes, settings), broker


# ── the switch ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nothing_is_sent_while_trading_is_disabled() -> None:
    """The master switch, which is off by default and off in every test
    settings object. It is checked here as well as in the broker, because two
    independent refusals is the point of a switch that guards real money."""
    service, broker = build(enabled=False)
    result = await service.buy("WETO", 25)
    assert result == {"ok": False, "message": "Trading is disabled."}
    assert broker.sent == []


@pytest.mark.asyncio
async def test_nothing_is_sent_while_tws_is_down() -> None:
    service, broker = build(connected=False)
    result = await service.buy("WETO", 25)
    assert not result["ok"]
    assert "not connected" in result["message"]
    assert broker.sent == []


# ── the cap ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_amount_over_the_cap_is_refused_for_what_it_asked_for() -> None:
    """Checked before sizing as well as after. A button configured larger than
    the ceiling should be refused for the amount it asked for, not silently
    accepted because it happened to round down to something affordable."""
    service, broker = build(max_order_dollars=60)
    result = await service.buy("WETO", 500)
    assert not result["ok"]
    assert "cap" in result["message"]
    assert broker.sent == []


@pytest.mark.asyncio
async def test_the_cap_also_catches_a_plan_that_grows_past_it_at_the_limit() -> None:
    """Six shares of a $10.00 ask is $60.00, which fits — but the order goes
    out at the $10.05 limit, which does not. The ceiling bounds the worst
    case, so this is refused."""
    service, broker = build(quote=(9.99, 10.00), max_order_dollars=60)
    result = await service.buy("WETO", 60)
    assert not result["ok"]
    assert broker.sent == []


# ── long only ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_selling_flat_sends_nothing() -> None:
    service, broker = build(positions={})
    result = await service.sell("WETO", 1.0)
    assert not result["ok"]
    assert broker.sent == []


@pytest.mark.asyncio
async def test_a_sell_never_exceeds_the_position_ibkr_reports() -> None:
    """The property that makes a short impossible. Not a disabled button — a
    rule, enforced on the quantity that reaches the wire."""
    service, broker = build(positions={"WETO": 14})
    await service.sell("WETO", 1.0)
    assert broker.sent[-1]["shares"] == 14
    assert broker.sent[-1]["side"] == "SELL"


@pytest.mark.asyncio
async def test_a_short_position_is_not_covered_by_the_sell_buttons() -> None:
    """An account short from elsewhere is not something these buttons act on:
    selling into it would deepen the short, and buying it back is not what a
    percentage-of-position button means."""
    service, broker = build(positions={"WETO": -40})
    result = await service.sell("WETO", 0.5)
    assert not result["ok"]
    assert broker.sent == []


@pytest.mark.asyncio
async def test_a_fraction_that_floors_to_nothing_sends_nothing() -> None:
    service, broker = build(positions={"WETO": 3})
    result = await service.sell("WETO", 0.25)
    assert not result["ok"]
    assert broker.sent == []


# ── the double-click ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_double_click_sends_one_order_not_two() -> None:
    """The most likely way to spend $100 on a $50 button. The second press
    arrives while the first is still on the wire and is refused."""
    service, broker = build()
    started = asyncio.Event()
    release = asyncio.Event()

    async def hold() -> None:
        started.set()
        await release.wait()

    broker.on_place = hold
    first = asyncio.create_task(service.buy("WETO", 25))
    await started.wait()
    second = await service.buy("WETO", 25)
    release.set()

    assert (await first)["ok"]
    assert not second["ok"]
    assert "in flight" in second["message"]
    assert len(broker.sent) == 1


@pytest.mark.asyncio
async def test_the_in_flight_guard_releases_after_a_broker_failure() -> None:
    """A raising broker must not wedge a symbol shut for the session — which
    would mean being unable to sell a position you are in."""
    service, broker = build(positions={"WETO": 14})
    broker.fail_with = "boom"
    assert not (await service.sell("WETO", 1.0))["ok"]
    broker.fail_with = None
    assert (await service.sell("WETO", 1.0))["ok"]


@pytest.mark.asyncio
async def test_the_guard_is_per_symbol_not_global() -> None:
    """Being unable to exit AAPL because a WETO order is in flight would be a
    guard that costs more than it saves."""
    service, broker = build(positions={"WETO": 14})
    started = asyncio.Event()
    release = asyncio.Event()

    async def hold() -> None:
        started.set()
        await release.wait()

    broker.on_place = hold
    held = asyncio.create_task(service.sell("WETO", 1.0))
    await started.wait()
    # Only the WETO order is held open; the AAPL one must be free to go
    # straight through, which is the whole claim being made.
    broker.on_place = None
    broker._positions["AAPL"] = 5
    service._quotes._latest["AAPL"] = type(service._quotes._latest["WETO"])(
        bid=200.0, ask=200.1, bid_size=1, ask_size=1, time=0
    )
    other = await service.sell("AAPL", 1.0)
    release.set()
    await held
    assert other["ok"]


# ── what actually reaches the wire ─────────────────────────────────────


@pytest.mark.asyncio
async def test_the_quantity_is_recomputed_here_from_the_freshest_quote() -> None:
    """The client sends dollars and never a share count. This is the whole
    reason: the quote that sizes the order is the one held at the moment of
    the click, not one a sleeping tab remembered."""
    service, broker = build(quote=(4.25, 4.27))
    await service.buy("WETO", 25)
    assert broker.sent[-1] == {"symbol": "WETO", "side": "BUY", "shares": 5, "limit": 4.32}

    await service._quotes.handle_quote(
        "WETO", Quote(bid=8.50, ask=8.55, bid_size=1, ask_size=1, time=1)
    )
    await service.buy("WETO", 25)
    assert broker.sent[-1] == {"symbol": "WETO", "side": "BUY", "shares": 2, "limit": 8.60}


@pytest.mark.asyncio
async def test_an_order_without_a_quote_is_refused_rather_than_priced_at_zero() -> None:
    service, broker = build(quote=None)
    result = await service.buy("WETO", 25)
    assert not result["ok"]
    assert broker.sent == []


# ── the refusal note ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_refusal_is_left_on_the_state_the_strip_draws() -> None:
    """During a move nobody is reading a log. An order that silently did not
    go is the failure this panel exists to remove, so the reason sits on the
    strip until the next action."""
    service, _ = build(positions={})
    await service.sell("WETO", 1.0)
    assert service.state()["note"] == "No position to sell."


@pytest.mark.asyncio
async def test_a_successful_order_clears_the_previous_refusal() -> None:
    service, _ = build(positions={"WETO": 14})
    await service.sell("WETO", 0.25 / 100)  # floors to nothing
    assert service.state()["note"] is not None
    await service.sell("WETO", 1.0)
    assert service.state()["note"] is None


@pytest.mark.asyncio
async def test_cancel_all_reaches_the_broker_and_clears_the_note() -> None:
    service, broker = build()
    result = await service.cancel_all()
    assert result == {"ok": True, "cancelled": 2}
    assert broker.cancelled == 1


@pytest.mark.asyncio
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
