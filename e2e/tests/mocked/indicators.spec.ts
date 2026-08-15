import { expect, test } from '../../fixtures/test';

test.describe('indicator toggles', () => {
  test('lists the overlays for the timeframe', async ({ terminal }) => {
    await terminal.waitForChart();
    for (const id of ['ema9', 'ema20', 'ema45', 'vwap']) {
      await expect(terminal.indicatorChip(id)).toBeVisible();
    }
  });

  test('shows each indicator’s current value', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.indicatorChip('ema9')).toContainText(/\d+\.\d{2}/);
  });

  test('hides a series when toggled off', async ({ terminal }) => {
    await terminal.waitForChart();
    expect((await terminal.chartState()).visible.ema9).toBe(true);

    await terminal.indicatorChip('ema9').getByRole('button').click();

    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(false);
    await expect(terminal.indicatorChip('ema9')).toHaveAttribute('data-visible', 'false');
  });

  test('shows it again when toggled back on', async ({ terminal }) => {
    await terminal.waitForChart();
    const toggle = terminal.indicatorChip('ema9').getByRole('button');

    await toggle.click();
    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(false);

    await toggle.click();
    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(true);
  });

  test('leaves the other series alone', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.indicatorChip('ema9').getByRole('button').click();
    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(false);
    expect((await terminal.chartState()).visible.ema20).toBe(true);
  });

  test('keeps the data even while hidden', async ({ terminal }) => {
    // Hiding must not clear the series, or the readout loses its value.
    await terminal.waitForChart();
    const before = (await terminal.chartState()).pointCounts.ema9;
    await terminal.indicatorChip('ema9').getByRole('button').click();
    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(false);
    expect((await terminal.chartState()).pointCounts.ema9).toBe(before);
  });

  test('remembers the choice across a reload', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.indicatorChip('ema9').getByRole('button').click();
    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(false);

    await terminal.page.reload();
    await terminal.waitForChart();
    expect((await terminal.chartState()).visible.ema9).toBe(false);
  });

  test('remembers a choice per timeframe', async ({ terminal }) => {
    // The overlays wanted on a 10-second chart are rarely the ones wanted daily.
    await terminal.waitForChart();
    await terminal.indicatorChip('ema9').getByRole('button').click();
    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(false);

    await terminal.selectTimeframe('1d');
    await expect.poll(async () => (await terminal.state()).timeframe).toBe('1d');
    expect((await terminal.chartState()).visible.ema9).toBe(true);

    await terminal.selectTimeframe('10s');
    await expect.poll(async () => (await terminal.state()).timeframe).toBe('10s');
    expect((await terminal.chartState()).visible.ema9).toBe(false);
  });

  test('announces its state to assistive technology', async ({ terminal }) => {
    await terminal.waitForChart();
    const toggle = terminal.indicatorChip('ema9').getByRole('button');
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  });
});
