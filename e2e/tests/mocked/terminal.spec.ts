import { makeNextBar, makeSnapshot, REGULAR_OPEN } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/**
 * The terminal surfaces added for the momentum workflow: the info strip above
 * the chart (quote, spread, float, rotation) and the market-regime counts.
 */

test.describe('top panel', () => {
  test('shows the last price and change, and names the instrument once', async ({
    terminal,
  }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('tp-last')).not.toHaveText('—');
    await expect(terminal.page.getByTestId('tp-change')).toContainText('%');

    // The ticker is the input's job; the header carries the name beside it
    // rather than a second copy of the symbol.
    await expect(terminal.symbolInput).toHaveValue('AAPL');
    await expect(terminal.page.getByTestId('tb-company')).toHaveText('Fixture Industries');
    await expect(terminal.page.getByTestId('tp-symbol')).toHaveCount(0);
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
    await expect(terminal.page.getByTestId('tp-rot')).toHaveText('1.7x');
    await expect(terminal.page.getByTestId('tp-rvol')).toHaveText('7.5x');
    await expect(terminal.page.getByTestId('tp-vol')).toHaveText('14.20M');
    // Two caps: 12M shares on yesterday's $8.40 close, and the same shares
    // on the ~$10 tape. The pair is the read — what the company was worth
    // before the move against what it is being bid at now.
    await expect(terminal.page.getByTestId('tp-mcap')).toHaveText('$100.80M');
    await expect(terminal.page.getByTestId('tp-cmcap')).toContainText('$12');

    // Without a share count neither can be derived; the reference falls back
    // to TradingView's snapshot and the current one stands down.
    await backend.pushInfo({ shares_outstanding: null });
    await expect(terminal.page.getByTestId('tp-mcap')).toHaveText('$62.00M');
    await expect(terminal.page.getByTestId('tp-cmcap')).toHaveText('—');
  });

  test('the reference cap holds still while the current one tracks the tape', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    await backend.pushInfo();
    await expect(terminal.page.getByTestId('tp-mcap')).toHaveText('$100.80M');

    const current = await terminal.page.getByTestId('tp-cmcap').textContent();
    await terminal.hoverChart(0.2);
    // The current cap rewinds with the crosshair; the reference does not.
    await expect.poll(async () => terminal.page.getByTestId('tp-cmcap').textContent()).not.toBe(
      current,
    );
    await expect(terminal.page.getByTestId('tp-mcap')).toHaveText('$100.80M');
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

  /**
   * The reopen window.
   *
   * The one condition in the playbook with a large measured effect behind
   * it, so what earns a browser test is that the strip actually reaches the
   * three states — the measured cohort, the hour that falls outside it, and
   * the already-extended case that measured negative — and that it clears
   * itself when the fifteen minutes are up rather than sitting there all day.
   */
  test('reads the minutes after a resume', async ({ terminal, backend }) => {
    await terminal.waitForChart();

    // Resumed at 09:40 New York, ninety seconds ago, up 19% on the day.
    const resumed = REGULAR_OPEN + 600;
    await backend.pushInfo({
      halted: false,
      halts_today: 1,
      halt_resumed_at: resumed,
      generated_at: resumed + 90,
    });

    const reopen = terminal.page.getByTestId('tp-reopen');
    await expect(reopen).toHaveText('REOPEN 1:30');
    await expect(reopen).toHaveAttribute('data-tone', 'aligned');

    // Sixteen minutes later the measurement has nothing left to say.
    await backend.pushInfo({ generated_at: resumed + 960 });
    await expect(reopen).toHaveCount(0);
  });

  test('separates a late reopen from an already-extended one', async ({ terminal, backend }) => {
    await terminal.waitForChart();

    // 10:35 New York — past the hour the cohort covers.
    await backend.pushInfo({
      halted: false,
      halts_today: 1,
      halt_resumed_at: REGULAR_OPEN + 3900,
      generated_at: REGULAR_OPEN + 3960,
    });
    await expect(terminal.page.getByTestId('tp-reopen')).toHaveAttribute('data-tone', 'late');

    // Inside the hour, but reopening on a stock already up 40% from the
    // fixture's 8.40 close — the one bucket that measured negative.
    await backend.send(makeNextBar(backend.lastSnapshot()!, { c: 11.8 }));
    await backend.pushInfo({
      halt_resumed_at: REGULAR_OPEN + 600,
      generated_at: REGULAR_OPEN + 660,
    });
    await expect(terminal.page.getByTestId('tp-reopen')).toHaveAttribute('data-tone', 'extended');
  });

  test('names the LULD band tier beside the headroom', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushInfo({ halt_active: true, halt_band_pct: 20 });
    // Two headroom percentages do not say how wide the band is; the tier is
    // fixed by last night's close and decides whether a break has room.
    const chip = terminal.page.getByTestId('tp-halt');
    await expect(chip).toContainText('LULD 20%');
    // The arrows carry the direction, so the distances are unsigned: a "+"
    // beside a down arrow reads as a move rather than a distance.
    await expect(chip).not.toContainText('+');
  });

  test('says a band is already past rather than reporting negative room', async ({
    terminal,
    backend,
  }) => {
    // The band reference is a five-minute mean, so on a fast mover price
    // trades through the upper band routinely. "−6.8%" beside "+23.7%" reads
    // as room in both directions when one side is simply gone.
    await terminal.waitForChart();
    await backend.pushInfo({ halt_active: true, halt_up: 9.0, halt_down: 8.0, halt_ref: 8.5 });

    const chip = terminal.page.getByTestId('tp-halt');
    await expect(chip).toContainText('↑PAST');
    await expect(chip).not.toContainText('-');
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
    // The counts ride next to the bar, not only in the tooltip; the window
    // length is fixed per upstream and stays on the hover.
    await expect(terminal.page.getByTestId('api-count-alp')).toHaveText('12/200');
    await expect(terminal.page.getByTestId('api-count-ibkr')).toHaveText('4/60');
    await expect(terminal.page.getByTestId('api-meter-alp')).toHaveAttribute(
      'title',
      /in the last 1m/,
    );
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

/**
 * The news clock.
 *
 * Issuers schedule press releases on the hour and the half hour, densest at
 * 8:00 and 8:30, and the morning's whole opportunity set follows that
 * calendar. So the clock that matters is not "how long until the open" but
 * "how long until news can land" — and then whether it did. The wall clock
 * is frozen here because the chip is a function of it and nothing else.
 *
 * 5 March 2024 is on EST, so New York is UTC−5.
 */
test.describe('news slot clock', () => {
  const nyTime = (hour: number, minute: number, second = 0) =>
    new Date(Date.UTC(2024, 2, 5, hour + 5, minute, second));

  test('counts down to the next scheduled window', async ({ terminal }) => {
    await terminal.page.clock.setFixedTime(nyTime(8, 28, 30));
    await terminal.waitForChart();

    const chip = terminal.page.getByTestId('news-slot');
    await expect(chip).toHaveText('8:30 1:30');
    await expect(chip).toHaveAttribute('data-state', 'waiting');
    // 8:00 and 8:30 are the two the release calendar peaks behind.
    await expect(chip).toHaveAttribute('data-dense', 'true');
  });

  test('switches to watching once the mark passes', async ({ terminal }) => {
    await terminal.page.clock.setFixedTime(nyTime(8, 30, 42));
    await terminal.waitForChart();

    const chip = terminal.page.getByTestId('news-slot');
    await expect(chip).toHaveText('8:30 +0:42');
    await expect(chip).toHaveAttribute('data-state', 'open');
  });

  test('drops the countdown when the next window is hours away', async ({ terminal }) => {
    // A terminal left open overnight would otherwise read "7:00 300:00",
    // which is five hours stated in minutes.
    await terminal.page.clock.setFixedTime(nyTime(2, 0));
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('news-slot')).toHaveText('7:00');
  });

  test('keeps the countdown once the window is within the hour', async ({ terminal }) => {
    await terminal.page.clock.setFixedTime(nyTime(6, 40));
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('news-slot')).toHaveText('7:00 20:00');
  });

  test('stops counting past the last initiation time', async ({ terminal }) => {
    await terminal.page.clock.setFixedTime(nyTime(9, 20));
    await terminal.waitForChart();

    const chip = terminal.page.getByTestId('news-slot');
    await expect(chip).toHaveText('NO NEW');
    await expect(chip).toHaveAttribute('data-state', 'late');
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
