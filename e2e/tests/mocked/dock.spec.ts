import { expect, test } from '../../fixtures/test';

/**
 * The right-hand dock.
 *
 * The rail that used to be the mini-chart column. What matters in a browser
 * rather than a unit test is that switching tabs does not disturb the layout
 * or the main chart: the width is shared, the charts tab is genuinely
 * unmounted when another is open (a hidden chart container is zero-height and
 * lightweight-charts cannot size a pane inside one), and the choice survives
 * a reload.
 */
test.describe('dock', () => {
  test('opens on the context charts', async ({ terminal }) => {
    await terminal.waitForChart();

    await expect(terminal.dock).toBeVisible();
    await expect(terminal.dockTab('charts')).toHaveAttribute('aria-selected', 'true');
    await expect(terminal.miniCharts).toBeVisible();
  });

  test('offers a tab for each panel', async ({ terminal }) => {
    await terminal.waitForChart();

    for (const id of ['charts', 'fundamentals', 'news', 'filings'] as const) {
      await expect(terminal.dockTab(id)).toBeVisible();
    }
  });

  test('switching tabs unmounts the charts rather than hiding them', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    await terminal.dockTab('fundamentals').click();

    await expect(terminal.dockPanel('fundamentals')).toBeVisible();
    await expect(terminal.miniCharts).toHaveCount(0);
    await expect(terminal.dockTab('fundamentals')).toHaveAttribute('aria-selected', 'true');
    await expect(terminal.dockTab('charts')).toHaveAttribute('aria-selected', 'false');
  });

  test('the charts come back intact on return', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    await terminal.dockTab('news').click();
    await expect(terminal.dockPanel('news')).toBeVisible();
    await terminal.dockTab('charts').click();

    await terminal.waitForMiniCharts();
    expect((await terminal.miniChartState('1m'))!.timeframe).toBe('1m');
    await expect(terminal.tape).toBeVisible();
  });

  test('the main chart keeps its data through a tab switch', async ({ terminal }) => {
    await terminal.waitForChart();
    const before = await terminal.chartState();

    await terminal.dockTab('filings').click();
    await expect(terminal.dockPanel('filings')).toBeVisible();

    const after = await terminal.chartState();
    expect(after.barCount).toBe(before.barCount);
    expect(after.lastBar).toEqual(before.lastBar);
    expect(after.paneCount).toBe(before.paneCount);
    expect(after.timeframe).toBe(before.timeframe);
  });

  test('the rail keeps one width across every tab', async ({ terminal }) => {
    await terminal.waitForChart();
    const charts = await terminal.dock.boundingBox();

    await terminal.dockTab('news').click();
    await expect(terminal.dockPanel('news')).toBeVisible();
    const news = await terminal.dock.boundingBox();

    expect(news!.width).toBe(charts!.width);
  });

  test('remembers the open tab across a reload', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('fundamentals').click();
    await expect(terminal.dockPanel('fundamentals')).toBeVisible();

    await terminal.page.reload();
    await terminal.waitForChart();

    await expect(terminal.dockTab('fundamentals')).toHaveAttribute('aria-selected', 'true');
    await expect(terminal.dockPanel('fundamentals')).toBeVisible();
  });
});
