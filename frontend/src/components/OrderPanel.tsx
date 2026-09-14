import { useEffect, useRef, useState, type MouseEvent } from "react";

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
 * Order entry — the strip under the chart. See docs/order-entry.md.
 *
 * **Where it sits.** The chart's bottom edge is the nearest fixed anchor to a
 * live price that moves vertically, and *outside* the tab panel, so a position
 * stays visible while a balance sheet is read. Far from the toolbar's symbol
 * input, where buy buttons would be one mistyped ticker from an unintended
 * order. It costs height rather than width, which the right dock owns.
 *
 * **What the layout does.** The ticker is leftmost and largest: buying the
 * symbol you were looking at a moment ago is the worst failure mode of a
 * six-button trading UI. Buys ascend from the left, sells to the right, with
 * dead space between — the innermost pair is `$50` and `25%`, the cheapest
 * mis-click available, and `ALL` sits furthest from every buy button. Widths
 * are fixed and figures tabular, so a share count going 9 to 10 does not shift
 * the row under a moving finger.
 *
 * **There is no confirmation dialog**, which would defeat a one-click momentum
 * entry. The protection is on the server (services/trading.py); the strip
 * mirrors its repeat window so a second click is visibly dead, not refused.
 */

/** What a dead button says, in the space a dead button has. */
const BLOCKED_LABEL: Record<BlockedReason, string> = {
  no_quote: "no bid/ask",
  no_position: "flat",
  committed: "working",
  too_small: "0 sh",
  over_cap: "over cap",
};

const BLOCKED_TITLE: Record<BlockedReason, string> = {
  no_quote: "No bid/ask for this symbol — an order cannot be priced.",
  no_position: "Nothing held in this symbol.",
  committed: "Every share is already in a working sell order.",
  too_small: "Not enough for one whole share. Fractional shares are not used.",
  over_cap:
    "Over the per-order cap set in settings (trading.max_order_dollars).",
};

type Side = "buy" | "sell";
type Hold = { symbol: string; key: string } | null;

/**
 * Holds one side of the strip for the server's repeat window after an order.
 * A ref as well as state: two clicks can land before React renders between
 * them, and the second must see the first.
 */
function useRepeatGuard(windowMs: number) {
  const [holds, setHolds] = useState<Record<Side, Hold>>({
    buy: null,
    sell: null,
  });
  const latest = useRef(holds);
  const timers = useRef<Partial<Record<Side, ReturnType<typeof setTimeout>>>>(
    {},
  );

  useEffect(() => {
    const pending = timers.current;
    return () => Object.values(pending).forEach(clearTimeout);
  }, []);

  const update = (side: Side, hold: Hold) => {
    latest.current = { ...latest.current, [side]: hold };
    setHolds(latest.current);
  };

  /** Takes the side and returns true, or false if an order already holds it. */
  const claim = (side: Side, symbol: string, key: string): boolean => {
    if (latest.current[side]?.symbol === symbol) return false;
    update(side, { symbol, key });
    clearTimeout(timers.current[side]);
    timers.current[side] = setTimeout(() => update(side, null), windowMs);
    return true;
  };

  return { holds, claim };
}

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
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
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
  const orderNote = useTerminalStore((state) => state.orderNote);
  const connected = useTerminalStore((state) => state.connected);
  const delayed = useTerminalStore((state) => state.delayed);
  const symbol = useTerminalStore((state) => state.symbol);
  const quote = useTerminalStore((state) => state.quote);
  const info = useTerminalStore((state) => state.info);
  const buy = useTerminalStore((state) => state.buy);
  const sell = useTerminalStore((state) => state.sell);
  const cancelAllOrders = useTerminalStore((state) => state.cancelAllOrders);

  const { holds, claim } = useRepeatGuard(
    (trading?.repeat_guard_seconds ?? 0) * 1000,
  );

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
  // Halted, disconnected, delayed or read-only: the whole strip goes dead
  // rather than each button discovering it at the moment of the click. With the
  // backend socket down a click would be dropped on the floor unseen, and on
  // the delayed feed the server refuses to price off a stale book.
  const frozen =
    !connected || !trading.connected || halted || delayed || trading.read_only;
  const note =
    (connected
      ? null
      : "Disconnected from the terminal backend — orders cannot be sent.") ??
    (delayed
      ? "Quotes are delayed — orders are off until the real-time feed returns."
      : null) ??
    trading.note ??
    orderNote ??
    (halted ? "Halted — orders will not fill." : null);

  const heldBy = (side: Side) =>
    holds[side]?.symbol === symbol ? holds[side].key : null;

  const press = (
    side: Side,
    key: string,
    event: MouseEvent<HTMLButtonElement>,
    send: () => void,
  ) => {
    // Focus left on the button would let a later Enter, meant for the symbol
    // box, place the same order again.
    event.currentTarget.blur();
    if (claim(side, symbol, key)) send();
  };

  return (
    <section
      data-testid="order-panel"
      aria-label="Order entry"
      className={`flex shrink-0 flex-col gap-1 bg-panel px-2 py-1.5 ${
        trading.paper ? "border-t border-line" : "border-t-2 border-down"
      }`}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
        <span
          className="tnum font-mono text-[13px] font-bold text-ink"
          data-testid="order-symbol"
        >
          {symbol || "—"}
        </span>
        {info?.description && (
          <span
            className="max-w-[12rem] truncate text-[10px] text-ink-3"
            data-testid="order-company"
            title={info.description}
          >
            {info.description}
          </span>
        )}

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
              trading.paper ? "bg-ink-3/20 text-ink-2" : "bg-down/20 text-down-text"
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
              label={heldBy("buy") === key ? "···" : `$${dollars}`}
              plan={plan}
              tone="buy"
              disabled={frozen || !symbol || heldBy("buy") !== null}
              onClick={(event) =>
                press("buy", key, event, () => buy(symbol, dollars))
              }
            />
          );
        })}

        {/* Dead space between the sides. The gap is the safety feature. */}
        <span aria-hidden className="mx-2 h-6 w-px bg-line-strong" />

        {trading.sell_fractions.map((fraction) => {
          const plan = previewSell(
            fraction,
            held,
            quote,
            offset,
            position?.committed ?? 0,
          );
          const key = `sell-${fraction}`;
          return (
            <OrderButton
              key={key}
              testId={`order-${key}`}
              label={heldBy("sell") === key ? "···" : sellLabel(fraction)}
              plan={plan}
              tone="sell"
              disabled={frozen || !symbol || heldBy("sell") !== null}
              onClick={(event) =>
                press("sell", key, event, () => sell(symbol, fraction))
              }
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
