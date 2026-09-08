import { useEffect, useRef, useState } from "react";

import { formatPrice } from "@/lib/format";
import {
  previewBuy,
  previewSell,
  sellLabel,
  type ButtonPlan,
  type OffsetConfig,
} from "@/lib/orders";
import { useTerminalStore } from "@/store/useTerminalStore";
import type { BlockedReason, PositionRow } from "@/types/protocol";

/**
 * Order entry — the strip under the chart.
 *
 * WHY IT IS HERE AND NOT SOMEWHERE ELSE. The decision to click is made at the
 * chart's right edge and the bid/ask readout, so the chart's bottom edge is
 * the nearest fixed anchor to a live price that moves vertically. It sits
 * *outside* the tab panel, so a position stays visible while a balance sheet
 * is being read. It is deliberately far from the symbol input in the toolbar:
 * buy buttons up there are one mistyped ticker away from an unintended order.
 * And it costs height rather than width, which the right dock already owns.
 * See docs/order-entry.md.
 *
 * WHAT THE LAYOUT IS DOING. The ticker is the leftmost thing on the strip and
 * the largest — buying the symbol you were looking at a moment ago is the
 * single worst failure mode of a six-button trading UI, so it is spelled out
 * where the click starts. Buys ascend from the left, sells ascend to the
 * right, with dead space between: the two innermost neighbours are `$50` and
 * `25%`, the cheapest mis-click pair available, and `ALL` sits at the far edge
 * furthest from every buy button. Widths are fixed and figures tabular, so a
 * share count going from 9 to 10 does not shift the row under a finger that
 * is already moving.
 *
 * THERE IS NO CONFIRMATION DIALOG, on purpose — it would defeat a one-click
 * momentum entry, which is the entire feature. The protection is elsewhere: a
 * master switch that is off by default, a hard server-side cap, a long-only
 * clamp on the quantity, and the in-flight guard that turns a double-click
 * into one order. See services/trading.py.
 */

/** What a dead button says, in the space a dead button has. */
const BLOCKED_LABEL: Record<BlockedReason, string> = {
  no_quote: "no bid/ask",
  no_position: "flat",
  too_small: "0 sh",
  over_cap: "over cap",
};

const BLOCKED_TITLE: Record<BlockedReason, string> = {
  no_quote: "No bid/ask for this symbol — an order cannot be priced.",
  no_position: "Nothing held in this symbol.",
  too_small: "Not enough for one whole share. Fractional shares are not used.",
  over_cap:
    "Over the per-order cap set in settings (trading.max_order_dollars).",
};

function OrderButton({
  label,
  plan,
  tone,
  testId,
  disabled,
  onClick,
}: {
  label: string;
  plan: ButtonPlan;
  tone: "buy" | "sell";
  testId: string;
  disabled: boolean;
  onClick: () => void;
}) {
  const dead = disabled || plan.blocked !== null || plan.shares <= 0;
  const detail = plan.blocked
    ? BLOCKED_LABEL[plan.blocked]
    : `${plan.shares} sh`;
  const palette =
    tone === "buy"
      ? "border-up/40 bg-up/10 text-up hover:bg-up/20"
      : "border-down/40 bg-down/10 text-down hover:bg-down/20";

  return (
    <button
      type="button"
      data-testid={testId}
      data-blocked={plan.blocked ?? undefined}
      disabled={dead}
      onClick={onClick}
      title={
        plan.blocked
          ? BLOCKED_TITLE[plan.blocked]
          : `${label} — ${plan.shares} shares, limit ${formatPrice(plan.limit)}, ` +
            `about $${plan.notional.toFixed(2)}`
      }
      className={`tnum flex h-9 w-[76px] shrink-0 flex-col items-center justify-center rounded-sm border font-mono leading-tight transition-colors ${
        dead
          ? "cursor-not-allowed border-line bg-panel text-ink-3 opacity-60"
          : palette
      }`}
    >
      <span className="text-[12px] font-bold">{label}</span>
      <span className="text-[9px] font-semibold opacity-80">{detail}</span>
    </button>
  );
}

/** The account chips. A six-button entry UI that shows only the focused name
 *  is a way to end a day long something you forgot about. */
function PositionsRail({
  positions,
  symbol,
  onSelect,
}: {
  positions: PositionRow[];
  symbol: string;
  onSelect: (symbol: string) => void;
}) {
  if (positions.length === 0) return null;
  return (
    <div
      className="flex min-w-0 items-center gap-1 overflow-x-auto"
      data-testid="positions-rail"
    >
      {positions.map((position) => (
        <button
          key={position.symbol}
          type="button"
          onClick={() => onSelect(position.symbol)}
          data-testid={`position-${position.symbol}`}
          className={`tnum shrink-0 rounded-sm border px-1.5 py-0.5 font-mono text-[10px] ${
            position.symbol === symbol
              ? "border-accent bg-accent/10 text-ink"
              : "border-line bg-panel text-ink-2 hover:border-line-strong"
          }`}
        >
          <span className="font-bold">{position.symbol}</span>{" "}
          <span>{position.shares}</span>{" "}
          <span className={position.unrealized >= 0 ? "text-up" : "text-down"}>
            {position.unrealized >= 0 ? "+" : "−"}$
            {Math.abs(position.unrealized).toFixed(2)}
          </span>
        </button>
      ))}
    </div>
  );
}

export function OrderPanel({
  onSelect,
}: {
  onSelect: (symbol: string) => void;
}) {
  const trading = useTerminalStore((state) => state.trading);
  const positions = useTerminalStore((state) => state.positions);
  const workingOrders = useTerminalStore((state) => state.workingOrders);
  const lastOrder = useTerminalStore((state) => state.lastOrder);
  const symbol = useTerminalStore((state) => state.symbol);
  const quote = useTerminalStore((state) => state.quote);
  const info = useTerminalStore((state) => state.info);
  const buy = useTerminalStore((state) => state.buy);
  const sell = useTerminalStore((state) => state.sell);
  const cancelAllOrders = useTerminalStore((state) => state.cancelAllOrders);

  // A press is held for a beat so a fast fill still shows that the click
  // registered. Without it a button that works looks like a button that did
  // nothing, which is how a second order gets sent.
  const [pressed, setPressed] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const press = (key: string, send: () => void) => {
    send();
    setPressed(key);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setPressed(null), 600);
  };

  // With trading off the strip is not rendered at all: an inert row of buy
  // buttons is worse than no row, because it looks like it would work.
  if (!trading?.enabled) return null;

  const offset: OffsetConfig = {
    cents: trading.offset_cents,
    bps: trading.offset_bps,
  };
  const position = positions.find((row) => row.symbol === symbol);
  const held = position?.shares ?? 0;
  const halted = info?.halted === true;
  // Halted, disconnected or read-only: the whole strip goes dead rather than
  // each button discovering it separately at the moment of the click.
  const frozen = !trading.connected || halted || trading.read_only;
  const note =
    trading.note ?? (halted ? "Halted — orders will not fill." : null);

  return (
    <section
      data-testid="order-panel"
      aria-label="Order entry"
      className="flex shrink-0 flex-col gap-1 border-t border-line bg-panel px-2 py-1.5"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
        <span
          className="tnum font-mono text-[13px] font-bold text-ink"
          data-testid="order-symbol"
        >
          {symbol || "—"}
        </span>

        <span
          className="tnum font-mono text-ink-2"
          data-testid="order-position"
        >
          {held > 0 ? (
            <>
              POS <span className="font-bold text-ink">{held}</span> @{" "}
              {formatPrice(position?.avg_cost ?? 0)}{" "}
              <span
                className={
                  (position?.unrealized ?? 0) >= 0 ? "text-up" : "text-down"
                }
              >
                {(position?.unrealized ?? 0) >= 0 ? "+" : "−"}$
                {Math.abs(position?.unrealized ?? 0).toFixed(2)}
              </span>
            </>
          ) : (
            <span className="text-ink-3">FLAT</span>
          )}
        </span>

        <span className="tnum font-mono text-ink-3" data-testid="order-quote">
          {quote ? (
            <>
              {formatPrice(quote.bid)} × {formatPrice(quote.ask)}
            </>
          ) : (
            "no bid/ask"
          )}
        </span>

        <PositionsRail
          positions={positions}
          symbol={symbol}
          onSelect={onSelect}
        />

        <span className="ml-auto flex items-center gap-2">
          {workingOrders.length > 0 && (
            <button
              type="button"
              onClick={cancelAllOrders}
              data-testid="cancel-all"
              className="rounded-sm border border-warn/50 bg-warn/10 px-1.5 py-0.5 text-[10px] font-semibold text-warn hover:bg-warn/20"
            >
              Cancel {workingOrders.length}
            </button>
          )}
          <span
            data-testid="order-account"
            title={
              trading.paper
                ? "Paper account — orders are simulated by IBKR."
                : "LIVE account — these buttons spend real money."
            }
            className={`rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-bold ${
              trading.paper ? "bg-ink-3/20 text-ink-2" : "bg-down/20 text-down"
            }`}
          >
            {trading.paper ? "PAPER" : "LIVE"}
            {trading.account ? ` ${trading.account}` : ""}
          </span>
          {!trading.connected && (
            <span
              className="text-[10px] font-semibold text-down"
              data-testid="order-disconnected"
            >
              TWS DOWN
            </span>
          )}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {trading.buy_dollars.map((dollars) => {
          const plan = previewBuy(
            dollars,
            quote,
            offset,
            trading.max_order_dollars,
          );
          const key = `buy-${dollars}`;
          return (
            <OrderButton
              key={key}
              testId={`order-${key}`}
              label={pressed === key ? "···" : `$${dollars}`}
              plan={plan}
              tone="buy"
              disabled={frozen || !symbol}
              onClick={() => press(key, () => buy(symbol, dollars))}
            />
          );
        })}

        {/* Dead space between the sides. The gap is the safety feature. */}
        <span aria-hidden className="mx-2 h-6 w-px bg-line-strong" />

        {trading.sell_fractions.map((fraction) => {
          const plan = previewSell(fraction, held, quote, offset);
          const key = `sell-${fraction}`;
          return (
            <OrderButton
              key={key}
              testId={`order-${key}`}
              label={pressed === key ? "···" : sellLabel(fraction)}
              plan={plan}
              tone="sell"
              disabled={frozen || !symbol}
              onClick={() => press(key, () => sell(symbol, fraction))}
            />
          );
        })}

        {note && (
          <span
            role="status"
            data-testid="order-note"
            className="ml-2 min-w-0 flex-1 truncate text-[11px] font-semibold text-down"
          >
            {note}
          </span>
        )}
        {!note && lastOrder && (
          <span
            data-testid="order-ack"
            className="tnum ml-2 min-w-0 flex-1 truncate font-mono text-[11px] text-ink-3"
          >
            {lastOrder.side} {lastOrder.shares} {lastOrder.symbol} @{" "}
            {formatPrice(lastOrder.limit)}
            {" · "}
            {lastOrder.status}
            {lastOrder.filled > 0 &&
              ` ${lastOrder.filled} @ ${formatPrice(lastOrder.avg_fill)}`}
          </span>
        )}
      </div>
    </section>
  );
}
