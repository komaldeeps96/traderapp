import { SCANNER_TIERS, makeScannerRows } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

test.describe('scanner without IBKR', () => {
  test('says why it is empty', async ({ terminal }) => {
    // Scanning is IBKR-only with no Alpaca equivalent, so an empty table with
    // no explanation would just read as a bug.
    await terminal.waitForChart();
    await expect(terminal.scannerNote()).toBeVisible();
    await expect(terminal.scannerNote()).toContainText('IBKR');
  });

  test('disables the filters', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-small_cap-filter-toggle').click();
    await expect(terminal.page.getByTestId('scanner-small_cap-apply')).toBeDisabled();
  });

  test('filters come alive when IBKR connects mid-session', async ({ terminal, backend }) => {
    // Availability must track live status frames — a page that loaded during
    // a backend restart cached "unavailable" from REST and stayed locked.
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-small_cap-filter-toggle').click();
    await expect(terminal.page.getByTestId('scanner-small_cap-apply')).toBeDisabled();

    await backend.pushStatus({ source: 'ibkr' });
    await expect(terminal.page.getByTestId('scanner-small_cap-apply')).toBeEnabled();

    await backend.pushStatus({ source: 'alpaca' });
    await expect(terminal.page.getByTestId('scanner-small_cap-apply')).toBeDisabled();
  });
});

test.describe('scanner with IBKR', () => {
  test.use({ backendOptions: { scannerAvailable: true, source: 'ibkr' } });

  test('renders the rows it receives', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushScanner('small_cap', makeScannerRows(6));

    await expect.poll(async () => terminal.scannerRows().count()).toBe(6);
  });

  test('shows the momentum columns', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushScanner('small_cap', makeScannerRows(3));
    await expect.poll(async () => terminal.scannerRows().count()).toBe(3);

    const first = terminal.scannerRows().first();
    await expect(first).toContainText('SC01');
    // Price, change, volume, float, market cap, trades/min, dollars/min.
    // The symbol is a <th>, so it is not counted here.
    await expect(first.locator('td')).toHaveCount(7);
  });

  test('loads a symbol when a row is clicked', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushScanner('small_cap', makeScannerRows(4));
    await expect.poll(async () => terminal.scannerRows().count()).toBe(4);

    await terminal.scannerRows().first().click();

    const command = await backend.waitForCommand('subscribe');
    expect(command.symbol).toBe('SC01');
    await expect(terminal.symbolInput).toHaveValue('SC01');
  });

  test('keeps the current timeframe when loading from the scanner', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    await terminal.selectTimeframe('5m');
    await expect.poll(async () => (await terminal.state()).timeframe).toBe('5m');

    await backend.pushScanner('small_cap', makeScannerRows(2));
    await expect.poll(async () => terminal.scannerRows().count()).toBe(2);
    await terminal.scannerRows().first().click();

    const command = await backend.waitForCommand('subscribe');
    expect(command.timeframe).toBe('5m');
  });

  test('sends the filters when applied', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-small_cap-filter-toggle').click();

    // The draft hydrates from the pushed config exactly once, so a config
    // that lands *after* these fields are edited silently overwrites them.
    // Waiting for the seeded value proves hydration has already happened.
    await expect(terminal.page.getByTestId('scanner-small_cap-above_price')).toHaveValue('1');

    await terminal.page.getByTestId('scanner-small_cap-above_price').fill('2');
    await terminal.page.getByTestId('scanner-small_cap-below_price').fill('15');
    // Volume is entered in thousands.
    await terminal.page.getByTestId('scanner-small_cap-above_volume').fill('500');
    await terminal.page.getByTestId('scanner-small_cap-market_cap_below').fill('500');
    await terminal.page.getByTestId('scanner-small_cap-change_perc_above').fill('10');
    await terminal.page.getByTestId('scanner-small_cap-apply').click();

    const command = await backend.waitForCommand('scanner.configure');
    expect(command.scanner_id).toBe('small_cap');
    expect(command.above_price).toBe(2);
    expect(command.below_price).toBe(15);
    expect(command.above_volume).toBe(500000);
    expect(command.market_cap_below).toBe(500_000_000);
    expect(command.change_perc_above).toBe(10);
    // Untouched bounds are explicitly cleared, not silently kept.
    expect(command.market_cap_above).toBe('clear');
  });

  test('clears the price bounds when the fields are emptied', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-mid_cap-filter-toggle').click();

    // The mock's default config seeds above_price/below_price; emptying the
    // fields and applying must actually relax them, not silently keep them.
    // The draft hydrates from the pushed config exactly once, so a config
    // that lands *after* these fields are edited silently overwrites them.
    // Waiting for the seeded value proves hydration has already happened.
    await expect(terminal.page.getByTestId('scanner-mid_cap-above_price')).toHaveValue('1');

    await terminal.page.getByTestId('scanner-mid_cap-above_price').fill('');
    await terminal.page.getByTestId('scanner-mid_cap-below_price').fill('');
    await terminal.page.getByTestId('scanner-mid_cap-apply').click();

    const command = await backend.waitForCommand('scanner.configure');
    expect(command.scanner_id).toBe('mid_cap');
    expect(command.above_price).toBe('clear');
    expect(command.below_price).toBe('clear');
  });

  test('sends the chosen scan type', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-small_cap-filter-toggle').click();
    await terminal.scannerPanel('small_cap').getByLabel('Scan').selectOption('MOST_ACTIVE');
    await terminal.page.getByTestId('scanner-small_cap-apply').click();

    const command = await backend.waitForCommand('scanner.configure');
    expect(command.scan_code).toBe('MOST_ACTIVE');
  });

  test('does not overwrite filters being edited', async ({ terminal, backend }) => {
    // A periodic refresh arriving mid-edit must not wipe the field.
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-small_cap-filter-toggle').click();
    await terminal.page.getByTestId('scanner-small_cap-above_price').fill('7');

    await backend.pushScanner('small_cap', makeScannerRows(3));
    await expect.poll(async () => terminal.scannerRows().count()).toBe(3);

    await expect(terminal.page.getByTestId('scanner-small_cap-above_price')).toHaveValue('7');
  });

  test('highlights the symbol currently on the chart', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushScanner('small_cap', makeScannerRows(3));
    await expect.poll(async () => terminal.scannerRows().count()).toBe(3);

    await terminal.scannerRows().first().click();
    await expect(terminal.symbolInput).toHaveValue('SC01');
    await expect(terminal.page.getByTestId('scanner-small_cap-row-SC01')).toHaveClass(
      /bg-accent/,
    );
  });

  test('flashes green on a row printing over a thousand a minute', async ({
    terminal,
    backend,
  }) => {
    // The threshold is HOT_TRADE_RATE in ScannerPanel.tsx. Strictly over, so
    // a row sitting exactly on it stays quiet.
    const rows = makeScannerRows(3);
    rows[0].trades_1m = 1400;
    rows[1].trades_1m = 1000;

    await terminal.waitForChart();
    await backend.pushScanner('small_cap', rows);
    await expect.poll(async () => terminal.scannerRows().count()).toBe(3);

    const hot = terminal.page.getByTestId('scanner-small_cap-row-SC01');
    await expect(hot).toHaveAttribute('data-hot', 'true');
    // The tint is what carries the meaning, but the pulse is the ask.
    expect(await hot.evaluate((el) => getComputedStyle(el).animationName)).toBe('scanner-row-hot');

    for (const symbol of ['SC02', 'SC03']) {
      const quiet = terminal.page.getByTestId(`scanner-small_cap-row-${symbol}`);
      await expect(quiet).not.toHaveAttribute('data-hot', 'true');
      expect(await quiet.evaluate((el) => getComputedStyle(el).animationName)).toBe('none');
    }
  });

  test('a flashing row still shows which symbol is loaded', async ({ terminal, backend }) => {
    // Both at once is the common case — you chart the busiest name — and the
    // green owns the background, so the accent bar on the symbol cell is what
    // has to survive it.
    const rows = makeScannerRows(2);
    rows[0].trades_1m = 2000;

    await terminal.waitForChart();
    await backend.pushScanner('small_cap', rows);
    await expect.poll(async () => terminal.scannerRows().count()).toBe(2);

    await terminal.scannerRows().first().click();
    await expect(terminal.symbolInput).toHaveValue('SC01');

    const row = terminal.page.getByTestId('scanner-small_cap-row-SC01');
    await expect(row).toHaveAttribute('data-hot', 'true');
    await expect(row.locator('th')).toHaveClass(/border-l-accent/);
  });

  test('every tier flashes, not just small cap', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    for (const tier of SCANNER_TIERS) {
      const rows = makeScannerRows(1);
      rows[0].trades_1m = 3000;
      await backend.pushScanner(tier.id, rows);
      await expect(terminal.page.getByTestId(`scanner-${tier.id}-row-SC01`)).toHaveAttribute(
        'data-hot',
        'true',
      );
    }
  });

  test('shows a waiting message before any results', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.scannerPanel()).toContainText('Waiting for scanner results');
  });

  test('all four market-cap tiers are visible at once, not tabbed', async ({ terminal }) => {
    await terminal.waitForChart();
    for (const tier of SCANNER_TIERS) {
      await expect(terminal.scannerPanel(tier.id)).toBeVisible();
    }
  });

  test('filters on one tier do not disturb another', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushScanner('small_cap', makeScannerRows(2));
    await backend.pushScanner('mid_cap', makeScannerRows(3));
    await expect.poll(async () => terminal.scannerRows('small_cap').count()).toBe(2);
    await expect.poll(async () => terminal.scannerRows('mid_cap').count()).toBe(3);

    await terminal.page.getByTestId('scanner-mid_cap-filter-toggle').click();
    await terminal.page.getByTestId('scanner-mid_cap-above_price').fill('9');
    await terminal.page.getByTestId('scanner-mid_cap-apply').click();
    await backend.waitForCommand('scanner.configure');

    // small_cap's rows and filter state are untouched by mid_cap's change —
    // still its own initial config (above_price: 1 from the mock's default),
    // not mid_cap's 9.
    await expect.poll(async () => terminal.scannerRows('small_cap').count()).toBe(2);
    await terminal.page.getByTestId('scanner-small_cap-filter-toggle').click();
    await expect(terminal.page.getByTestId('scanner-small_cap-above_price')).toHaveValue('1');
  });
});
