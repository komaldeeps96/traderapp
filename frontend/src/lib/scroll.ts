/**
 * Scroll arithmetic, kept out of the components so it can be tested: jsdom has
 * no layout engine, so anything reading geometry inside a component needs a
 * browser. The component keeps only the measuring.
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
 * Clamped at both ends: a row with little above it cannot be centred, so it
 * settles as high as the content allows rather than being padded down with
 * blank space.
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
