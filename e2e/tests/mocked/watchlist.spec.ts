import { expect, test } from '../../fixtures/test';

/**
 * The list of names this desk is working.
 *
 * The point of the whole feature is that the list survives — a reload, a
 * second window, the socket dropping — so most of what is worth testing here
 * is about where the list lives rather than how it looks. It lives on the
 * server: the client sends an edit and renders what comes back, which is why
 * a name added in one window turns up in the other.
 */
test.describe('watchlist', () => {
  test.beforeEach(async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-tab-watch').click();
    await expect(terminal.page.getByTestId('watchlist-panel')).toBeVisible();
  });

  test('opens on the day scanners, not this', async ({ terminal }) => {
    await terminal.page.getByTestId('scanner-tab-day').click();
    await expect(terminal.page.getByTestId('watchlist-panel')).toBeHidden();
  });

  test('says how to fill an empty list', async ({ terminal }) => {
    // An empty table with no explanation reads as a broken panel.
    await expect(terminal.page.getByTestId('watchlist-empty')).toBeVisible();
  });

  test('adds a symbol from the input', async ({ terminal }) => {
    await terminal.page.getByTestId('watchlist-input').fill('AAPL');
    await terminal.page.getByTestId('watchlist-add').click();
    await expect(terminal.page.getByTestId('watchlist-row-AAPL')).toBeVisible();
    await expect(terminal.page.getByTestId('watchlist-row-AAPL')).toContainText('231.40');
  });

  test('enter adds it too', async ({ terminal }) => {
    // The keyboard is how this is actually used: a name is typed and the hand
    // does not leave it to find a button.
    await terminal.page.getByTestId('watchlist-input').fill('TSLA');
    await terminal.page.getByTestId('watchlist-input').press('Enter');
    await expect(terminal.page.getByTestId('watchlist-row-TSLA')).toBeVisible();
  });

  test('clears the box after adding, ready for the next one', async ({ terminal }) => {
    await terminal.page.getByTestId('watchlist-input').fill('AAPL');
    await terminal.page.getByTestId('watchlist-input').press('Enter');
    await expect(terminal.page.getByTestId('watchlist-input')).toHaveValue('');
  });

  test('lower case is accepted', async ({ terminal, backend }) => {
    await terminal.page.getByTestId('watchlist-input').fill('nvda');
    await terminal.page.getByTestId('watchlist-input').press('Enter');
    const command = await backend.waitForCommand('watchlist.add');
    expect(command.symbol).toBe('NVDA');
    await expect(terminal.page.getByTestId('watchlist-row-NVDA')).toBeVisible();
  });

  test('a blank entry sends nothing', async ({ terminal, backend }) => {
    await terminal.page.getByTestId('watchlist-input').fill('   ');
    await terminal.page.getByTestId('watchlist-input').press('Enter');
    await terminal.page.waitForTimeout(150);
    expect(backend.commands().some((entry) => entry.action === 'watchlist.add')).toBe(false);
  });

  test('the same name twice does not appear twice', async ({ terminal }) => {
    for (const _ of [0, 1]) {
      await terminal.page.getByTestId('watchlist-input').fill('AAPL');
      await terminal.page.getByTestId('watchlist-input').press('Enter');
    }
    await expect(terminal.page.getByTestId('watchlist-row-AAPL')).toHaveCount(1);
  });

  test('removes a symbol', async ({ terminal }) => {
    await terminal.page.getByTestId('watchlist-input').fill('AAPL');
    await terminal.page.getByTestId('watchlist-input').press('Enter');
    await expect(terminal.page.getByTestId('watchlist-row-AAPL')).toBeVisible();

    await terminal.page.getByTestId('watchlist-remove-AAPL').click();
    await expect(terminal.page.getByTestId('watchlist-row-AAPL')).toBeHidden();
  });
});

test.describe('a watchlist that is already there', () => {
  test.use({ backendOptions: { watchlist: ['TSLA', 'AAPL', 'NVDA'] } });

  test('arrives with the connection', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-tab-watch').click();
    await expect(terminal.page.getByTestId('watchlist-row-TSLA')).toBeVisible();
  });

  test('keeps the order names were added in', async ({ terminal }) => {
    // Not alphabetical and not sorted by change: the order is information,
    // and a list that re-sorts itself under the cursor loses it.
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-tab-watch').click();
    const rows = terminal.page.locator('[data-testid^="watchlist-row-"]');
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText('TSLA');
    await expect(rows.nth(1)).toContainText('AAPL');
    await expect(rows.nth(2)).toContainText('NVDA');
  });

  test('removing one leaves the rest in order', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-tab-watch').click();
    await terminal.page.getByTestId('watchlist-remove-AAPL').click();

    const rows = terminal.page.locator('[data-testid^="watchlist-row-"]');
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText('TSLA');
    await expect(rows.nth(1)).toContainText('NVDA');
  });

  test('loads the chart when a row is clicked', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-tab-watch').click();
    await terminal.page.getByTestId('watchlist-row-NVDA').click();

    await expect.poll(async () => terminal.symbolInput.inputValue()).toBe('NVDA');
    const command = await backend.waitForCommand('subscribe');
    expect(command.symbol).toBe('NVDA');
  });

  test('removing a row does not also load its chart', async ({ terminal, backend }) => {
    // The × sits inside a row that is itself a click target; without stopping
    // the event, taking a name off the list also opens it.
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-tab-watch').click();
    const before = terminal.page.getByTestId('watchlist-row-TSLA');
    await expect(before).toBeVisible();

    await terminal.page.getByTestId('watchlist-remove-TSLA').click();
    await expect(before).toBeHidden();
    expect(
      backend.commands().filter((entry) => entry.action === 'subscribe' && entry.symbol === 'TSLA'),
    ).toHaveLength(0);
  });

  test('a symbol the screener does not know keeps its row', async ({ terminal, backend }) => {
    // A delisted or mistyped ticker has to stay visible: it is still on the
    // list, and this panel is the only place it can be taken off.
    await terminal.waitForChart();
    await terminal.page.getByTestId('scanner-tab-watch').click();
    await terminal.page.getByTestId('watchlist-input').fill('ZZZZ');
    await terminal.page.getByTestId('watchlist-input').press('Enter');
    await backend.waitForCommand('watchlist.add');

    const row = terminal.page.getByTestId('watchlist-row-ZZZZ');
    await expect(row).toBeVisible();
    await expect(row).toContainText('—');
    await expect(terminal.page.getByTestId('watchlist-remove-ZZZZ')).toBeAttached();
  });
});

test.describe('the star beside the symbol', () => {
  test('adds the chart’s symbol without retyping it', async ({ terminal }) => {
    // The far more common case: the name is already on screen because
    // something about it was interesting.
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('watch-star')).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    await terminal.page.getByTestId('watch-star').click();
    await expect(terminal.page.getByTestId('watch-star')).toHaveAttribute('aria-pressed', 'true');

    await terminal.page.getByTestId('scanner-tab-watch').click();
    await expect(terminal.page.getByTestId('watchlist-row-AAPL')).toBeVisible();
  });

  test('takes it off again', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('watch-star').click();
    await expect(terminal.page.getByTestId('watch-star')).toHaveAttribute('aria-pressed', 'true');
    await terminal.page.getByTestId('watch-star').click();
    await expect(terminal.page.getByTestId('watch-star')).toHaveAttribute('aria-pressed', 'false');
  });

  test('tracks the chart, not the last thing starred', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.page.getByTestId('watch-star').click();
    await expect(terminal.page.getByTestId('watch-star')).toHaveAttribute('aria-pressed', 'true');

    await terminal.setSymbol('TSLA');
    await expect(terminal.page.getByTestId('watch-star')).toHaveAttribute('aria-pressed', 'false');
  });
});
