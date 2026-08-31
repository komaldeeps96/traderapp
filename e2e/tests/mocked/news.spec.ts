import { expect, test } from '../../fixtures/test';
import { makeHeadline, makeNews, makeNewsMessage } from '../../fixtures/data';

/**
 * The news tab.
 *
 * IBKR is the one research feed this account is entitled to, so this is the
 * half of the dock that does not come from EDGAR. What earns a browser test:
 * that a headline can be read without leaving the terminal, that the catalyst
 * tint reaches the DOM (an offering has to be the loudest row on screen), and
 * that a live headline pushed over the WebSocket merges into the list the
 * backfill produced rather than appearing twice or not at all.
 */
test.describe('news tab', () => {
  test('lists the headlines newest first', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    const rows = terminal.page.getByTestId('news-row');
    // Four from the wire feeds, two from Benzinga.
    await expect(rows).toHaveCount(6);
    await expect(rows.first()).toContainText('Announces Pricing of $8M Public Offering');
  });

  test('dates an older headline rather than showing only a clock', async ({ terminal, page }) => {
    // A thirty-day feed showing only "09:01" makes a June filing read as this
    // morning's news.
    await page.route('**/api/news/*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          makeNews('AAPL', {
            headlines: [makeHeadline({ time: Date.UTC(2020, 5, 25, 13, 1) / 1000 })],
          }),
        ),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    await expect(terminal.page.getByTestId('news-row').first()).toContainText('Jun 25');
  });

  test('tints a row by what it does to the tape', async ({ terminal }) => {
    // An offering ends a long; it is not "negative sentiment", it is supply.
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    const rows = terminal.page.getByTestId('news-row');
    await expect(rows.nth(0)).toHaveAttribute('data-catalyst', 'supply');
    await expect(rows.nth(1)).toHaveAttribute('data-catalyst', 'distress');
    await expect(rows.nth(2)).toHaveAttribute('data-catalyst', 'upside');
    await expect(rows.nth(3)).toHaveAttribute('data-catalyst', 'none');
  });

  test('shows how many duplicate wire copies were folded in', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    await expect(terminal.page.getByTestId('news-row').nth(2)).toContainText('+2');
  });

  test('reads an article in place rather than opening a browser tab', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();
    await terminal.page.getByTestId('news-row').first().click();

    const article = terminal.page.getByTestId('news-article');
    await expect(article).toBeVisible();
    await expect(article).toContainText('announced the pricing of an underwritten public offering');
  });

  test('closes the article again', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();
    await terminal.page.getByTestId('news-row').first().click();
    await expect(terminal.page.getByTestId('news-article')).toBeVisible();

    await terminal.page.getByTestId('news-close').click();
    await expect(terminal.page.getByTestId('news-article')).toHaveCount(0);
  });

  test('a live headline arrives at the top without a refetch', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();
    await expect(terminal.page.getByTestId('news-row')).toHaveCount(6);

    await backend.send(
      makeNewsMessage('AAPL', {
        article_id: 'live-1',
        headline: 'Celularity Halted, News Pending',
        catalyst: 'distress',
        time: 9_999_999_999,
      }),
    );

    const rows = terminal.page.getByTestId('news-row');
    await expect(rows).toHaveCount(7);
    await expect(rows.first()).toContainText('Halted, News Pending');
  });

  test('the same live headline twice does not double the row', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    const message = makeNewsMessage('AAPL', { article_id: 'live-dup', time: 9_999_999_999 });
    await backend.send(message);
    await backend.send(message);

    await expect(terminal.page.getByTestId('news-row')).toHaveCount(7);
  });

  test('a headline for another symbol is ignored', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    await backend.send(
      makeNewsMessage('ZZZZ', { article_id: 'other', time: 9_999_999_999 }),
    );

    await expect(terminal.page.getByTestId('news-row')).toHaveCount(6);
  });

  test('does not blame TWS when Benzinga is the feed that is missing', async ({
    terminal,
    page,
  }) => {
    // This used to read "News needs a running IBKR TWS or Gateway
    // connection", which stopped being true the moment Benzinga arrived on
    // Alpaca's connection: it answers with no TWS at all.
    await page.route('**/api/news/*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeNews('AAPL', { headlines: [], providers: [] })),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    const panel = terminal.dockPanel('news');
    await expect(panel).toContainText('Alpaca keys');
    await expect(panel).toContainText('TWS');
  });

  test('distinguishes an empty feed from a missing one', async ({ terminal, page }) => {
    await page.route('**/api/news/*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeNews('AAPL', { headlines: [] })),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    await expect(terminal.dockPanel('news')).toContainText('No headlines');
  });
});


/**
 * The second source.
 *
 * IBKR's eight feeds are good on most names and silent on some of exactly the
 * companies this terminal is for — WETO returned its own halt and its own
 * resume and nothing else. Benzinga rides in on Alpaca's connection, which
 * also means it is the only source that answers with no TWS running.
 */
test.describe('Benzinga headlines', () => {
  test.beforeEach(async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();
  });

  test('sit in the same list as the wire feeds', async ({ terminal }) => {
    await expect(
      terminal.page.getByText('Why Celularity Shares Are Trading Higher Today'),
    ).toBeVisible();
  });

  test('the feed is named in the footer', async ({ terminal }) => {
    await expect(terminal.page.getByTestId('news-providers')).toContainText('Benzinga');
  });

  test('a roundup is marked rather than passed off as this company’s news', async ({
    terminal,
  }) => {
    // It names twelve companies and this one is merely among them, so the
    // headline is usually about somebody else.
    const rows = terminal.page.getByTestId('news-roundup');
    await expect(rows).toHaveCount(1);
  });

  test('a real press release is not marked', async ({ terminal }) => {
    const release = terminal.page
      .getByTestId('news-row')
      .filter({ hasText: 'Why Celularity Shares Are Trading Higher' });
    await expect(release.getByTestId('news-roundup')).toHaveCount(0);
  });

  test('opening one offers the original', async ({ terminal }) => {
    await terminal.page
      .getByTestId('news-row')
      .filter({ hasText: 'Why Celularity Shares Are Trading Higher' })
      .click();
    const link = terminal.page.getByTestId('news-source-link');
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', /benzinga\.com/);
    // Third-party link on the page that also holds the trading UI.
    await expect(link).toHaveAttribute('rel', /noreferrer/);
  });

  test('a wire headline offers no such link', async ({ terminal }) => {
    // A wire article exists nowhere but on the connection it came down.
    await terminal.page
      .getByTestId('news-row')
      .filter({ hasText: 'Announces Pricing of $8M Public Offering' })
      .click();
    await expect(terminal.page.getByTestId('news-article')).toBeVisible();
    await expect(terminal.page.getByTestId('news-source-link')).toHaveCount(0);
  });
});
