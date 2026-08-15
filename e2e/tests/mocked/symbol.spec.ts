import { expect, test } from '../../fixtures/test';

test.describe('changing symbol', () => {
  test('loads a new symbol', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.setSymbol('TSLA');

    const command = await backend.waitForCommand('subscribe');
    expect(command.symbol).toBe('TSLA');
    await expect.poll(async () => (await terminal.state()).symbol).toBe('TSLA');
  });

  test('uppercases what was typed', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.setSymbol('tsla');
    const command = await backend.waitForCommand('subscribe');
    expect(command.symbol).toBe('TSLA');
  });

  test('redraws with the new symbol’s data', async ({ terminal }) => {
    await terminal.waitForChart();
    const before = (await terminal.chartState()).lastBar!.c;

    await terminal.setSymbol('TSLA');
    await expect.poll(async () => (await terminal.state()).status).toBe('ready');

    // Bars are seeded from the symbol, so a different symbol must not leave
    // the previous one's prices on screen.
    await expect.poll(async () => (await terminal.chartState()).lastBar!.c).not.toBe(before);
  });

  test('keeps the timeframe when the symbol changes', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.selectTimeframe('15m');
    await expect.poll(async () => (await terminal.state()).timeframe).toBe('15m');

    await terminal.setSymbol('TSLA');
    await expect.poll(async () => (await terminal.state()).symbol).toBe('TSLA');
    expect((await terminal.state()).timeframe).toBe('15m');
  });

  test('ignores an empty submission', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const before = backend.commands().filter((entry) => entry.action === 'subscribe').length;

    await terminal.symbolInput.fill('   ');
    await terminal.symbolInput.press('Enter');
    await terminal.page.waitForTimeout(250);

    const after = backend.commands().filter((entry) => entry.action === 'subscribe').length;
    expect(after).toBe(before);
  });

  test('selects the field on focus so a new symbol replaces the old', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.symbolInput.click();
    await terminal.page.keyboard.type('MSFT');
    await expect(terminal.symbolInput).toHaveValue('MSFT');
  });
});

test.describe('a symbol with no data', () => {
  test.use({ backendOptions: { emptySymbols: ['NODATA'] } });

  test('explains the problem', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.setSymbol('NODATA');

    await expect(terminal.errorBanner).toBeVisible();
    await expect(terminal.errorBanner).toContainText('No market data available for NODATA');
  });

  test('recovers when a good symbol is entered next', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.setSymbol('NODATA');
    await expect(terminal.errorBanner).toBeVisible();

    await terminal.setSymbol('AAPL');
    await expect.poll(async () => (await terminal.state()).status).toBe('ready');
    await expect(terminal.errorBanner).toBeHidden();
  });
});
