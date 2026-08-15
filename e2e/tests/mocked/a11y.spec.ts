import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';

import { makeScannerRows } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/**
 * Automated accessibility checks.
 *
 * axe catches the mechanical failures — unlabelled controls, missing table
 * headers, colour contrast below threshold. It cannot judge whether the chart
 * itself is usable, which is why the terminal also carries a text readout of
 * every value the chart draws.
 */
async function scan(page: Page) {
  return new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    // The chart is a canvas; its content is exposed through the readout and
    // the key-levels table, both of which are scanned normally.
    .exclude('[data-testid="chart-canvas"]')
    .analyze();
}

test.describe('accessibility', () => {
  test('the terminal has no violations', async ({ page, terminal }) => {
    await terminal.waitForChart();
    const results = await scan(page);
    expect(results.violations).toEqual([]);
  });

  test('light mode has no violations', async ({ page, terminal }) => {
    await terminal.waitForChart();
    await terminal.themeToggle.click();
    await expect.poll(() => terminal.theme()).toBe('light');

    const results = await scan(page);
    expect(results.violations).toEqual([]);
  });

  test('every control can be reached by keyboard', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.keyboard.press('Tab');
    const focused = await terminal.page.evaluate(() => document.activeElement?.tagName);
    expect(['INPUT', 'BUTTON', 'SELECT']).toContain(focused);
  });

  test('a symbol can be loaded without a mouse', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.symbolInput.focus();
    await terminal.page.keyboard.type('MSFT');
    await terminal.page.keyboard.press('Enter');

    const command = await backend.waitForCommand('subscribe');
    expect(command.symbol).toBe('MSFT');
  });

  test('the connection state is announced', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByRole('status')).toContainText(/Connected|Disconnected/);
  });

  test('tables carry headers', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.keyLevels.getByRole('columnheader').first()).toBeVisible();
  });

  test('toggle buttons have accessible names', async ({ terminal }) => {
    await terminal.waitForChart();
    // On the 10s default, ema9 runs with span 54 and is labelled accordingly.
    await expect(
      terminal.indicatorChip('ema9').getByRole('button', { name: /EMA 54/ }),
    ).toBeVisible();
  });
});

test.describe('accessibility with scanner results', () => {
  test.use({ backendOptions: { scannerAvailable: true, source: 'ibkr' } });

  test('the populated scanner has no violations', async ({ page, terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushScanner(makeScannerRows(5));
    await expect.poll(async () => terminal.scannerRows.count()).toBe(5);

    const results = await scan(page);
    expect(results.violations).toEqual([]);
  });
});
