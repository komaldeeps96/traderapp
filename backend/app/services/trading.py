"""Order entry, between the buttons and the broker. See docs/order-entry.md.

The client sends dollars or a fraction, never a quantity; shares are sized here
from the freshest quote and IBKR's own position. The guards, in order: the
master switch, one order per symbol and side per ``repeat_guard_seconds``, the
per-order cap measured at the limit, and long only against the shares no
working or unreported sell has already claimed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from ..core.settings import TradingSettings
from ..domain.orders import OrderPlan, plan_buy, plan_sell, to_micros
from ..providers.ibkr_broker import IBKRBroker
from ..services.quotes import QuoteService

logger = logging.getLogger(__name__)

# What each blocked reason says on the strip. Machine-readable codes cross the
# wire; the client renders its own copy on the disabled button, and these are
# for the rejection line, where the sentence has to stand alone.
BLOCKED_MESSAGES = {
    "no_quote": "No bid/ask — cannot price an order.",
    "no_position": "No position to sell.",
    "committed": "Every share is already in a working sell.",
    "too_small": "Too small for one whole share.",
    "over_cap": "Over the per-order cap.",
}


class TradingService:
    """Turns a button press into a checked, sized, priced order."""

    def __init__(
        self,
        broker: IBKRBroker,
        quotes: QuoteService,
        settings: TradingSettings,
        clock: Callable[[], float] = time.monotonic,
        feed_delayed: Callable[[], bool] = lambda: False,
        feed_live: Callable[[], bool] = lambda: True,
        halted: Callable[[str], bool] = lambda _symbol: False,
        wall_clock: Callable[[], float] = time.time,
    ):
        self._broker = broker
        self._quotes = quotes
        self._settings = settings
        self._clock = clock
        # Whether the quotes that size an order are the delayed tape: a limit
        # priced off a fifteen-minute-old book fills badly or rests unseen.
        self._feed_delayed = feed_delayed
        self._feed_live = feed_live
        self._halted = halted
        # Quote.time is a UTC epoch second, so its age is measured on the wall.
        self._wall_clock = wall_clock
        # Symbols with an order being placed. Qualifying a contract awaits the
        # network, so two windows could otherwise both pass every check.
        self._in_flight: set[str] = set()
        # When each (symbol, side) last reached the broker. TWS acknowledges in
        # milliseconds, faster than a double-click, so an acknowledgement cannot
        # be what tells a second click from a second decision.
        self._last_sent: dict[tuple[str, str], float] = {}
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
            "repeat_guard_seconds": self._settings.repeat_guard_seconds,
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
            committed=self._broker.committed_to_sells(symbol),
            bid=bid,
            ask=ask,
            offset_cents=self._settings.offset_cents,
            offset_bps=self._settings.offset_bps,
        )

    # ── orders ─────────────────────────────────────────────────────────

    async def buy(self, symbol: str, dollars: float) -> dict:
        """Buy ``dollars`` worth of ``symbol``, sized here and now.

        The requested amount is checked against the cap before sizing as well as
        after: a button configured larger than the ceiling is refused for what
        it asked for, not what it rounded down to.
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

    def _why_not(self, symbol: str, plan: OrderPlan) -> str | None:
        """The first reason this plan cannot be sent, or None. Order matters:
        the most fundamental refusal is the one worth reading."""
        checks = (
            (not self._settings.enabled, "Trading is disabled."),
            (not self._broker.is_available, "TWS is not connected."),
            (not self._feed_live(), "No market data feed; an order would be priced off a frozen book."),
            (
                self._feed_delayed(),
                "Quotes are on the delayed feed; an order would be priced off a stale book.",
            ),
            (self._halted(symbol), f"{symbol} is halted; an order would rest until the reopen."),
            (
                self._quote_age(symbol) > self._settings.max_quote_age_seconds,
                f"The quote on {symbol} is {self._quote_age(symbol):.0f}s old.",
            ),
            (
                self._repeated(symbol, plan.side),
                f"A second {plan.side.lower()} on {symbol} inside "
                f"{self._settings.repeat_guard_seconds:g}s is held as a double-click.",
            ),
            (plan.blocked is not None, BLOCKED_MESSAGES.get(plan.blocked or "", plan.blocked)),
            (plan.shares <= 0, BLOCKED_MESSAGES["too_small"]),
            (
                self._over_position_cap(symbol, plan),
                f"{symbol} would pass the ${self._settings.max_position_dollars:g} position cap.",
            ),
        )
        return next((message for failed, message in checks if failed), None)

    def _quote_age(self, symbol: str) -> float:
        """Seconds since the quote last moved; zero with none, which ``no_quote`` refuses."""
        quote = self._quotes.get(symbol)
        return 0.0 if quote is None else self._wall_clock() - quote.time

    def _over_position_cap(self, symbol: str, plan: OrderPlan) -> bool:
        if plan.side != "BUY":
            return False
        held = max(0, self._broker.position(symbol))
        worst_case = (held + plan.shares) * to_micros(plan.limit)
        return worst_case > to_micros(self._settings.max_position_dollars)

    def _repeated(self, symbol: str, side: str) -> bool:
        sent = self._last_sent.get((symbol, side))
        return sent is not None and self._clock() - sent < self._settings.repeat_guard_seconds

    async def _send(self, symbol: str, plan: OrderPlan) -> dict:
        refusal = self._why_not(symbol, plan)
        if refusal is not None:
            return self._refuse(refusal)

        # Checked and claimed with no await in between, so no lock is needed.
        if symbol in self._in_flight:
            return self._refuse(f"An order on {symbol} is already in flight.")
        self._in_flight.add(symbol)
        try:
            result = await self._broker.place(
                symbol=symbol, side=plan.side, shares=plan.shares, limit=plan.limit
            )
        finally:
            # A raising broker must not wedge the symbol shut for the session.
            self._in_flight.discard(symbol)

        if not result.get("ok"):
            return self._refuse(str(result.get("message") or "Order rejected."))
        self._last_sent[(symbol, plan.side)] = self._clock()
        self._note = None
        self._broker.clear_error()
        return result

    def _refuse(self, message: str) -> dict:
        """Record a refusal where the strip will show it, and report it.

        Refusals are loud on purpose: an order that silently did not go is the
        failure this panel exists to remove.
        """
        self._note = message
        logger.info("Order refused: %s", message)
        return {"ok": False, "message": message}
