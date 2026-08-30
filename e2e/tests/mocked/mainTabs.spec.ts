import { expect, test } from '../../fixtures/test';

/**
 * The main area is now tabbed.
 *
 * The chart is the first tab and the reason the terminal exists, so the load
 * -bearing property is that leaving it and coming back changes nothing about
 * it. Everything else here is the Financials tab that made the strip worth
 * rendering.
 */
test.describe('main tabs', () => {
  test('opens on the chart', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('main-tab-chart')).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(terminal.page.getByTestId('main-panel-chart')).toHaveAttribute(
      'data-active',
      'true',
    );
  });

  test('switches to the financials tab', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('main-tab-financials').click();
    await expect(terminal.page.getByTestId('financials-tab')).toBeVisible();
  });

  test('remembers the tab across a reload', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('main-tab-financials').click();
    await expect(terminal.page.getByTestId('financials-tab')).toBeVisible();

    await terminal.page.reload();
    await expect(terminal.page.getByTestId('financials-tab')).toBeVisible();
  });
});

test.describe('the chart behind another tab', () => {
  test('is never unmounted', async ({ terminal }) => {
    // `display:none` would collapse it to zero height and lightweight-charts
    // cannot size a pane inside a container that has none. It stays in the
    // layout, hidden with `visibility`.
    await terminal.waitForChart();
    const before = (await terminal.chartState()).barCount;

    await terminal.page.getByTestId('main-tab-financials').click();
    await expect(terminal.page.getByTestId('financials-tab')).toBeVisible();

    expect((await terminal.chartState()).barCount).toBe(before);
  });

  test('holds its viewport across a switch', async ({ terminal }) => {
    // Scrolling back through history and losing the position on every tab
    // switch would make the tabs unusable while reading a chart.
    await terminal.waitForChart();
    const zoomIn = terminal.chartControls.getByRole('button', { name: 'Zoom in' });
    await zoomIn.click();
    await zoomIn.click();

    // Let the zoom finish animating first. Comparing a range sampled
    // mid-animation against one sampled after would fail on the easing, not
    // on anything the tabs did.
    //
    // "Stable" means unchanged for half a second, not two equal samples in a
    // row: on WebKit the animation starts late enough that the first two
    // readings match while it has not begun, and the range then moves during
    // the tab switch.
    await terminal.page.waitForFunction(
      () => {
        const scope = window as unknown as Record<string, unknown>;
        const chart = window.__traderapp!.chart() as { visibleRange: unknown };
        const now = JSON.stringify(chart.visibleRange);
        if (scope.__rangeSample === now) {
          scope.__rangeStable = ((scope.__rangeStable as number) ?? 0) + 1;
        } else {
          scope.__rangeSample = now;
          scope.__rangeStable = 0;
        }
        return ((scope.__rangeStable as number) ?? 0) >= 5;
      },
      null,
      { polling: 100 },
    );

    const before = (await terminal.chartState()).visibleRange;
    expect(before).not.toBeNull();

    await terminal.page.getByTestId('main-tab-financials').click();
    await expect(terminal.page.getByTestId('financials-tab')).toBeVisible();
    await terminal.page.getByTestId('main-tab-chart').click();
    await expect(terminal.page.getByTestId('main-panel-chart')).toHaveAttribute(
      'data-active',
      'true',
    );

    // Not merely close: the same bars, untouched.
    expect((await terminal.chartState()).visibleRange).toEqual(before);
  });

  test('is hidden from assistive tech while another tab is open', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('main-tab-financials').click();
    await expect(terminal.page.getByTestId('main-panel-chart')).toHaveAttribute(
      'aria-hidden',
      'true',
    );
  });
});

test.describe('the financials tab', () => {
  test.beforeEach(async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('main-tab-financials').click();
    await expect(terminal.page.getByTestId('financials-tab')).toBeVisible();
  });

  test('lays the periods out newest first', async ({ terminal }) => {
    const headings = terminal.page.getByTestId('financials-tab').locator('thead th');
    await expect(headings.nth(1)).toContainText('FY2025');
    await expect(headings.nth(2)).toContainText('FY2024');
  });

  test('prints the exact close under the label', async ({ terminal }) => {
    // "FY2025" is a convention companies disagree about; the end date is the
    // fact, so it travels with it.
    await expect(terminal.page.getByTestId('financials-tab').locator('thead th').nth(1)).toContainText('2025-09-27');
  });

  test('groups the lines into statements', async ({ terminal }) => {
    await expect(terminal.page.getByTestId('statement-income')).toBeVisible();
    await expect(terminal.page.getByTestId('statement-balance')).toBeVisible();
  });

  test('compacts dollars but not per-share figures', async ({ terminal }) => {
    const row = terminal.page.getByTestId('financials-row-revenue').locator('..');
    await expect(row).toContainText('$416.16B');
    const eps = terminal.page.getByTestId('financials-row-eps_diluted').locator('..');
    await expect(eps).toContainText('7.46');
  });

  test('shows a dash where nothing was filed', async ({ terminal }) => {
    // A quarter a company never filed is a blank, not a zero.
    const eps = terminal.page.getByTestId('financials-row-eps_diluted').locator('..');
    await expect(eps).toContainText('—');
  });

  test('names the concepts that answered', async ({ terminal }) => {
    // A revenue line stitched across an ASC 606 change is two tags, and a
    // reader comparing against a filing needs to know which one they see.
    await expect(terminal.page.getByTestId('financials-row-revenue')).toHaveAttribute(
      'title',
      /RevenueFromContractWithCustomer.* · Revenues/,
    );
  });

  test('switches to the quarterly view', async ({ terminal }) => {
    await terminal.page.getByTestId('financials-period-quarterly').click();
    await expect(terminal.page.getByTestId('financials-tab').locator('thead th').nth(1)).toContainText('FY2026 Q3');
  });

  test('says so when a company files no statements', async ({ page, terminal }) => {
    await page.route('**/api/financials/**', (route) =>
      route.fulfill({
        json: {
          symbol: 'NONE',
          available: true,
          note: null,
          period: 'annual',
          periods: [],
          statements: [],
        },
      }),
    );
    await terminal.page.getByTestId('financials-period-quarterly').click();
    await expect(terminal.page.getByTestId('financials-empty')).toBeVisible();
  });
});
