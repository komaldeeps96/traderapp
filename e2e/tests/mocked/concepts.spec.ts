import { expect, test } from '../../fixtures/test';

/**
 * Searching everything a filer reports.
 *
 * The curated statement is roughly a tenth of what a company tags — Apple
 * reports 503 concepts, JP Morgan 931 — and the rest is where a specific
 * question gets answered. The search swaps the table for those rows on the
 * same period axis, so a number found here lines up with the statement line
 * above it.
 */
test.describe('concept search', () => {
  test.beforeEach(async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('main-tab-financials').click();
    await expect(terminal.page.getByTestId('financials-tab')).toBeVisible();
  });

  test('shows the statement until something is searched for', async ({ terminal }) => {
    await expect(terminal.page.getByTestId('statement-income')).toBeVisible();
    await expect(terminal.page.getByTestId('concept-results')).toHaveCount(0);
  });

  test('waits for a real query rather than searching one letter', async ({ terminal }) => {
    await terminal.page.getByTestId('concept-search').fill('le');
    await expect(terminal.page.getByTestId('concept-results')).toHaveCount(0);
  });

  test('swaps the table for the matching concepts', async ({ terminal }) => {
    await terminal.page.getByTestId('concept-search').fill('lease');
    await expect(terminal.page.getByTestId('concept-results')).toBeVisible();
    const row = terminal.page.getByTestId('concept-row-FinanceLeaseLiability');
    // No currency symbol on the figure: an as-filed concept is not always
    // money, so the unit rides its own badge instead of being assumed.
    await expect(row).toContainText('1.23B');
    await expect(row).toContainText('USD');
    await expect(row).not.toContainText('$1.23B');
    await expect(terminal.page.getByTestId('statement-income')).toHaveCount(0);
  });

  test('says how many matched and how many are shown', async ({ terminal }) => {
    // 27 matches with 2 drawn is a different fact from 2 matches.
    await terminal.page.getByTestId('concept-search').fill('lease');
    await expect(terminal.page.getByTestId('concept-count')).toContainText('27 matches');
  });

  test('labels the unit each concept was filed in', async ({ terminal }) => {
    // A lease term in years must not be drawn as dollars.
    await terminal.page.getByTestId('concept-search').fill('lease');
    const term = terminal.page.getByTestId(
      'concept-row-OperatingLeaseWeightedAverageRemainingLeaseTerm1',
    );
    await expect(term).toContainText('10.30');
    await expect(term).toContainText('Y');
    await expect(term).not.toContainText('$');
  });

  test('captions the search as filed, not as converted', async ({ terminal }) => {
    // The statement above may be converted to USD; these rows are not, and
    // a "converted" caption over as-filed figures is a contradiction.
    await terminal.page.getByTestId('concept-search').fill('lease');
    await expect(terminal.page.getByTestId('financials-currency')).toContainText('as filed');
  });

  test('returns to the statement when the search is cleared', async ({ terminal }) => {
    await terminal.page.getByTestId('concept-search').fill('lease');
    await expect(terminal.page.getByTestId('concept-results')).toBeVisible();
    await terminal.page.getByTestId('concept-search').fill('');
    await expect(terminal.page.getByTestId('statement-income')).toBeVisible();
  });

  test('says so when nothing matches', async ({ page, terminal }) => {
    await page.route('**/api/concepts/**', (route) =>
      route.fulfill({
        json: {
          symbol: 'AAPL',
          available: true,
          currency: 'USD',
          query: 'zzz',
          total: 0,
          periods: [{ key: 'FY2025', end: '2025-09-27', fiscal_year: 2025 }],
          rows: [],
        },
      }),
    );
    await terminal.page.getByTestId('concept-search').fill('zzz');
    await expect(terminal.page.getByTestId('concept-empty')).toBeVisible();
  });
});
