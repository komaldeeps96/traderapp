import { expect, test } from '../../fixtures/test';

/**
 * The insiders tab.
 *
 * Every test here is about one separation: payroll is not conviction. A
 * vest, an option exercise and shares withheld for tax move the share count
 * and say nothing, and counting them is how "insiders dumped stock" gets
 * written about a vesting date.
 */
test.describe('insiders', () => {
  test.beforeEach(async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('main-tab-ownership').click();
    await expect(terminal.page.getByTestId('ownership-tab')).toBeVisible();
  });

  test('leads with the read, not the rows', async ({ terminal }) => {
    await expect(terminal.page.getByTestId('insider-verdict')).toContainText(
      'both sides of the market',
    );
  });

  test('keeps compensation out of the buying and selling', async ({ terminal }) => {
    const comp = terminal.page.getByTestId('insider-comp');
    await expect(comp).toContainText('$4.85M');
    // And it is not folded into either side.
    await expect(terminal.page.getByTestId('insider-buys')).toContainText('$25.0K');
    await expect(terminal.page.getByTestId('insider-sells')).toContainText('$10.0K');
  });

  test('separates a scheduled sale from a decided one', async ({ terminal }) => {
    // A 10b5-1 sale is set months ahead and is as automatic as payroll.
    await expect(terminal.page.getByTestId('insider-planned')).toContainText('$447.5K');
  });

  test('marks the planned rows in the table', async ({ terminal }) => {
    const planned = terminal.page.locator('[data-testid="insider-row-S"]', {
      hasText: 'PLAN',
    });
    await expect(planned).toHaveCount(1);
  });

  test('tones a purchase differently from a vest', async ({ terminal }) => {
    await expect(terminal.page.getByTestId('insider-row-P')).toHaveAttribute(
      'data-intent',
      'buy',
    );
    await expect(terminal.page.getByTestId('insider-row-M')).toHaveAttribute(
      'data-intent',
      'compensation',
    );
  });

  test('shows a dash where a price was never stated', async ({ terminal }) => {
    // An option exercise at zero has no market price, and printing $0 would
    // read as a gift of stock.
    await expect(terminal.page.getByTestId('insider-row-M')).toContainText('—');
  });

  test('says so when a company has no filings', async ({ page, terminal }) => {
    // "No insider buying" and "no filings at all" are different facts.
    await page.route('**/api/ownership/**', (route) =>
      route.fulfill({
        json: { symbol: 'NONE', available: true, note: null, summary: null, trades: [] },
      }),
    );
    await terminal.page.getByTestId('main-tab-chart').click();
    await terminal.page.getByTestId('main-tab-ownership').click();
    await expect(terminal.page.getByTestId('ownership-empty')).toBeVisible();
  });

  test('leaves the chart untouched behind it', async ({ terminal }) => {
    expect((await terminal.chartState()).barCount).toBeGreaterThan(0);
  });
});
