import { makePosition } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/**
 * The order-entry strip.
 *
 * The quote every spec here runs against is bid 10.02 / ask 10.06, which makes
 * the arithmetic legible: at 5c/15bps the buy limit is 10.11 and the sell
 * limit 9.97, and the $10 button buys **nothing** — a dead button is an
 * ordinary state on a $10 stock, not an edge case, so it is asserted first.
 *
 * Nothing here can place an order: the mock backend records commands and
 * replies, and the real one refuses everything with `trading.enabled` false.
 * What is being tested is that the strip cannot *mislead* — that a button
 * showing a share count sends the amount that produced it, that a dead button
 * cannot be clicked, and that the panel never appears at all unless the
 * server says trading is armed.
 */

const ARMED = { enabled: true, connected: true, account: 'DU1234', paper: true };

test.describe('with trading off', () => {
  test('the strip is not rendered at all', async ({ terminal }) => {
    // An inert row of buy buttons is worse than no row: it looks like it
    // would work. The default server state is off, so this is the default
    // appearance of the terminal and of every visual baseline.
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('order-panel')).toHaveCount(0);
  });
});

test.describe('armed', () => {
  test.use({ backendOptions: { trading: ARMED } });

  test.beforeEach(async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('order-panel')).toBeVisible();
  });

  test('names the symbol it will trade, where the click starts', async ({ terminal }) => {
    // Buying the name you were looking at a moment ago is the worst failure
    // mode this panel has, so the ticker is the leftmost thing on the strip.
    await expect(terminal.page.getByTestId('order-symbol')).toHaveText('AAPL');
  });

  test('sizes each buy button from the ask', async ({ terminal }) => {
    // 25 / 10.06 = 2.48 -> 2 shares. 50 / 10.06 = 4.97 -> 4. Floored, never
    // rounded: rounding up would overspend the button.
    await expect(terminal.page.getByTestId('order-buy-25')).toContainText('2 sh');
    await expect(terminal.page.getByTestId('order-buy-50')).toContainText('4 sh');
  });

  test('a button too small for one whole share is dead and says so', async ({ terminal }) => {
    const tenner = terminal.page.getByTestId('order-buy-10');
    await expect(tenner).toContainText('0 sh');
    await expect(tenner).toBeDisabled();
  });

  test('the share counts follow the spread', async ({ terminal, backend }) => {
    // The preview is computed on the client off the quote it already holds,
    // so this moves with no round trip. The number it shows is the number the
    // server will independently arrive at.
    await backend.pushQuote({ bid: 2.0, ask: 2.05 });
    await expect(terminal.page.getByTestId('order-buy-10')).toContainText('4 sh');
    await expect(terminal.page.getByTestId('order-buy-25')).toContainText('12 sh');
  });

  test('sends the dollar amount and never a share count', async ({ terminal, backend }) => {
    // The whole architecture in one assertion: a tab that has been asleep
    // cannot put a stale size on the wire, because it never sends a size.
    await terminal.page.getByTestId('order-buy-25').click();
    const command = await backend.waitForCommand('trade.buy');
    expect(command).toEqual({ action: 'trade.buy', symbol: 'AAPL', dollars: 25 });
    expect(command).not.toHaveProperty('shares');
  });

  test('sends the fraction and never a share count', async ({ terminal, backend }) => {
    await backend.pushTrading({ ...ARMED, positions: [makePosition('AAPL', 14)] });
    await terminal.page.getByTestId('order-sell-0.5').click();
    const command = await backend.waitForCommand('trade.sell');
    expect(command).toEqual({ action: 'trade.sell', symbol: 'AAPL', fraction: 0.5 });
  });

  test('every sell button is dead while flat', async ({ terminal }) => {
    for (const id of ['order-sell-0.25', 'order-sell-0.5', 'order-sell-1']) {
      await expect(terminal.page.getByTestId(id)).toBeDisabled();
    }
    await expect(terminal.page.getByTestId('order-sell-1')).toContainText('flat');
  });

  test('sizes each sell button off the position', async ({ terminal, backend }) => {
    await backend.pushTrading({ ...ARMED, positions: [makePosition('AAPL', 14)] });
    // 25% of 14 floors to 3, not 3.5. ALL is the position exactly.
    await expect(terminal.page.getByTestId('order-sell-0.25')).toContainText('3 sh');
    await expect(terminal.page.getByTestId('order-sell-0.5')).toContainText('7 sh');
    await expect(terminal.page.getByTestId('order-sell-1')).toContainText('14 sh');
    await expect(terminal.page.getByTestId('order-sell-1')).toContainText('ALL');
  });

  test('a fraction that floors to nothing is dead', async ({ terminal, backend }) => {
    // 25% of three shares is nothing. The button must not send an empty order.
    await backend.pushTrading({ ...ARMED, positions: [makePosition('AAPL', 3)] });
    await expect(terminal.page.getByTestId('order-sell-0.25')).toBeDisabled();
    await expect(terminal.page.getByTestId('order-sell-0.5')).toBeEnabled();
  });

  test('shows the position and its unrealised P&L', async ({ terminal, backend }) => {
    await backend.pushTrading({ ...ARMED, positions: [makePosition('AAPL', 14)] });
    const readout = terminal.page.getByTestId('order-position');
    await expect(readout).toContainText('14');
    await expect(readout).toContainText('9.87');
    await expect(readout).toContainText('1.84');
  });

  test('sells only the focused symbol, not another name that is held', async ({
    terminal,
    backend,
  }) => {
    await backend.pushTrading({ ...ARMED, positions: [makePosition('TSLA', 40)] });
    await expect(terminal.page.getByTestId('order-sell-1')).toBeDisabled();
    await expect(terminal.page.getByTestId('order-position')).toContainText('FLAT');
  });

  test('the rail lists every open position and loads one on click', async ({
    terminal,
    backend,
  }) => {
    // A six-button entry UI showing only the focused name is a way to end a
    // day long something you forgot about.
    await backend.pushTrading({
      ...ARMED,
      positions: [makePosition('AAPL', 14), makePosition('TSLA', 40)],
    });
    await expect(terminal.page.getByTestId('position-TSLA')).toBeVisible();
    await terminal.page.getByTestId('position-TSLA').click();
    const command = await backend.waitForCommand('subscribe');
    expect(command.symbol).toBe('TSLA');
  });
});

test.describe('when it must not be used', () => {
  test.use({ backendOptions: { trading: ARMED } });

  test('every button is dead while TWS is down', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushTrading({ ...ARMED, connected: false });
    await expect(terminal.page.getByTestId('order-disconnected')).toBeVisible();
    await expect(terminal.page.getByTestId('order-buy-25')).toBeDisabled();
  });

  test('every button is dead while the stock is halted', async ({ terminal, backend }) => {
    // A halted tape prints no fills; a live-looking buy button on one is a
    // click that goes nowhere and is noticed late.
    await terminal.waitForChart();
    await backend.pushInfo({ halted: true });
    await expect(terminal.page.getByTestId('order-buy-25')).toBeDisabled();
    await expect(terminal.page.getByTestId('order-note')).toContainText('Halted');
  });

  test('a read-only TWS is called out rather than silently failing', async ({
    terminal,
    backend,
  }) => {
    // The single most likely setup mistake, and it is invisible from the
    // code side: TWS accepts the connection either way and only objects when
    // an order arrives.
    await terminal.waitForChart();
    await backend.pushTrading({
      ...ARMED,
      read_only: true,
      note: 'TWS is in read-only mode. Untick Global Configuration → API → Settings → Read-Only API.',
    });
    await expect(terminal.page.getByTestId('order-note')).toContainText('read-only');
    await expect(terminal.page.getByTestId('order-buy-25')).toBeDisabled();
  });
});

test.describe('live and paper are told apart', () => {
  test.use({ backendOptions: { trading: ARMED } });

  test('a paper account is labelled quietly', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('order-account')).toHaveText('PAPER DU1234');
  });
});

test.describe('a live account announces itself', () => {
  test.use({ backendOptions: { trading: { ...ARMED, paper: false, account: 'U7654321' } } });

  test('is marked LIVE, in the colour the rest of the terminal uses for danger', async ({
    terminal,
  }) => {
    await terminal.waitForChart();
    const badge = terminal.page.getByTestId('order-account');
    await expect(badge).toHaveText('LIVE U7654321');
    await expect(badge).toHaveClass(/text-down/);
  });
});

test.describe('what came back', () => {
  test.use({ backendOptions: { trading: ARMED } });

  test('acknowledges a fill on the strip', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushOrder({ side: 'BUY', shares: 2, limit: 10.11, filled: 2, avg_fill: 10.06 });
    await expect(terminal.page.getByTestId('order-ack')).toContainText('BUY 2 AAPL');
    await expect(terminal.page.getByTestId('order-ack')).toContainText('10.06');
  });

  test('shows a refusal where it will be seen, not in a log', async ({ terminal, backend }) => {
    // During a move nobody is reading a log, and an order that silently did
    // not go is the failure this whole panel exists to remove.
    await backend.pushTrading({ ...ARMED, note: 'Over the per-order cap.' });
    await expect(terminal.page.getByTestId('order-note')).toContainText('cap');
  });

  test('offers a cancel while an order is working', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await backend.pushTrading({
      ...ARMED,
      orders: [
        {
          order_id: 7,
          symbol: 'AAPL',
          side: 'BUY',
          shares: 2,
          limit: 10.11,
          status: 'Submitted',
          filled: 0,
          avg_fill: 0,
          message: null,
          at: 0,
        },
      ],
    });
    await terminal.page.getByTestId('cancel-all').click();
    await backend.waitForCommand('trade.cancel_all');
  });
});
