/**
 * The button-preview arithmetic, against the shared case table.
 *
 * The same table drives `backend/tests/unit/test_orders.py`. The duplication
 * exists so the button can size itself without a round trip; this is what
 * stops the two copies from quietly disagreeing about what a click will do.
 */

import { describe, expect, it } from "vitest";

import cases from "./order-cases.json";
import {
  buyLimit,
  offsetMicros,
  previewBuy,
  previewSell,
  sellLabel,
  sellLimit,
  sharesForDollars,
  sharesForFraction,
  tickMicros,
  toMicros,
} from "./orders";

const OFFSET = { cents: cases.offset.cents, bps: cases.offset.bps };
const QUOTE = { bid: 4.25, ask: 4.27 };

describe("the shared case table", () => {
  it.each(cases.limits)("$why — bid $bid ask $ask", (row) => {
    expect(buyLimit(row.ask, OFFSET)).toBeCloseTo(row.buy, 6);
    expect(sellLimit(row.bid, OFFSET)).toBeCloseTo(row.sell, 6);
  });

  it.each(cases.buy_shares)("$$dollars at $ask is $shares shares", (row) => {
    expect(sharesForDollars(row.dollars, row.ask)).toBe(row.shares);
  });

  it.each(cases.sell_shares)(
    "$fraction of $position is $shares shares",
    (row) => {
      expect(sharesForFraction(row.position, row.fraction)).toBe(row.shares);
    },
  );
});

describe("properties the table cannot express", () => {
  it("always prices a limit marketable", () => {
    // The whole point. Rounding to nearest would break this on one side.
    for (const row of cases.limits) {
      expect(buyLimit(row.ask, OFFSET)).toBeGreaterThanOrEqual(row.ask);
      expect(sellLimit(row.bid, OFFSET)).toBeLessThanOrEqual(row.bid);
    }
  });

  it("always lands a limit on a valid tick", () => {
    // Off-tick is rejected by TWS, so this is a hard requirement.
    for (const row of cases.limits) {
      for (const price of [
        buyLimit(row.ask, OFFSET),
        sellLimit(row.bid, OFFSET),
      ]) {
        const micros = toMicros(price);
        expect(micros % tickMicros(micros)).toBe(0);
      }
    }
  });

  it("never prices a sell at or below zero", () => {
    for (const row of cases.limits) {
      expect(sellLimit(row.bid, OFFSET)).toBeGreaterThan(0);
    }
  });

  it("never sells more than the position", () => {
    for (const row of cases.sell_shares) {
      const shares = sharesForFraction(row.position, row.fraction);
      expect(shares).toBeGreaterThanOrEqual(0);
      expect(shares).toBeLessThanOrEqual(Math.max(0, row.position));
    }
  });

  it("takes the larger of the flat and proportionate offsets", () => {
    expect(offsetMicros(toMicros(10.0), OFFSET)).toBe(50_000);
    expect(offsetMicros(toMicros(33.33), OFFSET)).toBe(50_000);
    expect(offsetMicros(toMicros(33.34), OFFSET)).toBe(50_010);
    expect(offsetMicros(toMicros(100.0), OFFSET)).toBe(150_000);
  });
});

describe("buy previews", () => {
  it("carries the shares, the limit and the worst-case spend", () => {
    expect(previewBuy(25, QUOTE, OFFSET, 60)).toEqual({
      shares: 5,
      limit: 4.32,
      notional: 21.6,
      blocked: null,
    });
  });

  it.each([
    ["nothing", { bid: 0, ask: 0 }],
    ["no ask", { bid: 4.25, ask: 0 }],
    ["crossed", { bid: 4.3, ask: 4.2 }],
    ["missing", null],
  ])("blocks on %s", (_why, quote) => {
    expect(previewBuy(25, quote, OFFSET, 60).blocked).toBe("no_quote");
  });

  it("blocks rather than rounding up when the amount buys no whole share", () => {
    // A $10 button is simply dead on a $241 name. Zero is an ordinary answer.
    expect(previewBuy(10, { bid: 241, ask: 241.1 }, OFFSET, 60)).toMatchObject({
      shares: 0,
      blocked: "too_small",
    });
  });

  it("blocks at the cap the server would refuse it at", () => {
    // Six shares is $60.00 at the ask and $60.30 at the limit. The server
    // measures the cap at the limit, so the button must too — otherwise it
    // draws as live and fails on the click.
    expect(previewBuy(60, { bid: 9.99, ask: 10.0 }, OFFSET, 60)).toMatchObject({
      shares: 6,
      notional: 60.3,
      blocked: "over_cap",
    });
  });

  it("blocks an amount over the cap before sizing it", () => {
    expect(previewBuy(500, QUOTE, OFFSET, 60).blocked).toBe("over_cap");
  });
});

describe("sell previews", () => {
  it("prices through the bid", () => {
    expect(previewSell(0.5, 14, QUOTE, OFFSET)).toMatchObject({
      shares: 7,
      limit: 4.2,
    });
  });

  it("closes the position exactly on ALL", () => {
    for (const position of [1, 3, 7, 14, 99, 101]) {
      expect(previewSell(1, position, QUOTE, OFFSET).shares).toBe(position);
    }
  });

  it("blocks while flat", () => {
    expect(previewSell(1, 0, QUOTE, OFFSET).blocked).toBe("no_position");
  });

  it("blocks on a short — these buttons do not cover", () => {
    expect(previewSell(0.5, -40, QUOTE, OFFSET).blocked).toBe("no_position");
  });

  it("blocks a fraction that floors to nothing", () => {
    expect(previewSell(0.25, 3, QUOTE, OFFSET).blocked).toBe("too_small");
  });

  it("is never refused for the cap — leaving must always be possible", () => {
    expect(previewSell(1, 100_000, QUOTE, OFFSET).blocked).toBeNull();
  });
});

describe("labels", () => {
  it("names the whole-position button ALL, not 100%", () => {
    expect(sellLabel(1)).toBe("ALL");
    expect(sellLabel(0.5)).toBe("50%");
    expect(sellLabel(0.25)).toBe("25%");
  });
});
