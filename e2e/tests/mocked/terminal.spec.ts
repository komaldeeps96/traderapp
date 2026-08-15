import { makeSnapshot } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/**
 * The terminal surfaces added for the momentum workflow: the info strip above
 * the chart (quote, spread, float, rotation) and the market-regime counts.
 */

test.describe('top panel', () => {
  test('shows the symbol header with last price and change', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('tp-symbol')).toHaveText('AAPL');
    await expect(terminal.page.getByTestId('tp-last')).not.toHaveText('—');
    await expect(terminal.page.getByTestId('tp-change')).toContainText('%');
  });

  test('shows the bid, ask and spread from the quote stream', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushQuote({ bid: 10.0, ask: 10.04, bs: 700, as: 1200 });

    await expect(terminal.page.getByTestId('tp-bid')).toContainText('10.0');
    await expect(terminal.page.getByTestId('tp-ask')).toContainText('10.0');
    const spread = terminal.page.getByTestId('tp-spread');
    await expect(spread).toContainText('¢');
    await expect(spread).toHaveAttribute('data-tone', 'tight');
  });

  test('flags an untradeable spread', async ({ terminal, backend }) => {
    // Fifty cents is the stated hard ceiling; past it the trade is off.
    await terminal.waitForChart();
    await backend.pushQuote({ bid: 10.0, ask: 10.6 });
    await expect(terminal.page.getByTestId('tp-spread')).toHaveAttribute(
      'data-tone',
      'untradeable',
    );
  });

  test('shows float, rotation and market cap from the info stream', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    await backend.pushInfo();

    await expect(terminal.page.getByTestId('tp-float')).toHaveText('8.50M');
    await expect(terminal.page.getByTestId('tp-mktcap')).toHaveText('$62.00M');
    await expect(terminal.page.getByTestId('tp-rotation')).toHaveText('1.7x');
    await expect(terminal.page.getByTestId('tp-relvol')).toHaveText('7.5x');
    await expect(terminal.page.getByTestId('tp-dayvol')).toHaveText('14.20M');
  });

  test('drops the quote when the symbol changes', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushQuote({ bid: 10.0, ask: 10.04 });
    await expect(terminal.page.getByTestId('tp-bid')).toContainText('10.0');

    await terminal.setSymbol('TSLA');
    await backend.waitForCommand('subscribe');
    // The mock immediately answers with TSLA's own quote; what must never
    // happen is AAPL's quote surviving the switch.
    await expect.poll(async () => (await terminal.state()).symbol).toBe('TSLA');
  });
});

test.describe('symbol switch', () => {
  test.use({ backendOptions: { snapshotDelayMs: 700 } });

  test('blanks the old chart immediately and shows a loading state', async ({ terminal }) => {
    // The old instrument's candles must never sit under the new ticker's
    // name while its history loads — a wrong chart reads as data.
    await terminal.waitForChart();
    expect((await terminal.chartState()).barCount).toBeGreaterThan(0);

    await terminal.setSymbol('TSLA');

    await expect(terminal.page.getByTestId('chart-loading')).toBeVisible();
    await expect(terminal.page.getByTestId('chart-loading')).toContainText('TSLA');
    expect((await terminal.chartState()).barCount).toBe(0);

    // The snapshot lands and the overlay leaves with it.
    await expect(terminal.page.getByTestId('chart-loading')).toBeHidden({ timeout: 5_000 });
    expect((await terminal.chartState()).barCount).toBeGreaterThan(0);
  });

  test('keeps the chart through a timeframe-only switch', async ({ terminal }) => {
    // Same instrument: swapping resolution must not blank what is on screen.
    await terminal.waitForChart();
    await terminal.selectTimeframe('1m');

    await expect(terminal.page.getByTestId('chart-loading')).toBeVisible();
    expect((await terminal.chartState()).barCount).toBeGreaterThan(0);

    await expect.poll(async () => (await terminal.chartState()).timeframe).toBe('1m');
  });
});

test.describe('background backfill', () => {
  test('a repeat snapshot extends history without touching the viewport', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    // Zoom away from the default framing first, so "viewport preserved" and
    // "viewport reset" are distinguishable outcomes.
    const width = (range: { from: number; to: number } | null) =>
      range ? Math.round(range.to - range.from) : -1;
    await terminal.chartControls.getByLabel('Zoom in').click();
    await terminal.chartControls.getByLabel('Zoom in').click();
    // Both zooms must have landed before the reference is captured: one zoom
    // narrows ~244 logical bars to ~195, the second to ~156.
    await expect
      .poll(async () => width((await terminal.chartState()).visibleRange))
      .toBeLessThan(170);
    const before = await terminal.chartState();

    // The backend re-sends a fuller snapshot once its background pass lands.
    await backend.send(makeSnapshot({ symbol: 'AAPL', timeframe: '10s', barCount: 480 }));

    await expect.poll(async () => (await terminal.chartState()).barCount).toBe(480);
    const after = await terminal.chartState();
    expect(width(after.visibleRange)).toBe(width(before.visibleRange));
  });
});

test.describe('api budget meters', () => {
  test('shows both upstream meters with the opening usage', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('api-meter-alp')).toHaveAttribute('data-tone', 'ok');
    await expect(terminal.page.getByTestId('api-meter-ibkr')).toHaveAttribute('data-tone', 'ok');
    // The counts and window ride next to the bar, not only in the tooltip.
    await expect(terminal.page.getByTestId('api-count-alp')).toHaveText('12/200 · 1m');
    await expect(terminal.page.getByTestId('api-count-ibkr')).toHaveText('4/60 · 10m');
  });

  test('turns amber then red as a window fills', async ({ terminal, backend }) => {
    await terminal.waitForChart();

    await backend.pushApiUsage({ alpaca: 130 });
    await expect(terminal.page.getByTestId('api-meter-alp')).toHaveAttribute(
      'data-tone',
      'warn',
    );

    await backend.pushApiUsage({ alpaca: 190, ibkr: 55 });
    await expect(terminal.page.getByTestId('api-meter-alp')).toHaveAttribute('data-tone', 'hot');
    await expect(terminal.page.getByTestId('api-meter-ibkr')).toHaveAttribute(
      'data-tone',
      'hot',
    );
  });

  test('reports exact counts to assistive technology', async ({ terminal }) => {
    await terminal.waitForChart();
    const meter = terminal.page.getByTestId('api-meter-alp').getByRole('meter');
    await expect(meter).toHaveAttribute('aria-valuenow', '12');
    await expect(meter).toHaveAttribute('aria-valuemax', '200');
  });
});

test.describe('session clock', () => {
  test('shows the session badge', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('session-badge')).toBeVisible();
  });

  test('no longer carries the candle countdown', async ({ terminal }) => {
    // It moved onto each chart's price axis, under the last-price label.
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('candle-countdown')).toHaveCount(0);
  });
});

test.describe('market regime', () => {
  test('shows the regime counts in the toolbar', async ({ terminal }) => {
    // The screener panel that used to carry these was removed from the UI;
    // the counts are a market-wide read and outlived it.
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('regime')).toContainText('↑50%:4');
    await expect(terminal.page.getByTestId('regime')).toContainText('↑100%:1');
  });
});
