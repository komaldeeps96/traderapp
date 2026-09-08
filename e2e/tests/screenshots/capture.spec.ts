import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { makePosition, makeScannerRows, type TapePrintFixture } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/**
 * The screenshots in the README, captured rather than taken by hand.
 *
 * A README image is documentation with no test behind it: the UI moves, the
 * PNG does not, and nobody notices until a reader is looking at a screenshot
 * of a terminal that no longer exists. These come out of the same seeded
 * fixtures and frozen clock the visual baselines use, so `npm run screenshots`
 * regenerates the lot against whatever the code currently renders.
 *
 * Skipped unless asked for. It writes into the repository rather than into
 * `test-results/`, and a full `playwright test` sweep should not leave the
 * working tree dirty — so the capture runs only under `npm run screenshots`.
 */
const CAPTURING = Boolean(process.env.TRADERAPP_CAPTURE);

/**
 * Where the README reads them from. Resolved against *this file* rather than
 * written as a relative path: Playwright resolves a relative screenshot path
 * against the working directory, which is `e2e/`, and "../../../docs" from
 * there lands outside the repository entirely.
 */
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), '../../../docs/screenshots');

/** Mid-bar on every timeframe, so no countdown chip is caught mid-flip. */
const FROZEN = new Date('2024-03-05T15:15:04Z');

/**
 * The terminal as it looks when everything it talks to is up.
 *
 * Both of these are off in the fixtures by default, and correctly so — the
 * scanner needs a running TWS and the order strip is not rendered at all
 * until the server says trading is armed, which is the state every other
 * suite asserts against. A screenshot of that default is four "requires IBKR"
 * notices down the left rail and no strip, which is a true picture of an
 * unconfigured machine and a poor picture of the application.
 */
const ARMED = {
  enabled: true,
  connected: true,
  account: 'DU1234',
  paper: true,
  // Held, not flat. With no position the three sell buttons read "flat" and
  // are dead, so half the strip is greyed out in the picture — a true state,
  // and not the one worth showing.
  positions: [makePosition('AAPL', 14)],
};
// `source` matters as much as `scannerAvailable`: the scanners are an IBKR
// feature and stay disabled while the router reports Alpaca.
const RUNNING = { scannerAvailable: true, source: 'ibkr' as const, trading: ARMED };

/**
 * A tape long enough to look like one.
 *
 * The shared fixture is deliberately one row of each verdict — the specs
 * assert on tints and filters, so it is a truth table rather than a stream.
 * That reads as a nearly empty window in a screenshot, so this fills the
 * pane with a plausible burst instead. Fixed arithmetic, no randomness: the
 * image has to come out the same on the next capture.
 */
function burst(count = 26): TapePrintFixture[] {
  const base = 1_709_651_400_000; // 09:30 NY on the fixtures' session.
  const sides = ['ask', 'ask', 'bid', 'above', 'ask', 'bid', 'mid', 'below'] as const;
  const sizes = [100, 200, 500, 1_500, 100, 300, 2_500, 100, 800, 5_000];
  const ticks = [0, 1, 2, 1, 0, -1, -2, -1, 0, 1, 2, 3];
  return Array.from({ length: count }, (_, i) => ({
    q: i + 1,
    t: base + i * 700,
    p: Number((10.04 + ticks[i % ticks.length] * 0.01).toFixed(2)),
    s: sizes[i % sizes.length],
    a: sides[i % sides.length],
    x: ['Q', 'K', 'D', 'P', 'N'][i % 5],
  }));
}

/**
 * Fill the four market-cap scanners.
 *
 * `scannerAvailable` only removes the "requires IBKR" notice; the rows
 * themselves arrive as pushed frames, exactly as they do from a live TWS.
 */
async function fillScanners(backend: {
  pushScanner: (id: 'small_cap' | 'mid_cap' | 'large_cap' | 'mega_cap',
    rows?: ReturnType<typeof makeScannerRows>) => Promise<void>;
}) {
  await backend.pushScanner('small_cap', makeScannerRows(5));
  await backend.pushScanner('mid_cap', makeScannerRows(4));
  await backend.pushScanner('large_cap', makeScannerRows(3));
  await backend.pushScanner('mega_cap', makeScannerRows(3));
}

/**
 * The dock, cropped to where its content actually ends.
 *
 * The dock is full window height whatever is in it, so a panel that fills the
 * top third screenshots as two thirds empty background. Clipping to the last
 * element that rendered keeps the image about the panel rather than about the
 * column it lives in.
 */
async function shootDock(
  terminal: { page: import('@playwright/test').Page; dock: import('@playwright/test').Locator },
  last: import('@playwright/test').Locator,
  name: string,
) {
  const [dock, end] = await Promise.all([terminal.dock.boundingBox(), last.boundingBox()]);
  await terminal.page.screenshot({
    path: `${OUT}/${name}.png`,
    clip: {
      x: dock!.x,
      y: dock!.y,
      width: dock!.width,
      height: Math.min(end!.y + end!.height + 8 - dock!.y, dock!.height),
    },
  });
}

async function settle(terminal: { page: import('@playwright/test').Page }) {
  await terminal.page.clock.setFixedTime(FROZEN);
  await expect
    .poll(async () =>
      terminal.page.evaluate(
        () => (window.__traderapp!.chart() as { countdown: { text: string } | null }).countdown?.text,
      ),
    )
    .toBe('6s');
}

test.describe('screenshots', () => {
  test.skip(!CAPTURING, 'Run `npm run screenshots` to regenerate the README images.');
  test.use({ backendOptions: { ...RUNNING, tape: burst() } });

  test('the terminal', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await fillScanners(backend);
    await settle(terminal);
    await terminal.moveMouseAway();
    await terminal.page.screenshot({ path: `${OUT}/terminal.png` });
  });

  test('the terminal in light', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await fillScanners(backend);
    await terminal.themeToggle.click();
    await expect.poll(async () => (await terminal.chartState()).theme).toBe('light');
    await settle(terminal);
    await terminal.moveMouseAway();
    await terminal.page.screenshot({ path: `${OUT}/terminal-light.png` });
  });

  test('the AI tab', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('ai').click();
    await expect(terminal.page.getByTestId('ai-score')).toBeVisible();
    await settle(terminal);
    await terminal.moveMouseAway();
    await shootDock(terminal, terminal.page.getByTestId('ai-watch'), 'ai-tab');
  });

  test('the news tab, read and scored', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();
    await expect(terminal.page.getByTestId('news-brief-score')).toBeVisible();
    await settle(terminal);
    await terminal.moveMouseAway();
    await shootDock(terminal, terminal.page.getByTestId('news-row').last(), 'news-brief');
  });

  test('the tape', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.tapeRows().first()).toBeVisible();
    await settle(terminal);
    await terminal.moveMouseAway();
    await shootDock(terminal, terminal.tape, 'tape');
  });

  test('the order strip', async ({ terminal }) => {
    await terminal.waitForChart();
    const strip = terminal.page.getByTestId('order-panel');
    await expect(strip).toBeVisible();
    await settle(terminal);
    await terminal.moveMouseAway();
    await strip.screenshot({ path: `${OUT}/order-strip.png` });
  });
});
