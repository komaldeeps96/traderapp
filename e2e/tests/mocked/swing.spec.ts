import { expect, test } from '../../fixtures/test';

/**
 * The left column's second question.
 *
 * The day scanners rank the tape and need IBKR. These read daily structure
 * and come from TradingView, which is why the tab still fills when the other
 * one is dark.
 */
test.describe('swing screens', () => {
  test.beforeEach(async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-tab-swing').click();
    await expect(terminal.page.getByTestId('swing-panel')).toBeVisible();
  });

  test('opens on the day scanners, not these', async ({ terminal }) => {
    // Switching costs a click; opening on the wrong one costs a session.
    await terminal.page.getByTestId('scanner-tab-day').click();
    await expect(terminal.page.getByTestId('swing-panel')).toBeHidden();
  });

  test('lists the screens on offer', async ({ terminal }) => {
    await expect(terminal.page.getByTestId('swing-screen-trend')).toBeVisible();
    await expect(terminal.page.getByTestId('swing-screen-breakout')).toBeVisible();
  });

  test('states what the screen is looking for', async ({ terminal }) => {
    // Two of these differ only in how far off the high they want, which is
    // not something a name can carry.
    await expect(terminal.page.getByTestId('swing-note')).toContainText('52-week high');
  });

  test('draws the candidates', async ({ terminal }) => {
    await expect(terminal.page.getByTestId('swing-row-TEAM')).toBeVisible();
    await expect(terminal.page.getByTestId('swing-row-TEAM')).toContainText('190.41');
  });

  test('signs the distance from the high', async ({ terminal }) => {
    // Unsigned, "2.3%" could be above the high, which is not a place a stock
    // can be.
    await expect(terminal.page.getByTestId('swing-row-TEAM')).toContainText('-2.3%');
  });

  test('loads a symbol when a row is clicked', async ({ terminal }) => {
    await terminal.page.getByTestId('swing-row-ANF').click();
    await expect.poll(async () => (await terminal.state()).symbol).toBe('ANF');
  });

  test('remembers the tab across a reload', async ({ terminal }) => {
    await terminal.page.reload();
    await expect(terminal.page.getByTestId('swing-panel')).toBeVisible();
  });

  test('an empty screen reads as a market state, not a fault', async ({ page, terminal }) => {
    await page.route('**/api/swing/*', (route) =>
      route.fulfill({
        json: { screen_id: 'breakout', rows: [], config: {}, note: null },
      }),
    );
    await terminal.page.getByTestId('swing-screen-breakout').click();
    await expect(terminal.page.getByTestId('swing-empty')).toBeVisible();
  });

  test('a malformed payload does not take the terminal down', async ({ page, terminal }) => {
    // This is not hypothetical: an early mock answered the catalogue URL with
    // the *rows* payload, `payload.screens[0]` threw, and the whole app
    // unmounted — chart, scanners and all — from one panel's bad response.
    await page.route('**/api/swing/*', (route) =>
      route.fulfill({ json: { unexpected: true } }),
    );
    await terminal.page.getByTestId('scanner-tab-day').click();
    await terminal.page.getByTestId('scanner-tab-swing').click();

    await expect(terminal.page.getByTestId('scanner-tabs')).toBeVisible();
    expect((await terminal.chartState()).barCount).toBeGreaterThan(0);
  });

  test('says so when the screen itself failed', async ({ page, terminal }) => {
    // "Nothing qualifies" and "the source refused" must not look the same.
    await page.route('**/api/swing/*', (route) =>
      route.fulfill({
        json: {
          screen_id: 'breakout',
          rows: [],
          config: {},
          note: 'TradingView did not answer; the screen is stale.',
        },
      }),
    );
    await terminal.page.getByTestId('swing-screen-breakout').click();
    await expect(terminal.page.getByTestId('swing-warning')).toBeVisible();
    await expect(terminal.page.getByTestId('swing-empty')).toBeHidden();
  });
});
