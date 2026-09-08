"""Order arithmetic, against the shared case table.

The table lives in ``frontend/src/lib/order-cases.json`` and is read by this
suite and by ``frontend/src/lib/orders.test.ts``. The button preview computes
shares locally so the label moves with the spread without a round trip; the
backend recomputes them at the instant of the order because a client that has
been asleep must not be able to send a stale size. That means the arithmetic
exists twice, and this is what keeps the two copies honest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.settings import Settings, TradingSettings
from app.domain.orders import (
    buy_limit,
    offset_micros,
    plan_buy,
    plan_sell,
    sell_limit,
    shares_for_dollars,
    shares_for_fraction,
    tick_micros,
    to_micros,
)

CASES_FILE = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "order-cases.json"
)
CASES = json.loads(CASES_FILE.read_text())
OFFSET = {"offset_cents": CASES["offset"]["cents"], "offset_bps": CASES["offset"]["bps"]}


def _id(case: dict) -> str:
    return case.get("why", "")


# ── the shared table ───────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES["limits"], ids=_id)
def test_limit_prices_match_the_shared_table(case: dict) -> None:
    assert buy_limit(case["ask"], **OFFSET) == pytest.approx(case["buy"])
    assert sell_limit(case["bid"], **OFFSET) == pytest.approx(case["sell"])


@pytest.mark.parametrize("case", CASES["buy_shares"], ids=_id)
def test_buy_sizing_matches_the_shared_table(case: dict) -> None:
    assert shares_for_dollars(case["dollars"], case["ask"]) == case["shares"]


@pytest.mark.parametrize("case", CASES["sell_shares"], ids=_id)
def test_sell_sizing_matches_the_shared_table(case: dict) -> None:
    assert shares_for_fraction(case["position"], case["fraction"]) == case["shares"]


# ── the properties the table cannot express ────────────────────────────


@pytest.mark.parametrize("case", CASES["limits"], ids=_id)
def test_a_limit_is_always_marketable(case: dict) -> None:
    """The whole point: a buy prices at or above the offer, a sell at or below
    the bid. Rounding to *nearest* would break this on one side or the other,
    which is why the module rounds directionally."""
    assert buy_limit(case["ask"], **OFFSET) >= case["ask"]
    assert sell_limit(case["bid"], **OFFSET) <= case["bid"]


@pytest.mark.parametrize("case", CASES["limits"], ids=_id)
def test_a_limit_always_lands_on_a_valid_tick(case: dict) -> None:
    """Off-tick is rejected by TWS, so this is a hard requirement, not a
    nicety. Rule 612: a penny at or above a dollar, a hundredth below."""
    for price in (buy_limit(case["ask"], **OFFSET), sell_limit(case["bid"], **OFFSET)):
        micros = to_micros(price)
        assert micros % tick_micros(micros) == 0, price


@pytest.mark.parametrize("case", CASES["limits"], ids=_id)
def test_a_sell_limit_is_always_positive(case: dict) -> None:
    assert sell_limit(case["bid"], **OFFSET) > 0


@pytest.mark.parametrize("case", CASES["buy_shares"], ids=_id)
def test_a_buy_never_costs_more_than_asked_at_the_ask(case: dict) -> None:
    """Sizing is on the ask, so the expected spend is bounded by the button.
    The offset above it is a cap that is normally not spent — that is a
    separate claim, tested through the cap in plan_buy."""
    shares = shares_for_dollars(case["dollars"], case["ask"])
    if case["ask"] > 0:
        assert shares * case["ask"] <= case["dollars"] + 1e-9


@pytest.mark.parametrize("case", CASES["sell_shares"], ids=_id)
def test_a_sell_never_exceeds_the_position(case: dict) -> None:
    """Long only. This is the property that makes a short impossible, and it
    is enforced in the arithmetic rather than by a disabled button."""
    shares = shares_for_fraction(case["position"], case["fraction"])
    assert 0 <= shares <= max(0, case["position"])


def test_all_closes_the_position_exactly() -> None:
    for position in (1, 3, 7, 14, 99, 101, 1_000_000):
        assert shares_for_fraction(position, 1.0) == position


def test_the_offset_is_the_larger_of_its_two_parts() -> None:
    """Five cents below the crossover, basis points above it. At 5c/15bps the
    two meet at $33.33 — the figure quoted in docs/order-entry.md."""
    assert offset_micros(to_micros(10.00), **OFFSET) == 50_000  # 5c
    assert offset_micros(to_micros(33.33), **OFFSET) == 50_000  # still 5c
    assert offset_micros(to_micros(33.34), **OFFSET) == 50_010  # bps take over
    assert offset_micros(to_micros(100.00), **OFFSET) == 150_000  # 15c


def test_offset_is_monotonic_in_price() -> None:
    previous = 0
    for cents in range(1, 200_00, 137):
        current = offset_micros(cents * 10_000, **OFFSET)
        assert current >= previous
        previous = current


# ── plans ──────────────────────────────────────────────────────────────

PLAN_OFFSET = {**OFFSET, "max_order_dollars": 60.0}


def test_a_buy_plan_carries_the_shares_the_limit_and_the_worst_case_spend() -> None:
    plan = plan_buy(symbol="WETO", dollars=25, bid=4.25, ask=4.27, **PLAN_OFFSET)
    assert plan.ok
    assert (plan.shares, plan.limit) == (5, 4.32)
    # Measured at the limit, not the ask: the cap bounds the worst case.
    assert plan.notional == pytest.approx(21.60)


@pytest.mark.parametrize(
    ("bid", "ask"),
    [(0.0, 0.0), (4.25, 0.0), (0.0, 4.27), (4.30, 4.20)],
    ids=["nothing", "no ask", "no bid", "crossed"],
)
def test_a_buy_without_a_usable_quote_is_blocked(bid: float, ask: float) -> None:
    plan = plan_buy(symbol="WETO", dollars=25, bid=bid, ask=ask, **PLAN_OFFSET)
    assert plan.blocked == "no_quote"
    assert not plan.ok


def test_a_buy_too_small_to_reach_one_share_is_blocked_not_rounded_up() -> None:
    plan = plan_buy(symbol="AAPL", dollars=10, bid=241.0, ask=241.1, **PLAN_OFFSET)
    assert (plan.shares, plan.blocked) == (0, "too_small")


def test_the_cap_stops_an_order_larger_than_the_button_clicked() -> None:
    """The cap exists so no arithmetic fault anywhere in the stack can send an
    order bigger than the one on the button. It is checked at the limit."""
    plan = plan_buy(symbol="WETO", dollars=500, bid=4.25, ask=4.27, **PLAN_OFFSET)
    assert plan.blocked == "over_cap"
    assert not plan.ok


def test_the_cap_is_measured_at_the_limit_not_at_the_ask() -> None:
    """A plan that fits under the cap at the ask but not at the limit is
    refused. Bounding the expected spend rather than the worst case would let
    the offset carry an order past the ceiling."""
    # 6 shares: 6 x 10.00 = 60.00 at the ask, 6 x 10.05 = 60.30 at the limit.
    plan = plan_buy(
        symbol="X", dollars=60, bid=9.99, ask=10.00, offset_cents=5, offset_bps=15,
        max_order_dollars=60.0,
    )
    assert plan.shares == 6
    assert plan.notional == pytest.approx(60.30)
    assert plan.blocked == "over_cap"


def test_a_sell_plan_prices_through_the_bid() -> None:
    plan = plan_sell(symbol="WETO", fraction=0.5, position=14, bid=4.25, ask=4.27, **OFFSET)
    assert plan.ok
    assert (plan.shares, plan.limit) == (7, 4.20)


def test_selling_flat_is_blocked() -> None:
    plan = plan_sell(symbol="WETO", fraction=1.0, position=0, bid=4.25, ask=4.27, **OFFSET)
    assert plan.blocked == "no_position"


def test_a_sell_is_never_refused_for_being_over_the_cap() -> None:
    """The cap bounds what may be bought. Refusing to let a position out
    because it has grown past the ceiling would be the wrong kind of safety —
    the whole reason ALL exists is to be able to leave."""
    plan = plan_sell(symbol="WETO", fraction=1.0, position=100_000, bid=4.25, ask=4.27, **OFFSET)
    assert plan.ok
    assert plan.shares == 100_000


def test_a_short_position_sells_nothing() -> None:
    """Long only, at the plan layer too: a negative position is not covered
    by these buttons, it is refused."""
    plan = plan_sell(symbol="WETO", fraction=1.0, position=-40, bid=4.25, ask=4.27, **OFFSET)
    assert plan.blocked == "no_position"


# ── settings ───────────────────────────────────────────────────────────


def test_trading_is_off_by_default() -> None:
    """The switch that keeps a test run, and a fresh checkout, from trading."""
    assert TradingSettings().enabled is False
    assert Settings(_env_file=None).trading.enabled is False


def test_the_default_cap_is_a_hair_above_the_largest_button() -> None:
    """So no fault in the stack can produce an order larger than the one that
    was clicked. Raising the buttons means raising this deliberately."""
    settings = TradingSettings()
    assert settings.max_order_dollars > max(settings.buy_dollars)
    assert settings.max_order_dollars < 2 * max(settings.buy_dollars)


def test_the_paper_ports_are_recognised() -> None:
    """The strip says live or paper, and it reads the port rather than asking
    the user to remember which login TWS is on."""
    assert TradingSettings(port=7497).is_paper
    assert TradingSettings(port=4002).is_paper
    assert not TradingSettings(port=7496).is_paper
    assert not TradingSettings(port=4001).is_paper


@pytest.mark.parametrize("dollars", [[], [0], [10, -5]])
def test_nonsense_buy_buttons_fail_at_startup(dollars: list) -> None:
    with pytest.raises(ValueError):
        TradingSettings(buy_dollars=dollars)


@pytest.mark.parametrize("fractions", [[], [0], [1.5], [0.5, -0.1]])
def test_nonsense_sell_buttons_fail_at_startup(fractions: list) -> None:
    with pytest.raises(ValueError):
        TradingSettings(sell_fractions=fractions)
