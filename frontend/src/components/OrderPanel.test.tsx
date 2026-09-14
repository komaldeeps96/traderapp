/**
 * The order strip's own guards — the ones that live in the browser.
 *
 * The server refuses a repeat inside its window whatever the page does; this
 * is what makes the second click of a double-click visibly dead instead of a
 * refusal a moment later, and what stops a focused button from being pressed
 * again by an Enter meant for somewhere else.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCommandSink } from "@/lib/commands";
import { useTerminalStore } from "@/store/useTerminalStore";
import type {
  ClientCommand,
  PositionRow,
  QuoteMessage,
  TradingState,
} from "@/types/protocol";

import { OrderPanel } from "./OrderPanel";

const INITIAL = useTerminalStore.getState();

function tradingState(overrides: Partial<TradingState> = {}): TradingState {
  return {
    enabled: true,
    connected: true,
    account: "DU1234",
    paper: true,
    read_only: false,
    buy_dollars: [10, 25, 50],
    sell_fractions: [0.25, 0.5, 1],
    offset_cents: 5,
    offset_bps: 15,
    max_order_dollars: 60,
    repeat_guard_seconds: 1,
    tif: "DAY",
    positions_known: true,
    note: null,
    ...overrides,
  };
}

function position(shares: number, committed = 0): PositionRow {
  return { symbol: "WETO", shares, committed, avg_cost: 4.0, unrealized: 0 };
}

const QUOTE = {
  type: "quote",
  symbol: "WETO",
  bid: 4.25,
  ask: 4.27,
  bs: 10,
  as: 10,
  t: 0,
} as QuoteMessage;

let sent: ClientCommand[];

function arm(overrides: Partial<ReturnType<typeof useTerminalStore.getState>> = {}) {
  useTerminalStore.setState({
    connected: true,
    symbol: "WETO",
    quote: QUOTE,
    trading: tradingState(),
    positions: [position(14)],
    orderArmed: true,
    ...overrides,
  });
  render(<OrderPanel onSelect={() => {}} />);
}

const button = (id: string) => screen.getByTestId(id);
const trades = () => sent.filter((command) => command.action.startsWith("trade."));

beforeEach(() => {
  vi.useFakeTimers();
  useTerminalStore.setState(INITIAL, true);
  sent = [];
  setCommandSink((command) => sent.push(command));
});

afterEach(() => {
  vi.useRealTimers();
  setCommandSink(null);
});

describe("one click, one order", () => {
  it("sends one order for a double-click", () => {
    arm();
    fireEvent.click(button("order-buy-25"));
    fireEvent.click(button("order-buy-25"));
    expect(trades()).toEqual([
      { action: "trade.buy", symbol: "WETO", dollars: 25 },
    ]);
  });

  it("holds the whole side, not just the button pressed", () => {
    arm();
    fireEvent.click(button("order-buy-25"));
    expect(button("order-buy-25")).toHaveTextContent("···");
    expect(button("order-buy-50")).toBeDisabled();
    fireEvent.click(button("order-buy-50"));
    expect(trades()).toHaveLength(1);
  });

  it("gives the side back when the server's window closes", () => {
    arm();
    fireEvent.click(button("order-buy-25"));
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(button("order-buy-25")).toBeEnabled();
    fireEvent.click(button("order-buy-25"));
    expect(trades()).toHaveLength(2);
  });

  it("leaves the other side live", () => {
    arm();
    fireEvent.click(button("order-buy-25"));
    fireEvent.click(button("order-sell-0.5"));
    expect(trades().map((command) => command.action)).toEqual([
      "trade.buy",
      "trade.sell",
    ]);
  });

  it("holds the side for the symbol it was pressed on only", () => {
    arm();
    fireEvent.click(button("order-buy-25"));
    act(() => useTerminalStore.setState({ symbol: "OTHR", quote: { ...QUOTE, symbol: "OTHR" } }));
    expect(button("order-buy-25")).toBeEnabled();
  });

  it("takes focus off the pressed button, so a later Enter cannot press it", () => {
    arm();
    const buy = button("order-buy-25");
    buy.focus();
    fireEvent.click(buy);
    expect(document.activeElement).not.toBe(buy);
  });
});

describe("a strip that must not be used", () => {
  it("is dead while the backend socket is down, and says so", () => {
    // A click with no socket would be dropped on the floor unseen.
    arm({ connected: false });
    expect(button("order-buy-25")).toBeDisabled();
    expect(screen.getByTestId("order-note")).toHaveTextContent("Disconnected");
  });

  it("is dead on the delayed feed, which the server will not price off", () => {
    arm({ delayed: true });
    expect(button("order-buy-25")).toBeDisabled();
    expect(screen.getByTestId("order-note")).toHaveTextContent("delayed");
  });

  it("names a refusal addressed to this window", () => {
    arm({ orderNote: "Orders are accepted only from this machine." });
    expect(screen.getByTestId("order-note")).toHaveTextContent("only from this machine");
  });

  it("renders nothing at all with trading off", () => {
    arm({ trading: tradingState({ enabled: false }) });
    expect(screen.queryByTestId("order-panel")).toBeNull();
  });
});

describe("sells against shares already claimed", () => {
  it("sizes off what no working sell has claimed", () => {
    arm({ positions: [position(14, 7)] });
    expect(button("order-sell-1")).toHaveTextContent("7 sh");
  });

  it("is dead, saying why, when every share is claimed", () => {
    arm({ positions: [position(14, 14)] });
    expect(button("order-sell-1")).toBeDisabled();
    expect(button("order-sell-1")).toHaveTextContent("working");
  });
});

describe("arming", () => {
  it("keeps the buttons dead until the strip is armed", () => {
    arm({ orderArmed: false });
    expect(button("order-buy-25")).toBeDisabled();
    expect(screen.getByTestId("order-note")).toHaveTextContent("press ARM");
  });

  it("tells the server when it is armed", () => {
    arm({ orderArmed: false });
    fireEvent.click(button("order-arm"));
    expect(sent).toContainEqual({ action: "trade.arm", armed: true });
    expect(button("order-buy-25")).not.toBeDisabled();
  });

  it("disarms when the connection drops", () => {
    arm();
    act(() => useTerminalStore.getState().setConnected(false));
    expect(useTerminalStore.getState().orderArmed).toBe(false);
  });
});

