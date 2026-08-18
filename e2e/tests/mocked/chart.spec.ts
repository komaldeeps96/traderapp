import type { TerminalPage } from '../../pages/TerminalPage';
import { expect, test } from '../../fixtures/test';

/** The time scale applies range changes on its own frame, so reads are polled. */
function rangeWidth(terminal: TerminalPage) {
  return async () => {
    const range = (await terminal.chartState()).visibleRange!;
    return range.to - range.from;
  };
}

test.describe('chart rendering', () => {
  test('loads the session symbol on open', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.symbolInput).toHaveValue('AAPL');
  });

  test('draws every bar it was sent', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const state = await terminal.chartState();
    expect(state.barCount).toBe(backend.lastSnapshot()!.bars.length);
  });

  test('builds a series for each indicator on the timeframe', async ({ terminal }) => {
    await terminal.waitForChart();
    const state = await terminal.chartState();
    expect(state.seriesIds).toEqual(
      expect.arrayContaining(['ema9', 'ema20', 'ema45', 'vwap', 'pm_high', 'prev_day_close']),
    );
  });

  test('fills the moving averages with points', async ({ terminal }) => {
    await terminal.waitForChart();
    const state = await terminal.chartState();
    // A series that exists but holds nothing draws an invisible line — the
    // failure this catches.
    expect(state.pointCounts.ema9).toBeGreaterThan(100);
    expect(state.pointCounts.ema20).toBeGreaterThan(100);
  });

  test('compresses key levels rather than repeating a value per bar', async ({ terminal }) => {
    await terminal.waitForChart();
    const state = await terminal.chartState();
    expect(state.pointCounts.prev_day_close).toBeLessThan(10);
    expect(state.pointCounts.prev_day_close).toBeGreaterThan(0);
  });

  test('gives volume its own pane', async ({ terminal }) => {
    await terminal.waitForChart();
    const state = await terminal.chartState();
    expect(state.paneCount).toBe(2);
    expect(state.hasVolumePane).toBe(true);
  });

  test('draws a pane only on the timeframes its indicator is configured for', async ({
    terminal,
  }) => {
    // Panes are config-driven. MACD is enabled on 1m alone — on the 10s tape
    // it whipsaws — so the pane has to appear and disappear with the
    // timeframe rather than sitting there empty.
    await terminal.waitForChart();
    expect((await terminal.chartState()).hasMacdPane).toBe(false);

    await terminal.selectTimeframe('1m');
    await terminal.waitForChart();
    expect((await terminal.chartState()).hasMacdPane).toBe(true);

    await terminal.selectTimeframe('10s');
    await terminal.waitForChart();
    expect((await terminal.chartState()).hasMacdPane).toBe(false);
  });

  test('opens on the most recent bars rather than the whole history', async ({ terminal }) => {
    await terminal.waitForChart();
    const state = await terminal.chartState();
    expect(state.visibleRange).not.toBeNull();
    expect(state.visibleRange!.to).toBeGreaterThan(state.visibleRange!.from);
    expect(state.visibleRange!.to - state.visibleRange!.from).toBeLessThan(state.barCount);
  });

  test('shows the OHLCV readout', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.ohlcv).toBeVisible();
    await expect(terminal.ohlcvField('close')).not.toHaveText('—');
  });

  test('reports a canvas that actually painted', async ({ terminal }) => {
    await terminal.waitForChart();
    const painted = await terminal.page.evaluate(() => {
      const canvas = document.querySelector('[data-testid="chart-canvas"] canvas');
      return canvas instanceof HTMLCanvasElement && canvas.width > 0 && canvas.height > 0;
    });
    expect(painted).toBe(true);
  });

  test('logs no console errors while loading', async ({ page, terminal }) => {
    const errors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text());
    });
    await terminal.waitForChart();
    expect(errors).toEqual([]);
  });
});

test.describe('chart navigation', () => {
  test('the controls sit centred above the sub-panes', async ({ terminal }) => {
    // They once floated flush in the bottom-right corner, landing on the time
    // axis in translucent white — present in the DOM, passing every click
    // test, and invisible to a human. Placement is what makes them usable, so
    // placement is what this asserts.
    await terminal.waitForChart();
    const controls = terminal.page.getByTestId('chart-controls').locator('div').first();
    await expect(controls).toBeVisible();

    // The offset is measured from the panes once they have laid out, so the
    // controls settle a beat after the chart is ready.
    await expect
      .poll(async () => {
        const box = (await controls.boundingBox())!;
        const chart = (await terminal.chart.boundingBox())!;
        return Math.round(chart.y + chart.height - (box.y + box.height));
      })
      .toBeGreaterThan(120);

    const box = (await controls.boundingBox())!;
    const chart = (await terminal.chart.boundingBox())!;

    const controlsCentre = box.x + box.width / 2;
    const chartCentre = chart.x + chart.width / 2;
    expect(Math.abs(controlsCentre - chartCentre)).toBeLessThan(60);
    expect(box.y).toBeGreaterThan(chart.y);
  });

  test('the controls follow the sub-pane height', async ({ terminal }) => {
    // They must clear the sub-panes at any viewport — an earlier version
    // pinned them flush in the corner, where they landed on the time axis in
    // translucent white: present, clickable, and invisible.
    //
    // Asserted against the engine's own reported offset rather than a fixed
    // pixel clearance. A hardcoded one was tried and sat three pixels from
    // the boundary at 700px tall, so it passed or failed on sub-pixel
    // rounding and read as flakiness.
    await terminal.waitForChart();
    const controls = terminal.page.getByTestId('chart-controls').locator('div').first();

    const clears = async () => {
      const box = await controls.boundingBox();
      const chart = await terminal.chart.boundingBox();
      if (!box || !chart) return null;
      const { subPaneOffset } = await terminal.chartState();
      return box.y + box.height <= chart.y + chart.height - subPaneOffset;
    };

    await expect.poll(clears).toBe(true);

    const tall = (await terminal.chartState()).subPaneOffset;
    await terminal.page.setViewportSize({ width: 1440, height: 700 });

    // The offset is measured, not fixed, so a shorter chart moves it.
    await expect.poll(async () => (await terminal.chartState()).subPaneOffset).not.toBe(tall);
    await expect.poll(clears).toBe(true);
  });

  test('the volume pane carries no axis tag that could drift onto the controls', async ({
    terminal,
  }) => {
    // A histogram's price tag rides at the height of its last value, so on a
    // normal session it wanders into the middle of the pane — straight over
    // the buttons.
    await terminal.waitForChart();
    const state = await terminal.chartState();

    expect(state.paneSeries.volume).not.toBeNull();
    expect(state.paneSeries.volume!.axisLabel).toBe(false);
    expect(state.paneSeries.volume!.title).toBe('');
  });

  test('each control is reachable by its accessible name', async ({ terminal }) => {
    await terminal.waitForChart();
    for (const name of ['Scroll left', 'Zoom out', 'Zoom in', 'Scroll right', 'Reset view']) {
      await expect(terminal.chartControls.getByRole('button', { name })).toBeVisible();
    }
  });

  test('zooming in narrows the visible range', async ({ terminal }) => {
    await terminal.waitForChart();
    const before = (await terminal.chartState()).visibleRange!;
    await terminal.chartControls.getByRole('button', { name: 'Zoom in' }).click();
    await expect.poll(rangeWidth(terminal)).toBeLessThan(before.to - before.from);
  });

  test('zooming out widens it', async ({ terminal }) => {
    await terminal.waitForChart();
    // Zoom in first so there is room to widen: the opening view already shows
    // the whole fixture, and the time scale clamps past that. The zoom has to
    // be observed landing before the width is read — the scale applies it on
    // its own frame, so a read taken too early belongs to the previous view
    // and the zoom out below then gets measured against the wrong baseline.
    const opened = await rangeWidth(terminal)();
    await terminal.chartControls.getByRole('button', { name: 'Zoom in' }).click();
    await expect.poll(rangeWidth(terminal)).toBeLessThan(opened);
    const zoomed = await rangeWidth(terminal)();

    await terminal.chartControls.getByRole('button', { name: 'Zoom out' }).click();
    await expect.poll(rangeWidth(terminal)).toBeGreaterThan(zoomed);
  });

  test('zooming out lands back exactly where zooming in started', async ({ terminal }) => {
    // The two steps have to be inverses. They were not: zoom in trimmed a
    // tenth off each edge for 0.8x, zoom out added a tenth back for 1.2x, so
    // a round trip returned 0.96x and repeated tapping crept the view inwards.
    await terminal.waitForChart();
    const opened = await rangeWidth(terminal)();

    await terminal.chartControls.getByRole('button', { name: 'Zoom in' }).click();
    await expect.poll(rangeWidth(terminal)).toBeLessThan(opened);
    await terminal.chartControls.getByRole('button', { name: 'Zoom out' }).click();
    await expect.poll(rangeWidth(terminal)).toBeCloseTo(opened, 1);
  });

  test('scrolling moves the window without resizing it', async ({ terminal }) => {
    await terminal.waitForChart();
    const before = (await terminal.chartState()).visibleRange!;
    await terminal.chartControls.getByRole('button', { name: 'Scroll left' }).click();

    await expect
      .poll(async () => (await terminal.chartState()).visibleRange!.from)
      .toBeLessThan(before.from);
    await expect.poll(rangeWidth(terminal)).toBeCloseTo(before.to - before.from, 1);
  });

  test('reset returns to the opening view', async ({ terminal }) => {
    await terminal.waitForChart();
    const width = async () => {
      const range = (await terminal.chartState()).visibleRange!;
      return range.to - range.from;
    };

    const original = await width();
    await terminal.chartControls.getByRole('button', { name: 'Zoom in' }).click();
    await expect.poll(width).toBeLessThan(original);

    await terminal.page.getByTestId('reset-view').click();
    // The time scale applies a range change on its own frame, so this polls
    // rather than reading straight after the click.
    await expect.poll(width).toBeCloseTo(original, 0);
  });
});

/**
 * Time left in the current bar, on the price axis.
 *
 * It is drawn into the axis by a series primitive, so there is no element to
 * query — the engine's own report is the only handle a test has on it. What
 * matters is that every chart counts its own timeframe, because a 10-second
 * bar and a 5-minute bar are shown side by side.
 */
test.describe('bar countdown', () => {
  test('counts the current bar down on the price axis', async ({ terminal }) => {
    await terminal.waitForChart();
    const countdown = (await terminal.chartState()).countdown;

    expect(countdown).not.toBeNull();
    // The default chart is 10s, so it never reads more than ten seconds.
    expect(countdown!.text).toMatch(/^\d{1,2}s$/);
    expect(Number(countdown!.text.replace('s', ''))).toBeLessThanOrEqual(10);
  });

  test('ticks down as the bar runs', async ({ terminal }) => {
    await terminal.waitForChart();
    const first = (await terminal.chartState()).countdown!.text;

    await expect
      .poll(async () => (await terminal.chartState()).countdown!.text, { timeout: 5_000 })
      .not.toBe(first);
  });

  test('counts minutes and seconds on a longer bar', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.selectTimeframe('5m');
    await terminal.waitForChart();

    await expect
      .poll(async () => (await terminal.chartState()).countdown?.text ?? '')
      .toMatch(/^\d:\d{2}$/);
  });

  test('drops it on a timeframe whose bar does not close today', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.selectTimeframe('1d');
    await terminal.waitForChart();

    await expect.poll(async () => (await terminal.chartState()).countdown).toBeNull();
  });

  test('each mini chart counts its own timeframe', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.waitForMiniCharts();

    // The main chart is on 10s and reads "9s"; the minis are on minutes and
    // read "m:ss". One shared clock could not produce both.
    expect((await terminal.chartState()).countdown!.text).toMatch(/^\d{1,2}s$/);
    for (const timeframe of ['1m', '5m'] as const) {
      const mini = await terminal.miniChartState(timeframe);
      expect(mini!.countdown!.text).toMatch(/^\d:\d{2}$/);
    }
  });
});
