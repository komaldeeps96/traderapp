import { describe, expect, it } from 'vitest';

import { centredScrollTop } from './scroll';

/**
 * The key levels panel puts the last-price row in the middle of the list.
 *
 * The rules that matter are the two clamps: a book with nothing overhead
 * cannot be centred, and it should read at the top rather than be pushed into
 * the middle by empty space.
 */
describe('centredScrollTop', () => {
  // A 300px window over 1000px of rows, each row 20px tall.
  const panel = { rowHeight: 20, viewportHeight: 300, contentHeight: 1000 };

  it('centres a row with room on both sides', () => {
    // 500 - (300 - 20) / 2 = 360
    expect(centredScrollTop({ ...panel, rowOffset: 500 })).toBe(360);
  });

  it('leaves the row at the top when little sits above it', () => {
    // The gapper case in reverse: nothing overhead, so there is nothing to
    // scroll past and the price belongs at the top of the list.
    expect(centredScrollTop({ ...panel, rowOffset: 40 })).toBe(0);
  });

  it('leaves the row at the bottom when little sits below it', () => {
    expect(centredScrollTop({ ...panel, rowOffset: 960 })).toBe(700);
  });

  it('does not scroll a list that fits', () => {
    expect(
      centredScrollTop({ ...panel, rowOffset: 100, contentHeight: 250 }),
    ).toBe(0);
  });

  it('never scrolls past the end of the content', () => {
    const furthest = panel.contentHeight - panel.viewportHeight;
    for (let rowOffset = 0; rowOffset <= panel.contentHeight; rowOffset += 25) {
      const top = centredScrollTop({ ...panel, rowOffset });
      expect(top).toBeGreaterThanOrEqual(0);
      expect(top).toBeLessThanOrEqual(furthest);
    }
  });

  it('puts a deeply buried row in the middle of the viewport', () => {
    // What the panel is for: 24 levels overhead should not mean scrolling to
    // find the price. Centred means the row lands mid-viewport.
    const rowOffset = 480;
    const top = centredScrollTop({ ...panel, rowOffset });
    const rowCentreOnScreen = rowOffset - top + panel.rowHeight / 2;
    expect(rowCentreOnScreen).toBeCloseTo(panel.viewportHeight / 2, 5);
  });
});
