import { expect, test } from '../../fixtures/test';

test.describe('theme', () => {
  test('starts dark — this is a terminal', async ({ terminal }) => {
    await terminal.waitForChart();
    expect(await terminal.theme()).toBe('dark');
  });

  test('switches to light', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.themeToggle.click();
    await expect.poll(() => terminal.theme()).toBe('light');
  });

  test('restyles the chart, not just the page', async ({ terminal }) => {
    await terminal.waitForChart();
    expect((await terminal.chartState()).theme).toBe('dark');

    await terminal.themeToggle.click();
    await expect.poll(async () => (await terminal.chartState()).theme).toBe('light');
  });

  test('keeps the data through the switch', async ({ terminal }) => {
    await terminal.waitForChart();
    const before = (await terminal.chartState()).barCount;

    await terminal.themeToggle.click();
    await expect.poll(async () => (await terminal.chartState()).theme).toBe('light');

    expect((await terminal.chartState()).barCount).toBe(before);
    expect((await terminal.chartState()).pointCounts.ema9).toBeGreaterThan(0);
  });

  test('remembers the choice across a reload', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.themeToggle.click();
    await expect.poll(() => terminal.theme()).toBe('light');

    await terminal.page.reload();
    await terminal.waitForChart();
    expect(await terminal.theme()).toBe('light');
  });

  test('applies the saved theme before the first paint', async ({ terminal }) => {
    // The inline script in index.html stamps the attribute before React runs,
    // so a reload never flashes the wrong background.
    await terminal.waitForChart();
    await terminal.themeToggle.click();
    await expect.poll(() => terminal.theme()).toBe('light');

    await terminal.page.goto('/');
    expect(await terminal.theme()).toBe('light');
  });

  test('switches back to dark', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.themeToggle.click();
    await expect.poll(() => terminal.theme()).toBe('light');
    await terminal.themeToggle.click();
    await expect.poll(() => terminal.theme()).toBe('dark');
  });
});
