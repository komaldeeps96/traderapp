import { makeScannerRows } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

test.describe('scanner without IBKR', () => {
  test('says why it is empty', async ({ terminal }) => {
    // Scanning is IBKR-only with no Alpaca equivalent, so an empty table with
    // no explanation would just read as a bug.
    await terminal.waitForChart();
    await expect(terminal.scannerNote).toBeVisible();
    await expect(terminal.scannerNote).toContainText('IBKR');
  });

  test('disables the filters', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-filter-toggle').click();
    await expect(terminal.page.getByTestId('scanner-apply')).toBeDisabled();
  });

  test('filters come alive when IBKR connects mid-session', async ({ terminal, backend }) => {
    // Availability must track live status frames — a page that loaded during
    // a backend restart cached "unavailable" from REST and stayed locked.
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-filter-toggle').click();
    await expect(terminal.page.getByTestId('scanner-apply')).toBeDisabled();

    await backend.pushStatus({ source: 'ibkr' });
    await expect(terminal.page.getByTestId('scanner-apply')).toBeEnabled();

    await backend.pushStatus({ source: 'alpaca' });
    await expect(terminal.page.getByTestId('scanner-apply')).toBeDisabled();
  });
});

test.describe('scanner with IBKR', () => {
  test.use({ backendOptions: { scannerAvailable: true, source: 'ibkr' } });

  test('renders the rows it receives', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushScanner(makeScannerRows(6));

    await expect.poll(async () => terminal.scannerRows.count()).toBe(6);
  });

  test('shows the momentum columns', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushScanner(makeScannerRows(3));
    await expect.poll(async () => terminal.scannerRows.count()).toBe(3);

    const first = terminal.scannerRows.first();
    await expect(first).toContainText('SC01');
    // Price, change, volume, float, market cap, trades/min, dollars/min.
    // The symbol is a <th>, so it is not counted here.
    await expect(first.locator('td')).toHaveCount(7);
  });

  test('loads a symbol when a row is clicked', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushScanner(makeScannerRows(4));
    await expect.poll(async () => terminal.scannerRows.count()).toBe(4);

    await terminal.scannerRows.first().click();

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

    await backend.pushScanner(makeScannerRows(2));
    await expect.poll(async () => terminal.scannerRows.count()).toBe(2);
    await terminal.scannerRows.first().click();

    const command = await backend.waitForCommand('subscribe');
    expect(command.timeframe).toBe('5m');
  });

  test('sends the filters when applied', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-filter-toggle').click();

    await terminal.page.getByTestId('scanner-above_price').fill('2');
    await terminal.page.getByTestId('scanner-below_price').fill('15');
    // Volume is entered in thousands.
    await terminal.page.getByTestId('scanner-above_volume').fill('500');
    await terminal.page.getByTestId('scanner-market_cap_below').fill('500');
    await terminal.page.getByTestId('scanner-change_perc_above').fill('10');
    await terminal.page.getByTestId('scanner-apply').click();

    const command = await backend.waitForCommand('scanner.configure');
    expect(command.above_price).toBe(2);
    expect(command.below_price).toBe(15);
    expect(command.above_volume).toBe(500000);
    expect(command.market_cap_below).toBe(500_000_000);
    expect(command.change_perc_above).toBe(10);
    // Untouched bounds are explicitly cleared, not silently kept.
    expect(command.market_cap_above).toBe('clear');
  });

  test('sends the chosen scan type', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-filter-toggle').click();
    await terminal.page.getByLabel('Scan').selectOption('MOST_ACTIVE');
    await terminal.page.getByTestId('scanner-apply').click();

    const command = await backend.waitForCommand('scanner.configure');
    expect(command.scan_code).toBe('MOST_ACTIVE');
  });

  test('does not overwrite filters being edited', async ({ terminal, backend }) => {
    // A periodic refresh arriving mid-edit must not wipe the field.
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-filter-toggle').click();
    await terminal.page.getByTestId('scanner-above_price').fill('7');

    await backend.pushScanner(makeScannerRows(3));
    await expect.poll(async () => terminal.scannerRows.count()).toBe(3);

    await expect(terminal.page.getByTestId('scanner-above_price')).toHaveValue('7');
  });

  test('highlights the symbol currently on the chart', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushScanner(makeScannerRows(3));
    await expect.poll(async () => terminal.scannerRows.count()).toBe(3);

    await terminal.scannerRows.first().click();
    await expect(terminal.symbolInput).toHaveValue('SC01');
    await expect(terminal.page.getByTestId('scanner-row-SC01')).toHaveClass(/bg-accent/);
  });

  test('shows a waiting message before any results', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.scanner).toContainText('Waiting for scanner results');
  });
});
