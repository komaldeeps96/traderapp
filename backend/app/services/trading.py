"""Order entry, between the buttons and the broker.

Everything that decides *whether* an order happens lives here, and nothing
that decides it lives in the client. The panel sends a dollar amount or a
fraction — never a quantity — so a browser tab that has been asleep for a
minute cannot put a stale size on the wire. This recomputes the shares from
the freshest quote and IBKR's own position at the instant of the click, and
what it computes is what is sent.

Four guards, in the order they run:

1. **The switch.** ``trading.enabled`` is False by default and False in every
   test settings object. With it off there is no broker connection and this
   service refuses everything.
2. **The cap.** ``max_order_dollars`` bounds one order's notional, measured at
   the limit rather than at the ask, so it bounds the worst case. It defaults
   to a hair above the largest button, which means no arithmetic fault
   anywhere in the stack can produce an order larger than the one clicked.
3. **Long only.** A sell is clamped to the position IBKR reports, so it can
   never exceed what is held and therefore can never open a short. Enforced
   in ``domain/orders.plan_sell`` rather than by a disabled button, because a
   disabled button is a display and this is a rule.
4. **One click, one order.** A symbol with an order in flight refuses the
   next until the first is acknowledged. A double-click on a $50 button is
   the most likely way to spend $100 by accident.
"""

from __future__ import annotations

import asyncio
import logging

from ..core.settings import TradingSettings
from ..domain.orders import OrderPlan, plan_buy, plan_sell
from ..providers.ibkr_broker import IBKRBroker
from ..services.quotes import QuoteService

logger = logging.getLogger(__name__)

# What each blocked reason says on the strip. Machine-readable codes cross the
# wire; the client renders its own copy on the disabled button, and these are
# for the rejection line, where the sentence has to stand alone.
BLOCKED_MESSAGES = {
    "no_quote": "No bid/ask — cannot price an order.",
    "no_position": "No position to sell.",
    "too_small": "Too small for one whole share.",
    "over_cap": "Over the per-order cap.",
}


class TradingService:
    """Turns a button press into a checked, sized, priced order."""

    def __init__(self, broker: IBKRBroker, quotes: QuoteService, settings: TradingSettings):
        self._broker = broker
        self._quotes = quotes
        self._settings = settings
        # Symbols with an order on the wire, unacknowledged. Guards the
        # double-click; released in a finally so a raising broker cannot
        # wedge a symbol shut for the session.
        self._in_flight: set[str] = set()
        self._lock = asyncio.Lock()
        # The most recent rejection, shown on the strip until the next action.
        self._note: str | None = None

    # ── state the panel draws ──────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    def state(self) -> dict:
        """Everything the strip needs about the connection itself."""
        return {
            "enabled": self._settings.enabled,
            "connected": self._broker.is_available,
            "account": self._broker.account,
            "paper": self._settings.is_paper,
            "read_only": self._broker.read_only,
            "buy_dollars": list(self._settings.buy_dollars),
            "sell_fractions": list(self._settings.sell_fractions),
            "offset_cents": self._settings.offset_cents,
            "offset_bps": self._settings.offset_bps,
            "max_order_dollars": self._settings.max_order_dollars,
            "tif": self._settings.tif,
            "positions_known": self._broker.positions_known,
            "note": self._note or self._broker.last_error,
        }

    def positions(self) -> list[dict]:
        return self._broker.positions()

    def working_orders(self) -> list[dict]:
        return self._broker.working_orders()

    def position(self, symbol: str) -> int:
        return self._broker.position(symbol)

    # ── plans ──────────────────────────────────────────────────────────

    def _quote(self, symbol: str) -> tuple[float, float]:
        quote = self._quotes.get(symbol)
        if quote is None:
            return 0.0, 0.0
        return quote.bid, quote.ask

    def plan_buy(self, symbol: str, dollars: float) -> OrderPlan:
        bid, ask = self._quote(symbol)
        return plan_buy(
            symbol=symbol,
            dollars=dollars,
            bid=bid,
            ask=ask,
            offset_cents=self._settings.offset_cents,
            offset_bps=self._settings.offset_bps,
            max_order_dollars=self._settings.max_order_dollars,
        )

    def plan_sell(self, symbol: str, fraction: float) -> OrderPlan:
        bid, ask = self._quote(symbol)
        return plan_sell(
            symbol=symbol,
            fraction=fraction,
            position=self._broker.position(symbol),
            bid=bid,
            ask=ask,
            offset_cents=self._settings.offset_cents,
            offset_bps=self._settings.offset_bps,
        )

    # ── orders ─────────────────────────────────────────────────────────

    async def buy(self, symbol: str, dollars: float) -> dict:
        """Buy ``dollars`` worth of ``symbol``, sized here and now.

        The requested amount is checked against the cap *before* it is sized,
        as well as after: a button configured larger than the ceiling should
        be refused for what it asked for, not for what it happened to round
        down to.
        """
        if dollars > self._settings.max_order_dollars:
            return self._refuse(
                f"${dollars:,.0f} is over the ${self._settings.max_order_dollars:,.0f} "
                "per-order cap."
            )
        return await self._send(symbol, self.plan_buy(symbol, dollars))

    async def sell(self, symbol: str, fraction: float) -> dict:
        return await self._send(symbol, self.plan_sell(symbol, fraction))

    async def cancel_all(self) -> dict:
        if not self._settings.enabled:
            return self._refuse("Trading is disabled.")
        cancelled = await self._broker.cancel_all()
        self._note = None
        self._broker.clear_error()
        return {"ok": True, "cancelled": cancelled}

    def _why_not(self, plan: OrderPlan) -> str | None:
        """The reason this plan cannot be sent, or None."""
        if not self._settings.enabled:
            return "Trading is disabled."
        if not self._broker.is_available:
            return "TWS is not connected."
        if plan.blocked is not None:
            return BLOCKED_MESSAGES.get(plan.blocked, plan.blocked)
        if plan.shares <= 0:
            return BLOCKED_MESSAGES["too_small"]
        return None

    async def _send(self, symbol: str, plan: OrderPlan) -> dict:
        refusal = self._why_not(plan)
        if refusal is not None:
            return self._refuse(refusal)

        async with self._lock:
            if symbol in self._in_flight:
                return self._refuse(f"An order on {symbol} is already in flight.")
            self._in_flight.add(symbol)
        try:
            result = await self._broker.place(
                symbol=symbol, side=plan.side, shares=plan.shares, limit=plan.limit
            )
        finally:
            async with self._lock:
                self._in_flight.discard(symbol)

        if not result.get("ok"):
            return self._refuse(str(result.get("message") or "Order rejected."))
        self._note = None
        self._broker.clear_error()
        return result

    def _refuse(self, message: str) -> dict:
        """Record a refusal where the strip will show it, and report it.

        Refusals are loud on purpose. During a move nobody is reading a log,
        and an order that silently did not go is exactly the failure this
        panel exists to remove.
        """
        self._note = message
        logger.info("Order refused: %s", message)
        return {"ok": False, "message": message}
