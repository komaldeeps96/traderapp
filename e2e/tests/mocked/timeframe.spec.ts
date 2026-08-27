import { expect, test } from '../../fixtures/test';

test.describe('timeframes', () => {
  test('offers every timeframe', async ({ terminal }) => {
    await terminal.waitForChart();
    for (const timeframe of ['10s', '1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']) {
      await expect(terminal.timeframeTab(timeframe)).toBeVisible();
    }
  });

  test('marks the active one — 10s is the default', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.timeframeTab('10s')).toHaveAttribute('aria-pressed', 'true');
    await expect(terminal.timeframeTab('1d')).toHaveAttribute('aria-pressed', 'false');
  });

  test('requests the timeframe that was clicked', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.selectTimeframe('15m');

    const command = await backend.waitForCommand('subscribe');
    expect(command.timeframe).toBe('15m');
    expect(command.symbol).toBe('AAPL');
  });

  test('redraws at the new timeframe', async ({ terminal }) => {
    await terminal.waitForChart();
    const before = (await terminal.chartState()).barCount;

    await terminal.selectTimeframe('1h');
    await expect.poll(async () => (await terminal.chartState()).timeframe).toBe('1h');
    expect((await terminal.chartState()).barCount).toBeLessThan(before);
  });

  test('drops series that do not belong to the new timeframe', async ({ terminal }) => {
    // Stale timestamps on a hidden series tear phantom gaps into the shared
    // time axis, so those series have to be removed, not just hidden.
    await terminal.waitForChart();
    expect((await terminal.chartState()).seriesIds).toContain('vwap');

    await terminal.selectTimeframe('1d');
    await expect.poll(async () => (await terminal.chartState()).timeframe).toBe('1d');

    const state = await terminal.chartState();
    expect(state.seriesIds).not.toContain('vwap');
    expect(state.seriesIds).not.toContain('pm_high');
    expect(state.seriesIds).toContain('ema9');
  });

  test('brings intraday series back on return', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.selectTimeframe('1d');
    await expect.poll(async () => (await terminal.chartState()).timeframe).toBe('1d');

    await terminal.selectTimeframe('1m');
    await expect.poll(async () => (await terminal.chartState()).timeframe).toBe('1m');
    expect((await terminal.chartState()).seriesIds).toContain('vwap');
  });

  test('every timeframe renders bars', async ({ terminal }) => {
    await terminal.waitForChart();
    for (const timeframe of ['5m', '15m', '30m', '1h', '4h', '1d']) {
      await terminal.selectTimeframe(timeframe);
      await expect.poll(async () => (await terminal.chartState()).timeframe).toBe(timeframe);
      expect((await terminal.chartState()).barCount).toBeGreaterThan(0);
    }
  });

  test('resets the view on each switch', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.selectTimeframe('1h');
    await expect.poll(async () => (await terminal.chartState()).timeframe).toBe('1h');

    const state = await terminal.chartState();
    expect(state.visibleRange).not.toBeNull();
    expect(state.visibleRange!.to).toBeGreaterThan(0);
  });
});
