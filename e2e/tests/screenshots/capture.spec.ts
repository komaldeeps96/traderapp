import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { makePosition, makeScannerRows } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/**
 * The screenshots in the README, captured rather than taken by hand. They come
 * out of the same seeded fixtures and frozen clock the visual baselines use, so
 * `npm run screenshots` regenerates the lot against what the code renders now.
 *
 * Skipped unless asked for: it writes into the repository rather than
 * `test-results/`, and a full sweep should not leave the tree dirty.
 */
const CAPTURING = Boolean(process.env.TRADERAPP_CAPTURE);

/**
 * Where the README reads them from. Resolved against *this file*: Playwright
 * resolves a relative screenshot path against the working directory, `e2e/`,
 * from which "../../../docs" lands outside the repository.
 */
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), '../../../docs/screenshots');

/** Mid-bar on every timeframe, so no countdown chip is caught mid-flip. */
const FROZEN = new Date('2024-03-05T15:15:04Z');

/**
 * The terminal as it looks when everything it talks to is up.
 *
 * Both are off in the fixtures by default — the scanner needs a running TWS and
 * the order strip is not rendered until the server says trading is armed, which
 * is what every other suite asserts against. That default screenshots as four
 * "requires IBKR" notices and no strip.
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
 * Fill the four market-cap scanners. `scannerAvailable` only removes the
 * "requires IBKR" notice; the rows arrive as pushed frames, as from a live TWS.
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
 * The dock, cropped to where its content ends. It is full window height
 * whatever is in it, so a panel filling the top third would screenshot as two
 * thirds empty background.
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
  test.use({ backendOptions: RUNNING });

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

  test('the news tab, read and scored', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();
    await expect(terminal.page.getByTestId('news-brief-score')).toBeVisible();
    await settle(terminal);
    await terminal.moveMouseAway();
    await shootDock(terminal, terminal.page.getByTestId('news-row').last(), 'news-brief');
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
