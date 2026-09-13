import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useKeyLevels } from "@/hooks/useKeyLevels";

import { memoizeLast } from "./memo";

describe("memoizeLast", () => {
  it("answers again from the last result while the arguments are the same objects", () => {
    const compute = vi.fn((values: number[]) => ({ total: values.reduce((a, b) => a + b, 0) }));
    const memo = memoizeLast(compute);
    const values = [1, 2, 3];
    expect(memo(values)).toBe(memo(values));
    expect(compute).toHaveBeenCalledOnce();
  });

  it("computes again when any argument is a different object", () => {
    const compute = vi.fn((values: number[], scale: number) => values.map((v) => v * scale));
    const memo = memoizeLast(compute);
    memo([1], 2);
    memo([1], 2); // an equal array, not the same one
    memo([1], 3);
    expect(compute).toHaveBeenCalledTimes(3);
  });
});

describe("useKeyLevels", () => {
  it("gives every reader in a render the same computation", () => {
    // The chart, the sidebar and the top panel all read the levels on every
    // bar; three per-hook memos meant three builds of the ladder a second.
    const first = renderHook(() => useKeyLevels()).result.current;
    const second = renderHook(() => useKeyLevels()).result.current;
    expect(second).toBe(first);
  });
});
