/**
 * Where a server error goes. Only a failed chart load belongs to the chart:
 * its "error" status drops every live bar until the next snapshot, so a refused
 * order or a scanner complaint routed there froze the chart.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChartEngine } from "@/chart/ChartEngine";
import { setEngine } from "@/chart/engineRef";
import { useTerminalStore } from "@/store/useTerminalStore";
import type { ServerMessage } from "@/types/protocol";

import { handleMessage } from "./useTerminal";

const INITIAL = useTerminalStore.getState();

const BAR = {
  type: "bar",
  symbol: "WETO",
  timeframe: "10s",
  bar: { t: 100, o: 1, h: 1, l: 1, c: 1, v: 1, n: 1, x: 0 },
  series: {},
} as const;

function error(code: string, message: string, action?: string): ServerMessage {
  return { type: "error", code, message, action: action ?? null };
}

let engine: { applyBar: ReturnType<typeof vi.fn> };

beforeEach(() => {
  useTerminalStore.setState(INITIAL, true);
  engine = {
    applyBar: vi.fn(),
    previousClose: vi.fn(() => null),
    sessionVolumeAt: vi.fn(() => null),
    barCount: vi.fn(() => 1),
  } as never;
  setEngine(engine as unknown as ChartEngine);
  const store = useTerminalStore.getState();
  store.requestChart("WETO", "10s");
  store.chartReady({ symbol: "WETO", timeframe: "10s", barCount: 1, live: null });
});

describe("errors that belong to the chart", () => {
  it("puts a symbol with no data on the chart", () => {
    handleMessage(error("no_data", "No market data available for WETO."));
    expect(useTerminalStore.getState()).toMatchObject({
      status: "error",
      error: "No market data available for WETO.",
    });
  });

  it("puts any failure answering a subscribe on the chart", () => {
    handleMessage(error("bad_command", "symbol: invalid", "subscribe"));
    expect(useTerminalStore.getState().status).toBe("error");
  });
});

describe("errors that do not", () => {
  it("sends a refused order to the strip and keeps the chart live", () => {
    handleMessage(error("trade", "Trading is disabled.", "trade.buy"));
    const state = useTerminalStore.getState();
    expect(state.status).toBe("ready");
    expect(state.orderNote).toBe("Trading is disabled.");

    handleMessage(BAR);
    expect(engine.applyBar).toHaveBeenCalledOnce();
  });

  it("makes anything else a notice and keeps the chart live", () => {
    handleMessage(error("scanner", "Unknown scanner 'x'."));
    const state = useTerminalStore.getState();
    expect(state.status).toBe("ready");
    expect(state.notice).toBe("Unknown scanner 'x'.");
  });
});

describe("the strip's own note", () => {
  it("is cleared by the next order and by a new symbol", () => {
    const store = useTerminalStore.getState();
    store.setOrderNote("refused");
    store.buy("WETO", 25);
    expect(useTerminalStore.getState().orderNote).toBeNull();

    store.setOrderNote("refused");
    store.requestChart("OTHR", "10s");
    expect(useTerminalStore.getState().orderNote).toBeNull();
  });
});
