import { expect, liveTest as test } from '../../fixtures/test';
import type { TerminalPage } from '../../pages/TerminalPage';

/**
 * The real stack.
 *
 * Real backend, real Alpaca provider, real indicator maths, real WebSocket —
 * only Alpaca's HTTP endpoint is replaced by a fixture server, so this runs
 * with no credentials and outside market hours. The mocked suite proves the
 * frontend behaves; this proves the two halves actually agree on the protocol.
 */

test.describe('backend', () => {
  test('reports its health and data source', async ({ request }) => {
    const response = await request.get('http://127.0.0.1:8100/api/health');
    expect(response.ok()).toBe(true);

    const body = await response.json();
    expect(body.status).toBe('ok');
    expect(body.source).toBe('alpaca');
    expect(body.ibkr_connected).toBe(false);
  });

  test('serves the full indicator configuration', async ({ request }) => {
    const response = await request.get('http://127.0.0.1:8100/api/indicators');
    const specs = await response.json();

    expect(specs.length).toBeGreaterThan(25);
    const ids = specs.map((spec: { id: string }) => spec.id);
    expect(ids).toEqual(
      expect.arrayContaining(['ema9', 'vwap', 'pm_high', 'prev_day_close', 'high_52w', 'd_sma200']),
    );
  });
});

test.describe('end to end', () => {
  // The backend remembers the last chart across sessions, which is right for a
  // single user but means parallel tests inherit each other's symbol and
  // timeframe. Each test therefore establishes its own baseline first.
  test.beforeEach(async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.selectTimeframe('1m');
    await terminal.setSymbol('AAPL');
    await expect.poll(async () => (await terminal.state()).status, { timeout: 20_000 }).toBe(
      'ready',
    );
    await expect.poll(async () => (await terminal.state()).timeframe).toBe('1m');
  });

  test('loads a chart from real market data', async ({ terminal }) => {
    const state = await terminal.chartState();
    expect(state.barCount).toBeGreaterThan(100);
    expect(state.lastBar).not.toBeNull();
  });

  test('computes indicators server-side', async ({ terminal }) => {
    const state = await terminal.chartState();
    expect(state.pointCounts.ema9).toBeGreaterThan(50);
    expect(state.pointCounts.vwap).toBeGreaterThan(50);
  });

  test('serves the mini charts their own timeframes', async ({ terminal }) => {
    // The real proof that the extra-timeframe subscription works: one socket,
    // one symbol, three resampled charts with server-computed EMAs on each.
    await terminal.waitForMiniCharts();

    for (const timeframe of ['1m', '5m'] as const) {
      const mini = (await terminal.miniChartState(timeframe))!;
      expect(mini.timeframe).toBe(timeframe);
      expect(mini.pointCounts.ema9).toBeGreaterThan(10);
      expect(mini.pointCounts.ema20).toBeGreaterThan(10);
    }

    const minute = (await terminal.miniChartState('1m'))!;
    const fiveMinute = (await terminal.miniChartState('5m'))!;
    expect(fiveMinute.barCount).toBeLessThan(minute.barCount);
  });

  test('computes key levels from daily history', async ({ terminal }) => {
    // These come from a separate daily fetch and a separate code path, so
    // their presence proves the whole level pipeline ran.
    const state = await terminal.chartState();
    expect(state.pointCounts.prev_day_close).toBeGreaterThan(0);
    expect(state.pointCounts.high_52w).toBeGreaterThan(0);
  });

  test('shows key levels with distances in the sidebar', async ({ terminal }) => {
    expect(await terminal.keyLevelRows.count()).toBeGreaterThan(5);
    await expect(terminal.priceMarker).toBeVisible();
  });

  test('resamples to a higher timeframe', async ({ terminal }) => {
    const minutes = (await terminal.chartState()).barCount;

    await terminal.selectTimeframe('15m');
    await expect.poll(async () => (await terminal.chartState()).timeframe).toBe('15m');

    const quarters = (await terminal.chartState()).barCount;
    expect(quarters).toBeLessThan(minutes);
    expect(quarters).toBeGreaterThan(0);
  });

  test('opens four-hour bars on the New York clock', async ({ terminal }) => {
    // 4h is the one timeframe whose bars do not fall out of epoch division,
    // so this is the end-to-end proof that the backend anchors them to the
    // local day: every bar opens at 00:00, 04:00, 08:00, 12:00, 16:00 or
    // 20:00 New York, which is what puts the pre-market, the open and the
    // close each in a bar of their own.
    await terminal.selectTimeframe('4h');
    await expect.poll(async () => (await terminal.chartState()).timeframe).toBe('4h');

    const state = await terminal.chartState();
    expect(state.barCount).toBeGreaterThan(0);

    const opened = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      hour12: false,
      hour: 'numeric',
      minute: 'numeric',
    }).format(new Date(state.lastBar!.t * 1000));
    const [hour, minute] = opened.split(':').map(Number);

    expect(minute).toBe(0);
    expect((hour ?? 0) % 4).toBe(0);
  });

  test('serves a 10-second chart rebuilt from the trade tape', async ({ terminal }) => {
    // 10s is its own base timeframe: the backend aggregates the raw trades
    // endpoint rather than resampling minutes, so bars here prove that path.
    await terminal.selectTimeframe('10s');
    await expect
      .poll(async () => (await terminal.chartState()).timeframe, { timeout: 20_000 })
      .toBe('10s');
    expect((await terminal.chartState()).barCount).toBeGreaterThan(100);

    // The 10s chart carries the minute EMAs at six times the span.
    const state = await terminal.chartState();
    expect(state.seriesIds).toContain('ema9');
    expect(state.pointCounts.ema9).toBeGreaterThan(0);
  });

  test('fills the info strip from its own bars', async ({ terminal }) => {
    // Day volume and previous close come from the backend's bar store — no
    // TradingView in this suite, so exactly the self-derived fields appear.
    await expect(terminal.page.getByTestId('tp-vol')).not.toHaveText('—', {
      timeout: 25_000,
    });
    await expect(terminal.page.getByTestId('tp-prevclose')).not.toHaveText('—');
  });

  test('loads a daily chart', async ({ terminal }) => {
    await terminal.selectTimeframe('1d');
    await expect.poll(async () => (await terminal.chartState()).timeframe).toBe('1d');
    expect((await terminal.chartState()).barCount).toBeGreaterThan(50);
  });

  test('switches symbol', async ({ terminal }) => {
    await terminal.setSymbol('TSLA');
    await expect.poll(async () => (await terminal.state()).symbol).toBe('TSLA');
    // The symbol updates the moment the request is sent, so wait for the
    // snapshot before trusting the bar count.
    await expect.poll(async () => (await terminal.state()).status, { timeout: 20_000 }).toBe(
      'ready',
    );
    expect((await terminal.chartState()).barCount).toBeGreaterThan(100);
  });

  test('reports a symbol with no data', async ({ terminal }) => {
    await terminal.setSymbol('NODATA');
    await expect(terminal.errorBanner).toBeVisible({ timeout: 20_000 });
  });

  test('rejects a malformed symbol without dropping the connection', async ({ terminal }) => {
    await terminal.symbolInput.fill('!!!');
    await terminal.symbolInput.press('Enter');

    // The socket survives, so a good symbol still works afterwards.
    await terminal.setSymbol('AAPL');
    await expect.poll(async () => (await terminal.state()).status, { timeout: 20_000 }).toBe(
      'ready',
    );
  });

  test('remembers the last chart for the next session', async ({ terminal, page }) => {
    await terminal.setSymbol('MSFT');
    await expect.poll(async () => (await terminal.state()).symbol).toBe('MSFT');
    // The client marks the symbol changed as soon as it sends the request;
    // the server only records it once it has served the snapshot. Reloading
    // before then races the save and reads back the previous symbol.
    await expect.poll(async () => (await terminal.state()).status, { timeout: 20_000 }).toBe(
      'ready',
    );

    await page.reload();
    await expect(terminal.symbolInput).toHaveValue('MSFT');
  });
});

test.describe('two windows', () => {
  test('watch different symbols without interfering', async ({ browser }) => {
    // The previous design broadcast one globally-active ticker to every
    // client, so a second window silently hijacked the first.
    const [first, second] = await Promise.all([browser.newContext(), browser.newContext()]);
    const [pageOne, pageTwo] = await Promise.all([first.newPage(), second.newPage()]);

    try {
      const { TerminalPage } = await import('../../pages/TerminalPage');
      const one = new TerminalPage(pageOne);
      const two = new TerminalPage(pageTwo);

      const settle = async (terminal: TerminalPage, symbol: string) => {
        await terminal.setSymbol(symbol);
        await expect.poll(async () => (await terminal.state()).symbol).toBe(symbol);
        // The symbol updates the moment the request is sent; the chart only
        // holds that symbol's bars once the snapshot has arrived.
        await expect
          .poll(async () => (await terminal.state()).status, { timeout: 20_000 })
          .toBe('ready');
      };

      await one.goto();
      await one.waitForChart();
      await settle(one, 'AAPL');

      await two.goto();
      await two.waitForChart();
      await settle(two, 'TSLA');

      // The first window must still be on AAPL, holding AAPL's own bars.
      expect((await one.state()).symbol).toBe('AAPL');
      const oneClose = (await one.chartState()).lastBar!.c;
      const twoClose = (await two.chartState()).lastBar!.c;
      expect(oneClose).not.toBe(twoClose);
    } finally {
      await Promise.all([first.close(), second.close()]);
    }
  });
});

test.describe('indicator toggles, against the real server', () => {
  /**
   * Toggle, and prove it reached state.yaml rather than the browser.
   *
   * Reading back through a reload is the only honest check: the chart applies
   * a toggle optimistically, so asserting on the chart alone would pass even
   * if the command never left the page. Each test restores what it changed
   * and reloads once more to prove the restore landed too — otherwise the
   * next test inherits it, these all share one backend.
   */
  async function toggleEma9(terminal: TerminalPage): Promise<boolean> {
    const before = (await terminal.chartState()).visible.ema9;
    await terminal.indicatorChip('ema9').getByRole('button').click();
    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(!before);
    return before;
  }

  async function reopen(terminal: TerminalPage): Promise<boolean> {
    await terminal.goto();
    await terminal.waitForChart();
    return (await terminal.chartState()).visible.ema9;
  }

  test('survive a reload, with nothing left in the browser', async ({ terminal, page }) => {
    await terminal.waitForChart();
    const before = await toggleEma9(terminal);

    // Clear the browser's own storage, so nothing here can carry the answer.
    await page.evaluate(() => localStorage.clear());
    expect(await reopen(terminal)).toBe(!before);

    await toggleEma9(terminal);
    expect(await reopen(terminal)).toBe(before);
  });

  test('are remembered per timeframe', async ({ terminal }) => {
    await terminal.waitForChart();

    await terminal.timeframeTab('1m').click();
    await terminal.waitForChart();
    const onMinute = (await terminal.chartState()).visible.ema9;

    await terminal.timeframeTab('10s').click();
    await terminal.waitForChart();
    const before = await toggleEma9(terminal);

    // The minute chart was never touched and must not have moved.
    await terminal.timeframeTab('1m').click();
    await terminal.waitForChart();
    expect((await terminal.chartState()).visible.ema9).toBe(onMinute);

    await terminal.timeframeTab('10s').click();
    await terminal.waitForChart();
    expect((await terminal.chartState()).visible.ema9).toBe(!before);

    await toggleEma9(terminal);
    expect(await reopen(terminal)).toBe(before);
  });
});


/**
 * The watchlist, against the real server.
 *
 * The mocked suite covers how the panel behaves; this covers the only thing
 * a mock cannot prove — that the list is genuinely on the server. It survives
 * a reload with the browser's own storage cleared, which no client-side list
 * could do.
 *
 * The backend here runs with the screener switched off, because nothing in a
 * test run may leave the machine. That is exactly the state this asserts is
 * still useful: the names, their order and their persistence do not depend on
 * a price being fetched for them.
 */
test.describe('watchlist, against the real server', () => {
  async function openWatch(terminal: TerminalPage): Promise<void> {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-tab-watch').click();
    await expect(terminal.page.getByTestId('watchlist-panel')).toBeVisible();
  }

  async function add(terminal: TerminalPage, symbol: string): Promise<void> {
    await terminal.page.getByTestId('watchlist-input').fill(symbol);
    await terminal.page.getByTestId('watchlist-input').press('Enter');
    await expect(terminal.page.getByTestId(`watchlist-row-${symbol}`)).toBeVisible();
  }

  test('survives a reload with nothing left in the browser', async ({ terminal, page }) => {
    await openWatch(terminal);
    await add(terminal, 'AAPL');
    await add(terminal, 'TSLA');

    // Clear the browser's own storage, so nothing here can carry the answer.
    await page.evaluate(() => localStorage.clear());
    await terminal.goto();
    await openWatch(terminal);

    const rows = terminal.page.locator('[data-testid^="watchlist-row-"]');
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText('AAPL');
    await expect(rows.nth(1)).toContainText('TSLA');
  });

  test('a removal survives too', async ({ terminal }) => {
    await openWatch(terminal);
    await terminal.page.getByTestId('watchlist-remove-AAPL').click();
    await expect(terminal.page.getByTestId('watchlist-row-AAPL')).toBeHidden();

    await terminal.goto();
    await openWatch(terminal);
    await expect(terminal.page.getByTestId('watchlist-row-AAPL')).toBeHidden();
    await expect(terminal.page.getByTestId('watchlist-row-TSLA')).toBeVisible();
  });

  test('says why the prices are blank rather than looking broken', async ({ terminal }) => {
    // With the screener off there is nothing to quote, and an empty row with
    // no explanation reads as a bug rather than as a switched-off feed.
    await openWatch(terminal);
    await expect(terminal.page.getByTestId('watchlist-warning')).toBeVisible();
  });

  test('and the list is empty again afterwards', async ({ terminal }) => {
    // Left clean for the next run: this suite shares one state file.
    await openWatch(terminal);
    await terminal.page.getByTestId('watchlist-remove-TSLA').click();
    await expect(terminal.page.getByTestId('watchlist-empty')).toBeVisible();
  });
});
