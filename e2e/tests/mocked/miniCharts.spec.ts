import { expect, test } from '../../fixtures/test';

/**
 * The context chart beside the main one.
 *
 * There were two of these — 1m over 5m — and the lower slot is now the
 * time-and-sales window, which has its own spec. What remains worth a browser
 * test rather than a unit test is unchanged. First, that the chart is
 * genuinely minimal: it draws onto a shared canvas with the same engine as the
 * main chart, and the whole point is that the ~30 key levels, MACD and the
 * dollar grid do *not* come with it. Second, that the main chart is
 * unaffected — the mini subscribes to an extra timeframe on the same socket,
 * and a bug there shows up as the main chart quietly losing its levels.
 */
test.describe('mini charts', () => {
  test('draws one context chart beside the main one', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    await expect(terminal.miniCharts).toBeVisible();
    await expect(terminal.miniChart('1m')).toBeVisible();
    expect((await terminal.miniChartState('1m'))!.timeframe).toBe('1m');
  });

  test('shares the tab with the tape rather than a second chart', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    await expect(terminal.tape).toBeVisible();
    await expect(terminal.miniChart('5m')).toHaveCount(0);
  });

  test('asks the server for its timeframe alongside the main chart', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    const command = await backend.waitForCommand('subscribe');
    expect(command.extra_timeframes).toEqual(['1m']);
  });

  test('carries only the two EMAs and volume', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    const mini = (await terminal.miniChartState('1m'))!;
    expect(mini.seriesIds).toHaveLength(2);
    expect(mini.seriesIds).toContain('ema9');
    expect(mini.seriesIds).toContain('ema20');
    expect(mini.hasVolumePane).toBe(true);
    expect(mini.dollarLineCount).toBe(0);
    expect(mini.bands).toEqual([]);
  });

  test('gives the EMAs real data rather than empty series', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    const mini = (await terminal.miniChartState('1m'))!;
    expect(mini.pointCounts.ema9).toBeGreaterThan(0);
    expect(mini.pointCounts.ema20).toBeGreaterThan(0);
  });

  test('leaves the main chart with its key levels', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    const main = (await terminal.chartState()).seriesIds;
    expect(main).toContain('pm_high');
    expect(main).toContain('vwap');
    expect(main.length).toBeGreaterThan(5);
  });

  test('opens on 60 bars, not the main chart’s 240', async ({ terminal }) => {
    // A mini showing the same 240 bars as the main chart at a fifth the width
    // is a smear; 60 is the window this is read at.
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    const range = (await terminal.miniChartState('1m'))!.visibleRange!;
    expect(Math.round(range.to - range.from)).toBe(59);
  });

  test('a mini zoom survives a reload without touching the main chart', async ({
    terminal,
  }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();
    const mainBefore = (await terminal.chartState()).visibleRange!;

    const width = async () => {
      const range = (await terminal.miniChartState('1m'))!.visibleRange!;
      return range.to - range.from;
    };
    const opened = await width();
    // Not scoped to `miniChart('1m')`: that testid is on the canvas container,
    // and the zoom buttons sit in the section header beside it. The label is
    // unique across the page anyway.
    await terminal.page.getByRole('button', { name: 'Zoom in 1m chart' }).click();
    await expect.poll(width).toBeLessThan(opened);
    const zoomed = await width();

    // Wait for the zoomed width itself — the initial frame already wrote a
    // default-width entry under this key.
    await expect
      .poll(() =>
        terminal.page.evaluate(() => {
          const raw = localStorage.getItem('traderapp.zoom');
          return raw ? ((JSON.parse(raw) as Record<string, number>)['mini:1m'] ?? null) : null;
        }),
      )
      // Storage holds a bar count: one more than the logical range width.
      .toBe(Math.round(zoomed + 1));

    await terminal.page.reload();
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();
    await expect.poll(width).toBeCloseTo(zoomed, 0);
    // Slot-keyed storage: the main chart still opens at its own width.
    const main = (await terminal.chartState()).visibleRange!;
    expect(main.to - main.from).toBeCloseTo(mainBefore.to - mainBefore.from, 0);
  });

  test('the slot can be retimed, and the choice survives a reload', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    // Ships as 1m; move it to 15m.
    await terminal.page.getByTestId('mini-tf-0').selectOption('15m');

    // The wire follows: the resubscribe carries the new timeframe…
    const command = await backend.waitForCommand('subscribe');
    expect(command.extra_timeframes).toContain('15m');
    expect(command.extra_timeframes).not.toContain('1m');

    // …and the slot draws it. The mock serves 30 bars of 15m.
    await expect
      .poll(async () => (await terminal.miniChartState('15m'))?.barCount ?? 0)
      .toBeGreaterThan(0);
    expect((await terminal.miniChartState('15m'))!.timeframe).toBe('15m');
    expect(await terminal.miniChartState('1m')).toBeNull();

    // The choice is a preference, not session state.
    await terminal.page.reload();
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('mini-tf-0')).toHaveValue('15m');
    await expect
      .poll(async () => (await terminal.miniChartState('15m'))?.barCount ?? 0)
      .toBeGreaterThan(0);
  });

  test('follows the symbol', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    await terminal.setSymbol('TSLA');
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    expect((await terminal.miniChartState('1m'))!.barCount).toBeGreaterThan(0);
  });

  test('follows the theme', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();
    expect((await terminal.miniChartState('1m'))!.theme).toBe('dark');

    await terminal.themeToggle.click();

    await expect
      .poll(async () => (await terminal.miniChartState('1m'))!.theme)
      .toBe('light');
  });

  test('zooms and resets from its own header', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    const framed = (await terminal.miniChartState('1m'))!.visibleRange!;
    await terminal.page.getByLabel('Zoom in 1m chart').click();

    await expect
      .poll(async () => {
        const range = (await terminal.miniChartState('1m'))!.visibleRange!;
        return range.to - range.from;
      })
      .toBeLessThan(framed.to - framed.from);

    await terminal.miniReset('1m').click();

    await expect
      .poll(async () => {
        const range = (await terminal.miniChartState('1m'))!.visibleRange!;
        return Math.round(range.to - range.from);
      })
      .toBe(Math.round(framed.to - framed.from));
  });

  test('zooming the mini leaves the main chart where it was', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    const before = (await terminal.chartState()).visibleRange!;
    const miniWidth = async () => {
      const range = (await terminal.miniChartState('1m'))!.visibleRange!;
      return range.to - range.from;
    };
    const miniBefore = await miniWidth();

    await terminal.page.getByLabel('Zoom in 1m chart').click();
    // Wait for the mini to actually move. Reading the main chart straight
    // after the click proves nothing: a leak onto it would land on a later
    // frame too, so the assertion would pass before the damage was done.
    await expect.poll(miniWidth).toBeLessThan(miniBefore);

    const after = (await terminal.chartState()).visibleRange!;
    expect(after.to - after.from).toBeCloseTo(before.to - before.from, 5);
  });
});
