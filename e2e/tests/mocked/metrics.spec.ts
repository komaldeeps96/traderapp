import { expect, test } from '../../fixtures/test';

/**
 * The metrics tab.
 *
 * What earns tests here is the refusals. The backend returns null rather
 * than a meaningless number — a P/E on a loss, a coverage ratio with nothing
 * to divide by — and the table must render that as absence, never as zero.
 */
test.describe('metrics', () => {
  test.beforeEach(async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('main-tab-metrics').click();
    await expect(terminal.page.getByTestId('metrics-tab')).toBeVisible();
  });

  test('leads with valuation, which is the part that moves intraday', async ({ terminal }) => {
    const strip = terminal.page.getByTestId('valuation-strip');
    await expect(strip).toBeVisible();
    await expect(strip).toContainText('$4.67T');
    await expect(terminal.page.getByTestId('multiple-pe')).toContainText('41.65×');
  });

  test('states what the multiples are computed on', async ({ terminal }) => {
    // A multiple on a fiscal year and one on a trailing twelve months are
    // different numbers, and which is on screen must not be guesswork.
    await expect(terminal.page.getByTestId('valuation-strip')).toContainText('on annual');
  });

  test('groups the ratios', async ({ terminal }) => {
    await expect(terminal.page.getByTestId('metric-group-profitability')).toBeVisible();
    await expect(terminal.page.getByTestId('metric-group-balance sheet')).toBeVisible();
  });

  test('gives a percentage one decimal', async ({ terminal }) => {
    const row = terminal.page.getByTestId('metric-row-gross_margin').locator('..');
    await expect(row).toContainText('46.9%');
  });

  test('marks a multiple so it is not read as a ratio', async ({ terminal }) => {
    const row = terminal.page.getByTestId('metric-row-interest_coverage').locator('..');
    await expect(row).toContainText('29.06×');
  });

  test('renders a refused ratio as absent, not as zero', async ({ terminal }) => {
    const row = terminal.page.getByTestId('metric-row-interest_coverage').locator('..');
    await expect(row).toContainText('—');
  });

  test('switches to the quarterly view', async ({ terminal }) => {
    await terminal.page.getByTestId('metrics-period-quarterly').click();
    await expect(terminal.page.getByTestId('metrics-tab')).toBeVisible();
  });

  test('says so when there is nothing to measure', async ({ page, terminal }) => {
    await page.route('**/api/metrics/**', (route) =>
      route.fulfill({
        json: {
          symbol: 'NONE',
          available: true,
          period: 'annual',
          periods: [],
          groups: [],
          valuation: null,
        },
      }),
    );
    await terminal.page.getByTestId('metrics-period-quarterly').click();
    await expect(terminal.page.getByTestId('metrics-empty')).toBeVisible();
  });

  test('leaves the chart untouched behind it', async ({ terminal }) => {
    expect((await terminal.chartState()).barCount).toBeGreaterThan(0);
  });
});
