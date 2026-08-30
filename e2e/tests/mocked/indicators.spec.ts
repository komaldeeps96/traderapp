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

  test('reports the choice to the server', async ({ terminal, backend }) => {
    // This used to be a localStorage round trip verified with a reload. The
    // toggle now lives in state.yaml, so what the page owes is the command —
    // the reload half is proved against the real backend, in the fullstack
    // suite, where the session that comes back is not a fixed fixture.
    await terminal.waitForChart();
    await terminal.indicatorChip('ema9').getByRole('button').click();
    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(false);

    const command = await backend.waitForCommand('indicators.visibility');
    expect(command).toMatchObject({ timeframe: '10s' });
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

test.describe('toggles the server remembers', () => {
  // Visibility used to be a browser preference. It now arrives with the
  // session, so a chart opens the same way on any machine the terminal runs on.
  test.use({ backendOptions: { sessionIndicators: { '10s': { ema9: false } } } });

  test('opens with an indicator the server has switched off', async ({ terminal }) => {
    await terminal.waitForChart();
    expect((await terminal.chartState()).visible.ema9).toBe(false);
    await expect(terminal.indicatorChip('ema9')).toHaveAttribute('data-visible', 'false');
  });

  test('leaves everything else on the config defaults', async ({ terminal }) => {
    // Only the difference is stored, so anything untouched still follows
    // indicators.yaml rather than a saved copy of it.
    await terminal.waitForChart();
    expect((await terminal.chartState()).visible.ema20).toBe(true);
  });

  test('switches it back on from the stored state', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.indicatorChip('ema9').getByRole('button').click();
    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(true);
  });
});

test.describe('reporting a toggle to the server', () => {
  test('sends the whole picture, not just the one that changed', async ({ terminal, backend }) => {
    // The server reduces this to the deltas. Sending the whole picture is
    // what lets it do that against the *current* defaults, so the two can
    // never disagree about what "default" means.
    await terminal.waitForChart();
    await terminal.indicatorChip('ema9').getByRole('button').click();
    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(false);

    const command = await backend.waitForCommand('indicators.visibility');
    expect(command).toMatchObject({
      timeframe: '10s',
      visible: { ema9: false, ema20: true },
    });
  });

  test('reports each timeframe under its own name', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.selectTimeframe('1d');
    await terminal.waitForChart();
    await terminal.indicatorChip('ema9').getByRole('button').click();
    await expect.poll(async () => (await terminal.chartState()).visible.ema9).toBe(false);

    const command = await backend.waitForCommand('indicators.visibility');
    expect(command).toMatchObject({ timeframe: '1d' });
  });
});
