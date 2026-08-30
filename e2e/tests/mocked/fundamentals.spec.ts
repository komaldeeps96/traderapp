import { expect, test } from '../../fixtures/test';
import { makeDilutionSummary, makeFundamentals } from '../../fixtures/data';

/**
 * The fundamentals panel and the chip that summarises it.
 *
 * The panel exists because IBKR answers error 10358 to every fundamentals
 * request on this account, so all of this comes from SEC EDGAR. What is worth
 * a browser test rather than a unit test is that the two halves agree — the
 * chip in the always-visible strip and the panel behind the tab are built
 * from the same read — and that stale figures are never presented as current.
 */
test.describe('fundamentals panel', () => {
  test('shows the supply, the need and the habit', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    const panel = terminal.dockPanel('fundamentals');
    await expect(panel).toContainText('Fixture Industries Inc');
    await expect(panel).toContainText('Supply overhang');
    await expect(panel).toContainText('Need for cash');
    await expect(panel).toContainText('Track record');
  });

  test('reports the warrant overhang against the share count', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    const panel = terminal.dockPanel('fundamentals');
    await expect(panel).toContainText('25.77M');
    await expect(panel).toContainText('89% of s/o');
  });

  test('renders the warrant strike and judges it against the live price', async ({ terminal }) => {
    // The full read ships the strike as a dated figure while the info-strip
    // chip gets a bare number; reading it as a number here rendered "—".
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    const panel = terminal.dockPanel('fundamentals');
    await expect(panel).toContainText('Warrant strike');
    await expect(panel).toContainText('3.00');
    await expect(panel).toContainText('ITM');
  });

  test('every figure carries the period it was reported for', async ({ terminal }) => {
    // XBRL lags by a quarter or more, and a delinquent filer's numbers can be
    // three quarters old. Presenting one as current would be a lie.
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    await expect(terminal.dockPanel('fundamentals')).toContainText('2025-12-31');
  });

  /**
   * The baby-shelf ceiling.
   *
   * The number everybody quotes comes off the last 10-K cover and is a year
   * stale. The rule re-measures public float on the date of every sale
   * against a 60-day look-back, so a run raises the ceiling it is running
   * into — and past $75M of float the cap stops applying at all. What earns
   * a browser test is that the panel shows the *live* figure rather than the
   * filed one, and that the uncapped case reads differently rather than
   * quietly showing a bigger number.
   */
  test('prices the baby-shelf cap at the 60-day high, not the cover page', async ({
    terminal,
  }) => {
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    // The filed figure implies $9.47M; measured at the 60-day high it is
    // $20.23M, and the panel must not quote the stale one.
    const cap = terminal.page.getByTestId('baby-shelf');
    await expect(cap).toContainText('20.23M');
    await expect(cap).not.toContainText('9.47M');
    await expect(terminal.page.getByTestId('shelf-float')).toContainText('2.1×');
  });

  test('says the cap is lifted rather than showing a bigger one', async ({ terminal, page }) => {
    await page.route('**/api/fundamentals/*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          makeFundamentals('AAPL', {
            dilution: {
              ...makeFundamentals('AAPL').dilution,
              live_shelf: {
                price: 6.4,
                public_float: 184_960_000,
                capped: false,
                capacity: null,
                multiple: 6.51,
              },
              // The backend drops the contradictory reason when the cap
              // lifts, so the fixture has to as well.
              reasons: [
                'warrants 89% of shares outstanding',
                'the run has carried float past $75M — the baby-shelf cap no longer applies',
              ],
            },
          }),
        ),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    await expect(terminal.page.getByTestId('baby-shelf')).toContainText('lifted');
    await expect(terminal.dockPanel('fundamentals')).not.toContainText('baby shelf limits apply');
  });

  test('says nothing about a cap that has never applied', async ({ terminal, page }) => {
    // A mega cap's float at the 60-day high is trillions and its one-third
    // limit has never bound anything. "Lifted" in red would be a dramatic
    // claim about a rule the company was never near.
    await page.route('**/api/fundamentals/*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          makeFundamentals('AAPL', {
            dilution: {
              ...makeFundamentals('AAPL').dilution,
              baby_shelf: false,
              baby_shelf_capacity: null,
              live_shelf: {
                price: 320,
                public_float: 4_660_011_000_000,
                capped: false,
                capacity: null,
                multiple: 1.43,
              },
              reasons: ['warrants 89% of shares outstanding'],
            },
          }),
        ),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    await expect(terminal.dockPanel('fundamentals')).toContainText('Public float');
    await expect(terminal.page.getByTestId('baby-shelf')).toHaveCount(0);
    await expect(terminal.page.getByTestId('shelf-float')).toHaveCount(0);
  });

  test('lists the reasons behind the verdict', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    const reasons = terminal.page.getByTestId('dilution-reasons');
    await expect(reasons).toContainText('89% of shares outstanding');
    await expect(reasons).toContainText('5.6 months of cash');
    await expect(terminal.page.getByTestId('dilution-tone')).toHaveText('serial');
  });

  test('says so plainly when the company files nothing', async ({ terminal, page }) => {
    await page.route('**/api/fundamentals/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeFundamentals('AAPL', { dilution: null, profile: null })),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    await expect(terminal.dockPanel('fundamentals')).toContainText('files nothing');
  });

  test('says so when EDGAR is switched off rather than showing an empty panel', async ({
    terminal,
    page,
  }) => {
    await page.route('**/api/fundamentals/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          symbol: 'AAPL',
          available: false,
          dilution: null,
          profile: null,
        }),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    await expect(terminal.dockPanel('fundamentals')).toContainText('switched off');
  });
});

test.describe('dilution chip', () => {
  test('is absent for a company with nothing to say', async ({ terminal }) => {
    // The default fixture sends no dilution block at all.
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('tp-dilution')).toHaveCount(0);
  });

  test('flags warrants in the money against the live price', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    // Strike $3 against a last price around $10: the warrants are live supply.
    await backend.pushInfo({ dilution: makeDilutionSummary() });

    const chip = terminal.page.getByTestId('tp-dilution');
    await expect(chip).toHaveText('W 89% ITM');
    await expect(chip).toHaveAttribute('data-tone', 'serial');
  });

  test('falls back to the runway when the warrants are out of the money', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    await backend.pushInfo({
      dilution: makeDilutionSummary({ warrant_strike: 500, tone: 'heavy' }),
    });

    const chip = terminal.page.getByTestId('tp-dilution');
    await expect(chip).toHaveText('CASH 5.6MO');
    await expect(chip).toHaveAttribute('data-tone', 'heavy');
  });

  test('renders nothing for a clean read', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushInfo({
      dilution: makeDilutionSummary({
        tone: 'clean',
        warrant_overhang: null,
        runway_months: null,
        reasons: [],
      }),
    });

    await expect(terminal.page.getByTestId('tp-spread')).toBeVisible();
    await expect(terminal.page.getByTestId('tp-dilution')).toHaveCount(0);
  });
});

test.describe('business ratios', () => {
  test('carries the ratios below the dilution read', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    const panel = terminal.dockPanel('fundamentals');
    await expect(panel).toContainText('Business');
    await expect(panel).toContainText('Miscellaneous Commercial Services');
    await expect(panel).toContainText('Current ratio');
  });

  test('shows the next earnings date', async ({ terminal }) => {
    // The one row in this group worth planning around.
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    await expect(terminal.page.getByTestId('next-earnings')).toContainText('2026-');
  });

  test('omits a ratio the company has no value for', async ({ terminal }) => {
    // A loss-maker has no P/E and negative equity has no debt-to-equity;
    // absent means absent, not "—".
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();

    await expect(terminal.dockPanel('fundamentals')).not.toContainText('Debt / equity');
  });
});
