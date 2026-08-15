/**
 * Scroll arithmetic, kept out of the components so it can be tested.
 *
 * jsdom has no layout engine — every box measures zero — so anything that
 * reads geometry inside a component is untestable without a browser. Pulling
 * the sums out means the clamping rules can be pinned properly and the
 * component keeps only the measuring.
 */

export interface CentreScrollInput {
  /** Distance from the top of the scrollable content to the row. */
  rowOffset: number;
  rowHeight: number;
  /** Visible height of the scroll container. */
  viewportHeight: number;
  /** Total height of its content. */
  contentHeight: number;
}

/**
 * Where to scroll so a row sits in the middle of its container.
 *
 * Clamped at both ends, and that clamp is the interesting part: a row with
 * little above it cannot be centred, because there is nothing to scroll past.
 * It settles as high as the content allows rather than being pushed down with
 * blank space — so a price with no levels overhead reads at the top of the
 * list, which is where it belongs.
 */
export function centredScrollTop({
  rowOffset,
  rowHeight,
  viewportHeight,
  contentHeight,
}: CentreScrollInput): number {
  const centred = rowOffset - (viewportHeight - rowHeight) / 2;
  const furthest = Math.max(0, contentHeight - viewportHeight);
  return Math.max(0, Math.min(centred, furthest));
}
