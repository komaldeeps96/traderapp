import { describe, expect, it } from "vitest";

import { parseFilter } from "./scannerFilters";

describe("parseFilter", () => {
  it("clears on a blank field", () => {
    expect(parseFilter("")).toEqual({ value: "clear" });
    expect(parseFilter("   ")).toEqual({ value: "clear" });
  });

  it("reads a thousands separator as the number it is", () => {
    // Number("1,000") is NaN, which went out as a cleared filter: typing a
    // trade-rate floor of 1,000 removed the floor.
    expect(parseFilter("1,000")).toEqual({ value: 1000 });
    expect(parseFilter("2,500,000")).toEqual({ value: 2_500_000 });
  });

  it("scales a figure typed in millions", () => {
    expect(parseFilter("50", { scale: 1e6 })).toEqual({ value: 50_000_000 });
  });

  it("reports what is not a number instead of clearing the filter", () => {
    expect(parseFilter("abc")).toEqual({ invalid: true });
    expect(parseFilter("1.2.3")).toEqual({ invalid: true });
  });

  it("holds a whole-number field to whole numbers", () => {
    expect(parseFilter("200", { integer: true })).toEqual({ value: 200 });
    expect(parseFilter("1.5", { integer: true })).toEqual({ invalid: true });
  });
});
