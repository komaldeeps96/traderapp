import { expect, test } from '../../fixtures/test';

/**
 * Visual regression.
 *
 * The fixture data is seeded, the timezone is pinned in the Playwright config,
 * and the session date is fixed, so these renders are reproducible. Baselines
 * are written on the first run and committed; regenerate deliberately with
 * `npx playwright test --project=visual --update-snapshots`.
 *
 * The session clock shows real wall-clock time, so it is masked out of every
 * frame. The bar countdown is painted into each chart's price axis, where a
 * mask cannot reach it, so the clock is frozen instead — otherwise three
 * chips would read a different number on every run and the baseline could
 * never match twice.
 */

/** Mid-bar on every timeframe, so no chip is caught mid-flip. */
const FROZEN = new Date('2024-03-05T15:15:04Z');

/**
 * Stop the clock and wait for the countdowns to settle on it.
 *
 * `setFixedTime` freezes the time-reading APIs without faking timers, so the
 * charts keep polling — they just keep reading the same instant. One poll
 * interval later every chip is stable.
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
 * Tolerance is deliberately tight. At 2% a whole control strip could be moved
 * across the chart and the comparison still passed — the diff was only ~0.7%
 * of the frame — so the suite was green without checking anything. 0.4% still
 * absorbs antialiasing but notices a component changing place or disappearing.
 */
const TOLERANCE = { maxDiffPixelRatio: 0.004, animations: 'disabled' as const };

test.describe('appearance', () => {
  test('dark theme — the default', async ({ terminal }) => {
    await terminal.waitForChart();
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
    await terminal.moveMouseAway();
    const sidebar = terminal.page.getByRole('complementary', { name: 'Market tools' });
    await expect(sidebar).toHaveScreenshot('sidebar-dark.png', {
      maxDiffPixelRatio: 0.01,
      animations: 'disabled',
    });
  });

  test('the top panel', async ({ terminal }) => {
    await terminal.waitForChart();
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
 * The full-terminal shots do contain it, but three chips are about 0.13% of
 * that frame — well inside the tolerance, so they could vanish entirely and
 * the comparison would still pass. This crops to the strip of price axis
 * around the last-price label, where the chip is a few percent of the frame
 * and its absence is a failure.
 */
test.describe('bar countdown', () => {
  test('sits under the last-price label', async ({ terminal }) => {
    await terminal.waitForChart();
    await freezeClock(terminal);
    await terminal.moveMouseAway();

    // Measured off the chart rather than hardcoded, so the column widths
    // either side can change without silently cropping the wrong pixels.
    //
    // Cropped to the price axis and no wider. An earlier version reached 110px
    // into the plot, and the candles in that strip land a pixel or two either
    // way depending on what width the container reports on first paint — so
    // the comparison failed on the bars rather than on its own subject, and
    // the baseline was rewritten every few runs. The axis labels are stable.
    const box = (await terminal.chart.boundingBox())!;
    await expect(terminal.page).toHaveScreenshot('countdown-axis-dark.png', {
      animations: 'disabled',
      maxDiffPixelRatio: 0.01,
      clip: { x: box.x + box.width - 56, y: box.y + 380, width: 56, height: 280 },
    });
  });
});
