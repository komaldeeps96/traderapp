import { expect, test } from '../../fixtures/test';
import { makeBrief, makeHeadline, makeNews, makeNewsMessage } from '../../fixtures/data';

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


test.describe('a live headline off the Benzinga socket', () => {
  test('lands in the list like any other', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    await backend.send(
      makeNewsMessage('AAPL', {
        article_id: 'bz:live-1',
        provider: 'BZ-ALP',
        headline: 'Celularity Receives FDA Clearance',
        time: 9_999_999_999,
        url: 'https://www.benzinga.com/news/live-1',
      }),
    );

    await expect(terminal.page.getByTestId('news-row').first()).toContainText('FDA Clearance');
  });

  test('a roundup does not light the dock badge', async ({ terminal, backend }) => {
    // It names a dozen companies and this one is merely among them, so a
    // badge for it interrupts about somebody else's stock.
    await terminal.waitForChart();
    await terminal.dockTab('charts').click();

    await backend.send(
      makeNewsMessage('AAPL', {
        article_id: 'bz:live-roundup',
        provider: 'BZ-ALP',
        headline: "12 Health Care Stocks Moving In Monday's Pre-Market Session",
        time: 9_999_999_999,
        symbol_count: 12,
        roundup: true,
      }),
    );

    await expect(terminal.dockTab('news')).not.toContainText('1');
  });

  test('but a real headline does', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.dockTab('charts').click();

    await backend.send(
      makeNewsMessage('AAPL', {
        article_id: 'bz:live-real',
        provider: 'BZ-ALP',
        headline: 'Celularity Receives FDA Clearance',
        time: 9_999_999_999,
      }),
    );

    await expect(terminal.dockTab('news')).toContainText('1');
  });
});


/**
 * The panel's top half: one day, read and scored.
 *
 * The reading itself happens on the server, in a `claude` process; what a
 * browser test can hold is the contract around it. Three things earn one.
 *
 * That the score reaches the DOM as a number *and* a band, because the whole
 * argument for the panel is the case the substring classifier cannot make —
 * an FDA clearance with an offering bolted to it is a 2, not an upside row.
 *
 * That the risks are rendered apart from the summary, because a trader
 * mid-run must not have to read a paragraph to find the offering in it.
 *
 * And that the toolbar switch actually stops the request, rather than merely
 * hiding a panel whose process has already been paid for.
 */
test.describe('the AI news summary', () => {
  test('scores the day above the feed', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    const score = terminal.page.getByTestId('news-brief-score');
    await expect(score).toHaveText(/2/);
    await expect(score).toHaveAttribute('data-verdict', 'weak');
    await expect(terminal.page.getByTestId('news-brief-summary')).toContainText(
      'registered direct',
    );
  });

  test('a low score on real good news is the point, not a bug', async ({ terminal }) => {
    // FDA clearance and a raise on the same morning. The substring classifier
    // in the list below tags the clearance "upside"; the reading says the
    // clearance is being sold into.
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    await expect(terminal.page.getByTestId('news-brief-bullets')).toContainText(
      'FDA 510(k) clearance',
    );
    await expect(terminal.page.getByTestId('news-brief-risks')).toContainText(
      'sold straight into the run',
    );
  });

  test('names the session and the window it read, not just "today"', async ({ terminal }) => {
    // Two different facts, and the pair is the whole claim: a chart open on
    // a Sunday is reading "for Monday, since Friday's close". A summary that
    // will not say which cannot be checked against the rows below it.
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    const window = terminal.page.getByTestId('news-brief-window');
    await expect(window).toContainText('Mar 5');
    await expect(window).toContainText('since');
    await expect(window).toContainText('3 headlines');
  });

  test('says why there is nothing rather than showing an empty box', async ({
    terminal,
    page,
  }) => {
    await page.route('**/api/news/*/brief*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          symbol: 'AAPL',
          status: 'no-cli',
          available: false,
          brief: null,
          note: "The 'claude' CLI was not found on this machine.",
        }),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    await expect(terminal.page.getByTestId('news-brief-note')).toContainText('was not found');
    // And the feed below is untouched by it.
    await expect(terminal.page.getByTestId('news-row')).toHaveCount(6);
  });

  test('the toolbar switch stops the request, not just the panel', async ({ terminal, page }) => {
    // A reading costs about a cent and a dozen seconds. A switch that hid the
    // panel while still paying for it would be worse than no switch.
    const asked: string[] = [];
    await page.route('**/api/news/*/brief*', (route) => {
      asked.push(route.request().url());
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeBrief()),
      });
    });
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('news').click();
    await expect(terminal.page.getByTestId('news-brief-score')).toBeVisible();

    const before = asked.length;
    await terminal.page.getByTestId('news-ai-toggle').click();

    await expect(terminal.page.getByTestId('news-brief')).toHaveCount(0);
    // The feed itself is untouched — the switch is about the reading.
    await expect(terminal.page.getByTestId('news-row')).toHaveCount(6);
    await terminal.page.waitForTimeout(300);
    expect(asked.length).toBe(before);
  });

  test('the switch is remembered across a reload', async ({ terminal }) => {
    await terminal.waitForChart();
    const toggle = terminal.page.getByTestId('news-ai-toggle');
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');

    await toggle.click();
    await terminal.goto();
    await terminal.waitForChart();

    await expect(terminal.page.getByTestId('news-ai-toggle')).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  test('refreshing asks for a fresh reading rather than the cached one', async ({
    terminal,
    page,
  }) => {
    const asked: string[] = [];
    await page.route('**/api/news/*/brief*', (route) => {
      asked.push(route.request().url());
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeBrief()),
      });
    });
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('news').click();
    await expect(terminal.page.getByTestId('news-brief-score')).toBeVisible();

    await terminal.page.getByTestId('news-brief-refresh').click();

    await expect
      .poll(() => asked.some((url) => url.includes('refresh=true')))
      .toBe(true);
  });

  test('a reading that fails leaves the feed readable', async ({ terminal, page }) => {
    await page.route('**/api/news/*/brief*', (route) => route.fulfill({ status: 500, body: '' }));
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('news').click();

    await expect(terminal.page.getByTestId('news-brief-note')).toBeVisible();
    await expect(terminal.page.getByTestId('news-row')).toHaveCount(6);
  });
});
