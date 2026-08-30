import { expect, test } from '../../fixtures/test';
import { makeFilingMessage, makeFilings, makeLongFilingTrail } from '../../fixtures/data';

/**
 * The filings tab and the mid-session alert.
 *
 * A small cap's filings are its dilution history, so the offering and distress
 * forms lead and everything else sits behind a fold. The alert is the payoff:
 * a 424B5 accepted while you are holding a runner is the most expensive
 * surprise in this style of trading, and it is public the moment EDGAR takes it.
 */
test.describe('filings tab', () => {
  test('leads with dilution and distress', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('filings').click();

    const rows = terminal.page.getByTestId('filing-row');
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toHaveAttribute('data-form', '424B5');
    await expect(rows.nth(1)).toHaveAttribute('data-form', 'NT 10-Q');
  });

  test('explains each form in trading terms', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('filings').click();

    await expect(terminal.dockPanel('filings')).toContainText('shares being sold now');
  });

  test('keeps the routine filings behind a fold', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('filings').click();
    await expect(terminal.page.getByTestId('filings-toggle')).toContainText('2');

    await terminal.page.getByTestId('filings-toggle').click();
    await expect(terminal.page.getByTestId('filing-row')).toHaveCount(4);
  });

  test('a long trail opens on the recent rows, not on 2019', async ({ terminal, page }) => {
    // A serial diluter's trail runs to 131 offering and distress filings going
    // back years; rendering all of it opens the panel somewhere in 2021.
    await page.route('**/api/filings/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeFilings('AAPL', { filings: makeLongFilingTrail(60) })),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('filings').click();

    await expect(terminal.page.getByTestId('filing-row')).toHaveCount(18);
    await expect(terminal.page.getByTestId('filings-older')).toContainText('42 older');
  });

  test('the older ones are one click away', async ({ terminal, page }) => {
    await page.route('**/api/filings/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeFilings('AAPL', { filings: makeLongFilingTrail(60) })),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('filings').click();
    await terminal.page.getByTestId('filings-older').click();

    await expect(terminal.page.getByTestId('filing-row')).toHaveCount(60);
  });

  test('a short trail needs no fold at all', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('filings').click();

    await expect(terminal.page.getByTestId('filings-older')).toHaveCount(0);
  });

  test('links to the document on sec.gov', async ({ terminal }) => {
    // The one place a new browser tab is right: reading an S-1 is not a job
    // for a 400px rail.
    await terminal.waitForChart();
    await terminal.dockTab('filings').click();

    const first = terminal.page.getByTestId('filing-row').first();
    await expect(first).toHaveAttribute('target', '_blank');
    await expect(first).toHaveAttribute('href', /sec\.gov\/Archives/);
  });

  test('says so when the company files nothing', async ({ terminal, page }) => {
    await page.route('**/api/filings/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeFilings('AAPL', { filings: [] })),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('filings').click();

    await expect(terminal.dockPanel('filings')).toContainText('no filings on EDGAR');
  });
});

test.describe('mid-session filing alert', () => {
  test('badges the tab when an offering lands while you are elsewhere', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('dock-alert-filings')).toHaveCount(0);

    await backend.send(makeFilingMessage('AAPL', { accession: 'live-424' }));

    await expect(terminal.page.getByTestId('dock-alert-filings')).toHaveText('1');
  });

  test('opening the tab clears the badge and marks the row new', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    await backend.send(makeFilingMessage('AAPL', { accession: 'live-424' }));
    await expect(terminal.page.getByTestId('dock-alert-filings')).toHaveText('1');

    await terminal.dockTab('filings').click();

    await expect(terminal.page.getByTestId('dock-alert-filings')).toHaveCount(0);
    await expect(terminal.page.getByTestId('filing-row').first()).toContainText('NEW');
  });

  test('a filing for another symbol is ignored', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.send(makeFilingMessage('ZZZZ', { accession: 'other' }));
    await expect(terminal.page.getByTestId('dock-alert-filings')).toHaveCount(0);
  });

  test('the same filing twice does not double the badge', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const message = makeFilingMessage('AAPL', { accession: 'live-424' });
    await backend.send(message);
    await backend.send(message);
    await expect(terminal.page.getByTestId('dock-alert-filings')).toHaveText('1');
  });
});
