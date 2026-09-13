/**
 * The contract every symbol-bound tab relies on: nothing from the previous
 * symbol on screen under the next, and a failure never passed off as an empty
 * answer ("no Form 4 filings on record" for what was a 500).
 */

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/http";

import { useSymbolResource } from "./useSymbolResource";

interface Pending {
  resolve: (value: string) => void;
  reject: (error: unknown) => void;
  signal: AbortSignal;
}

function harness() {
  const requests = new Map<string, Pending>();
  const loaderFor = (key: string) => (signal: AbortSignal) =>
    new Promise<string>((resolve, reject) => {
      requests.set(key, { resolve, reject, signal });
    });
  const hook = renderHook(
    ({ key }: { key: string }) => useSymbolResource(key, loaderFor(key)),
    { initialProps: { key: "AAPL" } },
  );
  return { requests, ...hook };
}

/** Settle a request, and let React render what it produced. */
async function settle(action: () => void): Promise<void> {
  await act(async () => {
    action();
    await Promise.resolve();
  });
}

describe("useSymbolResource", () => {
  it("shows nothing from the previous symbol while the next loads", async () => {
    const { requests, result, rerender } = harness();
    await settle(() => requests.get("AAPL")!.resolve("apple"));
    expect(result.current.data).toBe("apple");

    rerender({ key: "TSLA" });
    expect(result.current).toEqual({ data: null, error: null, loading: true });

    await settle(() => requests.get("TSLA")!.resolve("tesla"));
    expect(result.current).toEqual({ data: "tesla", error: null, loading: false });
  });

  it("drops an answer that arrives for a symbol already left", async () => {
    const { requests, result, rerender } = harness();
    rerender({ key: "TSLA" });
    await settle(() => requests.get("AAPL")!.resolve("apple"));
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
  });

  it("aborts the request it no longer wants", () => {
    const { requests, rerender } = harness();
    rerender({ key: "TSLA" });
    expect(requests.get("AAPL")!.signal.aborted).toBe(true);
    expect(requests.get("TSLA")!.signal.aborted).toBe(false);
  });

  it("reports a failure as an error, not as an empty answer", async () => {
    const { requests, result } = harness();
    await settle(() => requests.get("AAPL")!.reject(new ApiError("boom", 500)));
    expect(result.current).toEqual({
      data: null,
      error: "the server answered 500",
      loading: false,
    });
  });

  it("names an unreachable backend as that", async () => {
    const { requests, result } = harness();
    await settle(() => requests.get("AAPL")!.reject(new TypeError("Failed to fetch")));
    expect(result.current.error).toBe("the backend could not be reached");
  });

  it("stays idle with nothing to fetch", () => {
    const { requests, result, rerender } = harness();
    requests.clear();
    rerender({ key: "" });
    expect(result.current).toEqual({ data: null, error: null, loading: false });
    expect(requests.size).toBe(0);
  });
});
