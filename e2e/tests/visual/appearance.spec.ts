import { expect, test } from '../../fixtures/test';

/**
 * Visual regression.
 *
 * Fixture data is seeded, the timezone is pinned in the Playwright config and
 * the session date is fixed, so these renders are reproducible. Regenerate with
 * `npx playwright test --project=visual --update-snapshots=all` — the bare flag
 * only rewrites baselines whose comparison *failed*, and a small component
 * change lands inside the tolerance without failing.
 *
 * The session clock shows real wall-clock time and is masked out of every
 * frame. The bar countdown is painted into each chart's price axis where a mask
 * cannot reach it, so the clock is frozen instead.
 */

/** Mid-bar on every timeframe, so no chip is caught mid-flip. */
const FROZEN = new Date('2024-03-05T15:15:04Z');

/**
 * Stop the clock and wait for the countdowns to settle on it. `setFixedTime`
 * freezes the time-reading APIs without faking timers, so the charts keep
 * polling and keep reading the same instant.
 */
async function freezeClock(terminal: { page: import('@playwright/test').Page }) {
  await terminal.page.clock.setFixedTime(FROZEN);
  await expect
    .poll(async () =>
      terminal.page.evaluate(
        () => (window.__traderapp!.chart() as { countdown: { text: string } | null }).countdown?.text,
      ),
    )
    .toBe('6s');
}

/**
 * Tolerance is deliberately tight. At 2%, moving a whole control strip across
 * the chart diffs only ~0.7% of the frame and still passes. 0.4% absorbs
 * antialiasing but notices a component changing place or disappearing.
 */
const TOLERANCE = { maxDiffPixelRatio: 0.004, animations: 'disabled' as const };

test.describe('appearance', () => {
  test('dark theme — the default', async ({ terminal }) => {
    await terminal.waitForChart();
    // A chip on the toolbar is about 0.02% of this frame — three times under
    // the tolerance — so it could vanish entirely and the comparison would
    // still pass. Its presence is asserted rather than assumed, and so is the
    // dock's tab strip, where a tab added or removed is the same size of
    // change.
    await expect(terminal.page.getByTestId('news-ai-toggle')).toBeVisible();
    await expect(terminal.dockTabs()).toHaveCount(4);
    await freezeClock(terminal);
    await terminal.moveMouseAway();
    await expect(terminal.page).toHaveScreenshot('terminal-dark.png', {
      ...TOLERANCE,
      fullPage: false,
      mask: [terminal.page.getByTestId('session-clock')],
    });
  });

  test('light theme', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('news-ai-toggle')).toBeVisible();
    await expect(terminal.dockTabs()).toHaveCount(4);
    await terminal.themeToggle.click();
    await expect.poll(async () => (await terminal.chartState()).theme).toBe('light');
    await freezeClock(terminal);
    await terminal.moveMouseAway();

    await expect(terminal.page).toHaveScreenshot('terminal-light.png', {
      ...TOLERANCE,
      fullPage: false,
      mask: [terminal.page.getByTestId('session-clock')],
    });
  });

  test('the sidebar', async ({ terminal }) => {
    // DOM-rendered, so this is the stricter of the two checks.
    //
    // Named rather than bare `complementary`: the mini-chart column is an
    // aside too, so the bare role matches two elements and the comparison
    // stopped running rather than failing loudly.
    await terminal.waitForChart();
    // A third tab is well inside the pixel tolerance, so the screenshot alone
    // would happily pass against a two-tab baseline. Asserted, then compared.
    await expect(terminal.page.getByTestId('scanner-tab-watch')).toBeVisible();
    await terminal.moveMouseAway();
    const sidebar = terminal.page.getByRole('complementary', { name: 'Market tools' });
    await expect(sidebar).toHaveScreenshot('sidebar-dark.png', {
      maxDiffPixelRatio: 0.01,
      animations: 'disabled',
    });
  });

  test('the top panel', async ({ terminal }) => {
    await terminal.waitForChart();
    // Same reasoning as the sidebar's tab: one star is far too small to move
    // the diff ratio, so its presence is asserted rather than assumed.
    await expect(terminal.page.getByTestId('watch-star')).toBeVisible();
    await terminal.moveMouseAway();
    await expect(terminal.page.getByTestId('top-panel')).toHaveScreenshot('top-panel-dark.png', {
      maxDiffPixelRatio: 0.01,
      animations: 'disabled',
    });
  });
});

/**
 * The bar countdown, at the scale it is actually read.
 *
 * The full-terminal shots contain it, but three chips are ~0.13% of that frame
 * — inside the tolerance, so they could vanish and still pass. This crops to
 * the price axis around the last-price label, where absence is a failure.
 */
test.describe('bar countdown', () => {
  test('sits under the last-price label', async ({ terminal }) => {
    await terminal.waitForChart();
    await freezeClock(terminal);
    await terminal.moveMouseAway();

    // Measured off the chart rather than hardcoded, so the column widths either
    // side can change without cropping the wrong pixels.
    //
    // Cropped to the price axis and no wider: candles inside the plot land a
    // pixel either way depending on the width the container reports on first
    // paint, which fails the comparison on the bars rather than its subject.
    const box = (await terminal.chart.boundingBox())!;
    await expect(terminal.page).toHaveScreenshot('countdown-axis-dark.png', {
      animations: 'disabled',
      maxDiffPixelRatio: 0.01,
      clip: { x: box.x + box.width - 56, y: box.y + 380, width: 56, height: 280 },
    });
  });
});
