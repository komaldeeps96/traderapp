import { makeFinancials, makeMetrics } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/**
 * Foreign private issuers.
 *
 * A company filing a 40-F or 20-F tags under `ifrs-full` rather than
 * `us-gaap`, in its own currency. The facts were always in the same free
 * `companyfacts` payload the terminal already fetched — the tabs were empty
 * because the parser looked in one taxonomy, and that is most of the
 * Canadian small-cap universe.
 *
 * What has to hold once they render: the currency is stated, and nothing
 * silently mixes it with the USD market cap.
 */

const CANADIAN = {
  ...makeFinancials(),
  currency: 'CAD',
  symbol_prefix: '$',
  statements: [
    {
      key: 'income',
      label: 'Income statement',
      lines: [
        {
          key: 'revenue',
          label: 'Revenue',
          unit: 'CAD',
          concepts: ['Revenue'],
          values: [946_400_000, 920_450_000],
        },
        {
          key: 'eps_diluted',
          label: 'EPS, diluted',
          unit: 'CAD/shares',
          concepts: ['DilutedEarningsLossPerShare'],
          values: [-0.06, -0.36],
        },
      ],
    },
  ],
};

test.describe('a filer reporting in another currency', () => {
  // `terminal` is requested so the mock backend's own routes are installed
  // first: Playwright uses the last matching route registered, and a hook
  // asking only for `page` registers before the fixtures and loses.
  test.beforeEach(async ({ page, terminal }) => {
    await terminal.waitForChart();
    await page.route('**/api/financials/**', (route) => route.fulfill({ json: CANADIAN }));
  });

  test('says which currency the statements are in', async ({ terminal }) => {
    // A figure with no currency beside it cannot be compared to anything.
    await terminal.page.getByTestId('main-tab-financials').click();
    await expect(terminal.page.getByTestId('financials-currency')).toContainText('CAD');
  });

  test('does not put per-share figures through the money branch', async ({ terminal }) => {
    // The unit is "CAD/shares", not "USD/shares". Matching the literal sent
    // an EPS of -0.06 down the money path, where it rendered as "-$0".
    await terminal.page.getByTestId('main-tab-financials').click();
    const eps = terminal.page.getByTestId('financials-row-eps_diluted').locator('..');
    await expect(eps).toContainText('-0.06');
  });
});

test.describe('valuation across a currency boundary', () => {
  test.beforeEach(async ({ page, terminal }) => {
    await terminal.waitForChart();
    await page.route('**/api/metrics/**', (route) =>
      route.fulfill({
        json: {
          ...makeMetrics(),
          currency: 'CAD',
          valuation: {
            market_cap: 336_450_000,
            enterprise_value: null,
            basis: 'annual',
            note: 'Statements are in CAD and the market cap is in USD; multiples would be wrong by the exchange rate.',
            multiples: [
              { key: 'pe', label: 'P/E', value: null },
              { key: 'ps', label: 'P/S', value: null },
            ],
          },
        },
      }),
    );
  });

  test('refuses the multiples rather than computing them wrong', async ({ terminal }) => {
    // A P/E of 12 where the truth is 17 looks like nothing at all.
    await terminal.page.getByTestId('main-tab-metrics').click();
    await expect(terminal.page.getByTestId('multiple-pe')).toContainText('—');
  });

  test('says why, so the dashes do not read as missing data', async ({ terminal }) => {
    await terminal.page.getByTestId('main-tab-metrics').click();
    await expect(terminal.page.getByTestId('valuation-note')).toContainText('exchange rate');
  });

  test('still shows the ratios that need no conversion', async ({ terminal }) => {
    // A margin is one currency over itself, so it is still a fact.
    await terminal.page.getByTestId('main-tab-metrics').click();
    const margin = terminal.page.getByTestId('metric-row-gross_margin').locator('..');
    await expect(margin).toContainText('46.9%');
  });
});
