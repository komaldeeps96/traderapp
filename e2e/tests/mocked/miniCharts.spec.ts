import { expect, test } from '../../fixtures/test';

/**
 * The 1m and 5m context charts beside the main one.
 *
 * Two things are worth a browser test rather than a unit test. First, that
 * they are genuinely minimal: they draw onto a shared canvas with the same
 * engine as the main chart, and the whole point is that the ~30 key levels,
 * MACD and the dollar grid do *not* come with it. Second, that the main chart
 * is unaffected — the minis subscribe to extra timeframes on the same socket,
 * and a bug there shows up as the main chart quietly losing its levels.
 */
test.describe('mini charts', () => {
  test('draws a 1m and a 5m chart beside the main one', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    await expect(terminal.miniCharts).toBeVisible();
    await expect(terminal.miniChart('1m')).toBeVisible();
    await expect(terminal.miniChart('5m')).toBeVisible();

    expect((await terminal.miniChartState('1m'))!.timeframe).toBe('1m');
    expect((await terminal.miniChartState('5m'))!.timeframe).toBe('5m');
  });

  test('asks the server for both timeframes alongside the main chart', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    const command = await backend.waitForCommand('subscribe');
    expect(command.extra_timeframes).toEqual(['1m', '5m']);
  });

  test('carries only the two EMAs and volume', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    for (const timeframe of ['1m', '5m'] as const) {
      const mini = (await terminal.miniChartState(timeframe))!;
      expect(mini.seriesIds).toHaveLength(2);
      expect(mini.seriesIds).toContain('ema9');
      expect(mini.seriesIds).toContain('ema20');
      expect(mini.hasVolumePane).toBe(true);
      expect(mini.hasTradesPane).toBe(false);
      expect(mini.dollarLineCount).toBe(0);
      expect(mini.bands).toEqual([]);
    }
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
    // is a smear; 60 is the window these are read at.
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    for (const timeframe of ['1m', '5m'] as const) {
      const range = (await terminal.miniChartState(timeframe))!.visibleRange!;
      expect(Math.round(range.to - range.from)).toBe(59);
    }
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

  test('zooming a mini leaves the main chart where it was', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    const before = (await terminal.chartState()).visibleRange!;
    await terminal.page.getByLabel('Zoom in 5m chart').click();

    const after = (await terminal.chartState()).visibleRange!;
    expect(after.to - after.from).toBeCloseTo(before.to - before.from, 5);
  });
});
