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
    // The reference row keeps TradingView's static snapshot; its live
    // counterpart ticks per bar in the session strip above.
    await expect(terminal.page.getByTestId('tp-mktcap')).toHaveText('$62.00M');
    // 12M shares outstanding times the ~$10 tape.
    await expect(terminal.page.getByTestId('bs-mcap')).toContainText('$12');
    await expect(terminal.page.getByTestId('tp-rotation')).toHaveText('1.7x');
    await expect(terminal.page.getByTestId('tp-relvol')).toHaveText('7.5x');
    await expect(terminal.page.getByTestId('tp-dayvol')).toHaveText('14.20M');

    // Without a share count the live figure has nothing to derive from and
    // stands down; the snapshot stays.
    await backend.pushInfo({ shares_outstanding: null });
    await expect(terminal.page.getByTestId('bs-mcap')).toHaveCount(0);
    await expect(terminal.page.getByTestId('tp-mktcap')).toHaveText('$62.00M');
  });

  test('shows borrow status, the IPO badge and a suspect float', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    // The fixture's shortable of 2.9 is above IBKR's easy-to-borrow line.
    await backend.pushInfo({ listed_days: 23, float_shares: 13_000_000 });

    await expect(terminal.page.getByTestId('tp-borrow')).toHaveText('ETB');
    await expect(terminal.page.getByTestId('tp-ipo')).toHaveText('IPO 23d');
    // 13M float against 12M shares outstanding is impossible data.
    await expect(terminal.page.getByTestId('tp-float')).toContainText('⚠');

    await backend.pushInfo({ shortable: 1.2, listed_days: null });
    await expect(terminal.page.getByTestId('tp-borrow')).toHaveText('NO BORROW');
    await expect(terminal.page.getByTestId('tp-ipo')).toHaveCount(0);
  });

  test('shows the all-time high with its headroom, and draws its line', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    // The fixture's ATH is 22.0; the mock tape trades around 10.
    await backend.pushInfo();

    await expect(terminal.page.getByTestId('tp-ath')).toContainText('22.00');
    await expect(terminal.page.getByTestId('tp-ath')).toContainText('%');
    await expect.poll(async () => (await terminal.chartState()).athLine).toBe(22.0);

    // Blue sky reads as such.
    await backend.pushInfo({ all_time_high: 5.0 });
    await expect(terminal.page.getByTestId('tp-ath')).toContainText('-');
  });

  test('shows halts, the reverse split, the pullback and float disagreement', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    await backend.pushInfo({
      halted: true,
      halts_today: 3,
      reverse_split_ratio: 12,
      reverse_split_days: 45,
      yahoo_float: 17_000_000, // vs the fixture's 8.5M — a 100% disagreement
      pullback_depth_pct: 38,
      pullback_vol_ratio: 0.4,
      pullback_bars: 4,
      pullback_leg_pct: 20,
    });

    await expect(terminal.page.getByTestId('tp-halted')).toHaveText('HALTED · 3');
    await expect(terminal.page.getByTestId('tp-reverse-split')).toHaveText('R/S 1:12 · 45d');
    const pullback = terminal.page.getByTestId('tp-pullback');
    await expect(pullback).toHaveText('PB 38% · 0.4× · 4b');
    await expect(pullback).toHaveAttribute('data-tone', 'healthy');
    await expect(terminal.page.getByTestId('tp-float')).toContainText('±100%');

    // Resumed but scarred: the chip stays as a count.
    await backend.pushInfo({ halted: false, halts_today: 3 });
    await expect(terminal.page.getByTestId('tp-halted')).toHaveText('HALTS 3');
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
