import type { TerminalPage } from '../../pages/TerminalPage';
import { expect, liveTest as test } from '../../fixtures/test';

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
    await expect(terminal.page.getByTestId('tp-dayvol')).not.toHaveText('—', {
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
