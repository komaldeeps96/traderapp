import { expect, test } from '../../fixtures/test';

/**
 * The tabs that follow the charted symbol.
 *
 * Two rules they all keep: the previous company is never drawn under the next
 * one while it loads, and a request that failed says so rather than reading as
 * "no filings on record" — an empty answer and a broken one are different facts.
 */

const FAILED = {
  status: 500,
  // Without it the browser hides the status and reports a network failure.
  headers: { 'Access-Control-Allow-Origin': '*' },
  body: 'boom',
};

test.describe('a request that fails says so', () => {
  test.beforeEach(async ({ terminal }) => {
    await terminal.waitForChart();
  });

  for (const tab of ['ownership', 'peers', 'financials', 'metrics'] as const) {
    test(`on the ${tab} tab`, async ({ page, terminal }) => {
      await page.route(`**/api/${tab}/**`, (route) => route.fulfill(FAILED));
      await terminal.page.getByTestId(`main-tab-${tab}`).click();
      await expect(terminal.page.getByTestId(`${tab}-error`)).toContainText('server answered 500');
      await expect(terminal.page.getByTestId(`${tab}-empty`)).toHaveCount(0);
    });
  }

  test('on the fundamentals dock', async ({ page, terminal }) => {
    await page.route('**/api/fundamentals/**', (route) => route.fulfill(FAILED));
    await terminal.dockTab('fundamentals').click();
    await expect(terminal.dockPanel('fundamentals')).toContainText('server answered 500');
    await expect(terminal.dockPanel('fundamentals')).not.toContainText('files nothing');
  });
});

test.describe('switching symbol', () => {
  test('clears the previous company while the next one loads', async ({ page, terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('main-tab-ownership').click();
    await expect(terminal.page.getByTestId('insider-verdict')).toBeVisible();

    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route('**/api/ownership/TSLA', async (route) => {
      await held;
      await route.fallback();
    });

    await terminal.setSymbol('TSLA');
    await expect(terminal.page.getByTestId('insider-verdict')).toHaveCount(0);

    release();
    await expect(terminal.page.getByTestId('insider-verdict')).toBeVisible();
  });

  test('clears the previous company from the fundamentals dock too', async ({ page, terminal }) => {
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
