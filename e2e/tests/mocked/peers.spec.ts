import { expect, test } from '../../fixtures/test';

/**
 * The peers tab.
 *
 * A ratio on its own is not a judgement — 39x earnings is expensive for a
 * utility and cheap for a chip designer — so what is tested here is the
 * comparison: the rank, the industry median beside it, and the fact that a
 * company which reports nothing is left out rather than ranked last.
 */
test.describe('peers', () => {
  test.beforeEach(async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('main-tab-peers').click();
    await expect(terminal.page.getByTestId('peers-tab')).toBeVisible();
  });

  test('names the industry it is comparing against', async ({ terminal }) => {
    await expect(terminal.page.getByTestId('peers-industry')).toContainText(
      'Telecommunications Equipment',
    );
  });

  test('marks the company being looked at', async ({ terminal }) => {
    await expect(terminal.page.getByTestId('peer-row-AAPL')).toHaveAttribute(
      'data-subject',
      'true',
    );
    await expect(terminal.page.getByTestId('peer-row-CSCO')).toHaveAttribute(
      'data-subject',
      'false',
    );
  });

  test('ranks against the industry, with the median beside it', async ({ terminal }) => {
    const rank = terminal.page.getByTestId('peer-rank-price_book');
    await expect(rank).toContainText('27/28');
    await expect(rank).toContainText('2.33×');
  });

  test('reads a percentage as a percentage', async ({ terminal }) => {
    // The endpoint emits fractions. A second conversion in the UI produced
    // an industry median return on equity of 690%.
    const rank = terminal.page.getByTestId('peer-rank-return_on_equity');
    await expect(rank).toContainText('4.9%');
  });

  test('leaves an unranked measure blank rather than guessing', async ({ terminal }) => {
    // A company that does not report earnings has no P/E and no rank; a
    // middle position would be an invention.
    await expect(terminal.page.getByTestId('peer-rank-price_earnings')).toContainText('—');
  });

  test('shows a dash where a peer reports nothing', async ({ terminal }) => {
    await expect(terminal.page.getByTestId('peer-row-CSCO')).toContainText('—');
  });

  test('says so when the screener is switched off', async ({ page, terminal }) => {
    await page.route('**/api/peers/**', (route) =>
      route.fulfill({
        json: {
          symbol: 'X',
          available: false,
          industry: '',
          rows: [],
          ranks: [],
          note: null,
        },
      }),
    );
    await terminal.page.getByTestId('main-tab-chart').click();
    await terminal.page.getByTestId('main-tab-peers').click();
    await expect(terminal.page.getByTestId('peers-empty')).toBeVisible();
  });

  test('leaves the chart untouched behind it', async ({ terminal }) => {
    expect((await terminal.chartState()).barCount).toBeGreaterThan(0);
  });
});
