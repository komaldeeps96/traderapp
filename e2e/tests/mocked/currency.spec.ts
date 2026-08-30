import { makeFinancials } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/**
 * Foreign private issuers, restated in dollars.
 *
 * A 40-F or 20-F filer tags under `ifrs-full` and reports in its own
 * currency. Everything else on this screen is quoted in dollars, so those
 * statements are converted rather than captioned and left alone — at each
 * period's own rate, so a 2019 figure is what it was worth in 2019.
 *
 * What has to hold: the conversion is disclosed, and a period whose rate
 * could not be fetched is named rather than dropped into a dollar column.
 */

const CONVERTED = {
  ...makeFinancials(),
  currency: 'USD',
  native_currency: 'CAD',
  converted: true,
  symbol_prefix: '$',
  statements: [
    {
      key: 'income',
      label: 'Income statement',
      lines: [
        {
          key: 'revenue',
          label: 'Revenue',
          unit: 'USD',
          kind: 'money',
          instant: false,
          concepts: ['Revenue'],
          values: [677_100_000, 672_300_000],
        },
        {
          key: 'eps_diluted',
          label: 'EPS, diluted',
          unit: 'USD/shares',
          kind: 'per_share',
          instant: false,
          concepts: ['DilutedEarningsLossPerShare'],
          values: [-0.04, -0.26],
        },
      ],
    },
  ],
};

// `terminal` is requested so the mock backend's own routes install first:
// Playwright uses the last matching route registered, and a hook asking only
// for `page` registers before the fixtures and loses.
test.describe('a filer that reports in another currency', () => {
  test.beforeEach(async ({ page, terminal }) => {
    await terminal.waitForChart();
    await page.route('**/api/financials/**', (route) => route.fulfill({ json: CONVERTED }));
    await terminal.page.getByTestId('main-tab-financials').click();
  });

  test('says the figures were converted, and from what', async ({ terminal }) => {
    // A converted number that does not say so is worse than an unconverted
    // one: it cannot be checked against the filing it came from.
    await expect(terminal.page.getByTestId('financials-currency')).toContainText(
      'converted from CAD',
    );
  });

  test('shows the converted figures in dollars', async ({ terminal }) => {
    const revenue = terminal.page.getByTestId('financials-row-revenue').locator('..');
    await expect(revenue).toContainText('$677.10M');
  });

  test('does not put per-share figures through the money branch', async ({ terminal }) => {
    // Matching the literal 'USD/shares' broke the moment a filer quoted
    // 'CAD/shares'; the check is on shape, and an EPS is never compacted.
    const eps = terminal.page.getByTestId('financials-row-eps_diluted').locator('..');
    await expect(eps).toContainText('-0.04');
  });
});

test.describe('a period with no exchange rate', () => {
  test.beforeEach(async ({ page, terminal }) => {
    await terminal.waitForChart();
    await page.route('**/api/financials/**', (route) =>
      route.fulfill({ json: { ...CONVERTED, unconverted_periods: ['FY2024'] } }),
    );
    await terminal.page.getByTestId('main-tab-financials').click();
  });

  test('is named rather than silently missing', async ({ terminal }) => {
    // A blank column in a converted table reads as "the company reported
    // nothing", which is a different and much worse claim.
    await expect(terminal.page.getByTestId('financials-unconverted')).toContainText('FY2024');
  });
});

test.describe('a US filer', () => {
  test('is not captioned as converted', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('main-tab-financials').click();
    await expect(terminal.page.getByTestId('financials-currency')).toContainText('in USD');
    await expect(terminal.page.getByTestId('financials-currency')).not.toContainText('converted');
  });
});
