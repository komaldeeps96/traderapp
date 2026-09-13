import { makeNextBar } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/**
 * Where a server error lands. Only a failed chart load belongs to the chart:
 * its error state drops live bars until the next snapshot, so anything else
 * raised there froze the chart.
 */

test.describe('an error that is not about the chart', () => {
  test('a refused order leaves the chart live', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const before = (await terminal.chartState()).barCount;

    await backend.pushError('trade', 'Trading is disabled.');
    await backend.send(makeNextBar(backend.lastSnapshot()!));

    await expect.poll(async () => (await terminal.chartState()).barCount).toBe(before + 1);
    await expect(terminal.errorBanner).toBeHidden();
  });

  test('a scanner rejection is a dismissible notice, and the chart stays live', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    const before = (await terminal.chartState()).barCount;

    await backend.pushError('scanner', 'The market scanner needs a running IBKR TWS.');
    const notice = terminal.page.getByTestId('notice-banner');
    await expect(notice).toContainText('needs a running IBKR TWS');

    await backend.send(makeNextBar(backend.lastSnapshot()!));
    await expect.poll(async () => (await terminal.chartState()).barCount).toBe(before + 1);

    await notice.getByRole('button', { name: 'Dismiss notice' }).click();
    await expect(notice).toBeHidden();
  });
});

test.describe('an error that is about the chart', () => {
  test('a failed load shows on the chart even when the server itself failed', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    await backend.send({
      type: 'error',
      code: 'server',
      message: 'The server failed on subscribe.',
      action: 'subscribe',
    });
    await expect(terminal.errorBanner).toContainText('failed on subscribe');
  });
});
