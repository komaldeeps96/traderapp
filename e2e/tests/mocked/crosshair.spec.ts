import { expect, test } from '../../fixtures/test';

test.describe('crosshair readout', () => {
  test('shows the live bar when the pointer is off the chart', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.ohlcv).toHaveAttribute('data-hovering', 'false');
  });

  test('switches to the hovered bar', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.hoverChart(0.4);
    await expect(terminal.ohlcv).toHaveAttribute('data-hovering', 'true');
  });

  test('reads a different bar than the live one', async ({ terminal }) => {
    await terminal.waitForChart();
    const live = await terminal.ohlcvField('close').textContent();

    await terminal.hoverChart(0.2);
    await expect(terminal.ohlcv).toHaveAttribute('data-hovering', 'true');
    await expect.poll(async () => terminal.ohlcvField('close').textContent()).not.toBe(live);
  });

  test('returns to the live bar when the pointer leaves', async ({ terminal }) => {
    await terminal.waitForChart();
    const live = await terminal.ohlcvField('close').textContent();

    await terminal.hoverChart(0.2);
    await expect(terminal.ohlcv).toHaveAttribute('data-hovering', 'true');

    await terminal.moveMouseAway();
    await expect(terminal.ohlcv).toHaveAttribute('data-hovering', 'false');
    await expect(terminal.ohlcvField('close')).toHaveText(live ?? '');
  });

  test('the session strip reads the day as of the hovered bar', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    // Reference data for RVOL and rotation rides the info stream.
    await backend.pushInfo();

    const strip = terminal.page.getByTestId('bar-strip');
    await expect(strip).toHaveAttribute('data-hovering', 'false');
    await expect(terminal.page.getByTestId('bs-cumvol')).not.toHaveText('');
    await expect(terminal.page.getByTestId('bs-rvol')).toContainText('x');
    await expect(terminal.page.getByTestId('bs-rotation')).toContainText('x');

    // Windowed RVOL is server-stamped per bar as a readout-only series:
    // the strip reads it out, and the chart must NOT have painted it.
    await expect(terminal.page.getByTestId('bs-wrvol')).toContainText('x');
    const state = await terminal.chartState();
    expect(state.seriesIds).not.toContain('wrvol');
    expect(state.pointCounts['wrvol']).toBeGreaterThan(0);

    // Hovering an earlier bar must show a SMALLER cumulative volume — the
    // day had done less by then. That is the whole point of the strip.
    const parse = async () => {
      const text = (await terminal.page.getByTestId('bs-cumvol').textContent()) ?? '';
      const value = Number.parseFloat(text);
      return text.includes('M') ? value * 1e6 : text.includes('K') ? value * 1e3 : value;
    };
    const live = await parse();
    const wrvolLive = await terminal.page.getByTestId('bs-wrvol').textContent();
    await terminal.hoverChart(0.2);
    await expect(strip).toHaveAttribute('data-hovering', 'true');
    await expect.poll(parse).toBeLessThan(live);
    // The stamped series is a ramp, so an earlier bar reads a smaller value.
    await expect
      .poll(async () => terminal.page.getByTestId('bs-wrvol').textContent())
      .not.toBe(wrvolLive);
  });

  test('keeps open, high, low and close consistent', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.hoverChart(0.5);
    await expect(terminal.ohlcv).toHaveAttribute('data-hovering', 'true');

    const values = await Promise.all(
      (['open', 'high', 'low', 'close'] as const).map((field) =>
        terminal.ohlcvField(field).textContent(),
      ),
    );
    const [open, high, low, close] = values.map((text) => Number(text));
    expect(high).toBeGreaterThanOrEqual(Math.max(open, close));
    expect(low).toBeLessThanOrEqual(Math.min(open, close));
  });

  test('updates the indicator values as the crosshair moves', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.hoverChart(0.8);
    const late = await terminal.indicatorChip('ema9').textContent();

    await terminal.hoverChart(0.2);
    await expect.poll(async () => terminal.indicatorChip('ema9').textContent()).not.toBe(late);
  });

  test('marks a pre-market bar as extended hours', async ({ terminal }) => {
    // The fixture session starts before the open and crosses it, so the early
    // bars are pre-market and the later ones are not.
    await terminal.waitForChart();
    await terminal.hoverChart(0.12);
    await expect(terminal.ohlcv).toHaveAttribute('data-hovering', 'true');
    await expect(terminal.page.getByTestId('ohlcv-extended')).toBeVisible();
  });

  test('does not mark a regular-hours bar', async ({ terminal }) => {
    // Past ~0.9 the chart's right offset is empty space with no bar under it.
    await terminal.waitForChart();
    await terminal.hoverChart(0.7);
    await expect(terminal.ohlcv).toHaveAttribute('data-hovering', 'true');
    await expect(terminal.page.getByTestId('ohlcv-extended')).toBeHidden();
  });
});
