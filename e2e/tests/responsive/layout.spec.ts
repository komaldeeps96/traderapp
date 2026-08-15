import { expect, test } from '../../fixtures/test';

/**
 * A trading terminal is a desktop tool, but it should not fall apart when
 * opened on a tablet.
 */
test.describe('tablet layout', () => {
  test('renders the chart', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.chart).toBeVisible();
    expect((await terminal.chartState()).barCount).toBeGreaterThan(0);
  });

  test('keeps the sidebar usable', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.keyLevels).toBeVisible();
    await expect(terminal.scanner).toBeVisible();
  });

  test('does not scroll the page sideways', async ({ terminal }) => {
    await terminal.waitForChart();
    const overflows = await terminal.page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(overflows).toBe(false);
  });

  test('gives the chart real width', async ({ terminal }) => {
    await terminal.waitForChart();
    const box = await terminal.chart.boundingBox();
    expect(box!.width).toBeGreaterThan(300);
    expect(box!.height).toBeGreaterThan(200);
  });

  test('drops the mini charts rather than squeezing the main one', async ({ terminal }) => {
    // A tablet does not have the width for three charts. They are left out of
    // the tree entirely, not hidden with CSS — a chart engine built inside a
    // display:none container has no height to give its panes.
    await terminal.waitForChart();
    await expect(terminal.miniCharts).toHaveCount(0);
    expect(await terminal.miniChartState('1m')).toBeNull();
  });

  test('keeps the toolbar controls reachable', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.symbolInput).toBeVisible();
    await expect(terminal.timeframeTab('1d')).toBeVisible();
    await expect(terminal.themeToggle).toBeVisible();
  });

  test('still loads a symbol', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.setSymbol('TSLA');
    const command = await backend.waitForCommand('subscribe');
    expect(command.symbol).toBe('TSLA');
  });

  test('resizes the chart with the window', async ({ terminal }) => {
    await terminal.waitForChart();
    const before = (await terminal.chart.boundingBox())!.width;

    await terminal.page.setViewportSize({ width: 900, height: 700 });
    await expect.poll(async () => (await terminal.chart.boundingBox())!.width).toBeLessThan(before);
  });
});
