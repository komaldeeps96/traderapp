import { expect, test } from '../../fixtures/test';

/**
 * The fundamentals dock follows the charted symbol.
 *
 * The previous company is never drawn under the next one while it loads, and a
 * request that failed says so rather than reading as "files nothing" — an
 * empty answer and a broken one are different facts.
 */

const FAILED = {
  status: 500,
  // Without it the browser hides the status and reports a network failure.
  headers: { 'Access-Control-Allow-Origin': '*' },
  body: 'boom',
};

test.describe('a request that fails says so', () => {
  test('on the fundamentals dock', async ({ page, terminal }) => {
    await terminal.waitForChart();
    await page.route('**/api/fundamentals/**', (route) => route.fulfill(FAILED));
    await terminal.dockTab('fundamentals').click();
    await expect(terminal.dockPanel('fundamentals')).toContainText('server answered 500');
    await expect(terminal.dockPanel('fundamentals')).not.toContainText('files nothing');
  });
});

test.describe('switching symbol', () => {
  test('clears the previous company from the fundamentals dock', async ({ page, terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();
    await expect(terminal.page.getByTestId('dilution-tone')).toBeVisible();

    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route('**/api/fundamentals/TSLA', async (route) => {
      await held;
      await route.fallback();
    });

    await terminal.setSymbol('TSLA');
    await expect(terminal.dockPanel('fundamentals')).toContainText('Loading TSLA');
    await expect(terminal.page.getByTestId('dilution-tone')).toHaveCount(0);

    release();
    await expect(terminal.page.getByTestId('dilution-tone')).toBeVisible();
  });
});
