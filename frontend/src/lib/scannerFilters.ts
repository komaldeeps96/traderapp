/**
 * A scanner filter field, as typed.
 *
 * Blank clears the filter. Thousands separators are accepted, because "1,000"
 * is how a trade rate gets typed, and anything that still is not a number is
 * reported rather than quietly sent as a cleared filter.
 */
export type ParsedFilter = { value: number | "clear" } | { invalid: true };

export function parseFilter(
  raw: string,
  { scale = 1, integer = false }: { scale?: number; integer?: boolean } = {},
): ParsedFilter {
  const cleaned = raw.trim().replace(/[,_\s]/g, "");
  if (!cleaned) return { value: "clear" };
  const value = Number(cleaned);
  if (!Number.isFinite(value) || (integer && !Number.isInteger(value))) {
    return { invalid: true };
  }
  return { value: value * scale };
}
