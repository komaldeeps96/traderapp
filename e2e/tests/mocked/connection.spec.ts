import { expect, test } from '../../fixtures/test';

test.describe('data source badge', () => {
  test('names the active source', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.sourceBadge).toHaveAttribute('data-source', 'alpaca');
    await expect(terminal.sourceBadge).toContainText('ALPACA');
  });

  test('shows the connection as live', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.sourceBadge).toHaveAttribute('data-connected', 'true');
  });

  test('does not claim a delay when there is none', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.delayedBadge).toBeHidden();
  });
});

test.describe('a delayed feed', () => {
  test.use({ backendOptions: { delayed: true } });

  test('says so plainly', async ({ terminal }) => {
    // Whether a price is live or fifteen minutes old changes what a trader
    // does with it, so it must never be ambiguous.
    await terminal.waitForChart();
    await expect(terminal.delayedBadge).toBeVisible();
    await expect(terminal.delayedBadge).toContainText('15-min delayed');
  });

  test('marks it on the badge', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.sourceBadge).toHaveAttribute('data-delayed', 'true');
  });
});

test.describe('running on IBKR', () => {
  test.use({ backendOptions: { source: 'ibkr' } });

  test('names IBKR as the source', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.sourceBadge).toContainText('IBKR');
  });
});

test.describe('failover while running', () => {
  test.use({ backendOptions: { source: 'ibkr' } });

  test('follows the source when it changes', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await expect(terminal.sourceBadge).toContainText('IBKR');

    // TWS goes away mid-session; the backend moves to Alpaca and says so.
    await backend.pushStatus({
      source: 'alpaca',
      delayed: true,
      ibkr_connected: false,
      message: 'IBKR unavailable — using Alpaca (15-minute delayed).',
    });

    await expect(terminal.sourceBadge).toContainText('ALPACA');
    await expect(terminal.delayedBadge).toBeVisible();
  });
});

test.describe('losing the connection', () => {
  test('reports the drop', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.dropConnection();
    await expect(terminal.sourceBadge).toHaveAttribute('data-connected', 'false');
  });

  test('reconnects on its own', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.dropConnection();
    await expect(terminal.sourceBadge).toHaveAttribute('data-connected', 'false');

    // Backoff starts at 500ms with jitter.
    await expect(terminal.sourceBadge).toHaveAttribute('data-connected', 'true', {
      timeout: 15_000,
    });
  });

  test('restores the chart after reconnecting', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.setSymbol('TSLA');
    await expect.poll(async () => (await terminal.state()).symbol).toBe('TSLA');

    await backend.dropConnection();
    await expect(terminal.sourceBadge).toHaveAttribute('data-connected', 'true', {
      timeout: 15_000,
    });

    // The client replays its subscription, so the chart comes back by itself.
    const resubscribed = await backend.waitForCommand('subscribe', 10_000);
    expect(resubscribed.symbol).toBe('TSLA');
    await expect.poll(async () => (await terminal.chartState()).barCount).toBeGreaterThan(0);
  });
});

test.describe('a backend that is not running', () => {
  test('explains what is wrong instead of hanging', async ({ page }) => {
    await page.route('**/api/**', (route) => route.abort('connectionrefused'));
    await page.goto('/');
    await expect(page.getByTestId('error-banner')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('error-banner')).toContainText('backend');
  });
});
