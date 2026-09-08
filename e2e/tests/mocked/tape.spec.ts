import { expect, test } from '../../fixtures/test';
import { makeTapePrints } from '../../fixtures/data';

/**
 * Time and sales — the window that took the second context chart's place.
 *
 * The rules are unit-tested in `frontend/src/lib/tape.test.ts`. What only a
 * browser can show is that they reach the screen: that each verdict draws its
 * own tint, that the controls are wired to the filters, and that a symbol
 * switch does not leave the last company's prints sitting under a new ticker.
 */
test.describe('time and sales', () => {
  test('opens with the prints the server already had', async ({ terminal }) => {
    await terminal.waitForChart();

    await expect(terminal.tape).toBeVisible();
    await expect(terminal.tapeRows()).toHaveCount(6);
    // Newest first, as every tape is read.
    await expect(terminal.tapeRows().first()).toHaveAttribute('data-testid', 'tape-row-6');
  });

  test('tints each side the way a direct-access tape does', async ({ terminal }) => {
    await terminal.waitForChart();

    // Two greens and two reds; a print that took neither side stays plain.
    await expect(terminal.tapeRow(1)).toHaveClass(/tape-ask/);
    await expect(terminal.tapeRow(2)).toHaveClass(/tape-above/);
    await expect(terminal.tapeRow(3)).not.toHaveClass(/tape-/);
    await expect(terminal.tapeRow(4)).toHaveClass(/tape-bid/);
    await expect(terminal.tapeRow(5)).toHaveClass(/tape-below/);
  });

  test('the two greens are genuinely different, and so are the reds', async ({ terminal }) => {
    // The whole point of the second shade is that it reads as more, so this
    // asserts on the painted colour rather than on the class name.
    await terminal.waitForChart();
    const paint = (seq: number) =>
      terminal
        .tapeRow(seq)
        .evaluate((node) => getComputedStyle(node).backgroundColor);

    expect(await paint(2)).not.toBe(await paint(1));
    expect(await paint(5)).not.toBe(await paint(4));
  });

  test('marks a block print', async ({ terminal }) => {
    await terminal.waitForChart();

    // 2,500 and 5,000 are over the default 1,000 threshold; 100 is not.
    await expect(terminal.tapeRow(2)).toHaveAttribute('data-block', 'true');
    await expect(terminal.tapeRow(5)).toHaveAttribute('data-block', 'true');
    await expect(terminal.tapeRow(1)).not.toHaveAttribute('data-block', 'true');
  });

  test('shows price, size and venue', async ({ terminal }) => {
    await terminal.waitForChart();

    const row = terminal.tapeRow(2);
    await expect(row).toContainText('10.08');
    await expect(row).toContainText('2,500');
    await expect(row).toContainText('K');
  });

  test('a size floor hides the small prints', async ({ terminal }) => {
    await terminal.waitForChart();

    await terminal.page.getByTestId('tape-min-size').selectOption('1000');

    await expect(terminal.tapeRows()).toHaveCount(2);
    await expect(terminal.tapeRow(2)).toBeVisible();
    await expect(terminal.tapeRow(5)).toBeVisible();
  });

  test('the irregular print is shown by default and can be dropped', async ({ terminal }) => {
    await terminal.waitForChart();

    // A late report is real volume, so it is on the tape — marked, not hidden.
    await expect(terminal.tapeRow(6)).toBeVisible();

    await terminal.page.getByTestId('tape-regular-only').click();
    await expect(terminal.tapeRow(6)).toHaveCount(0);
    await expect(terminal.tapeRows()).toHaveCount(5);
  });

  test('aggregation folds same-price prints into one row', async ({ terminal, backend }) => {
    await terminal.waitForChart();

    const base = Date.now();
    await backend.pushTape([
      { q: 7, t: base, p: 10.1, s: 100, a: 'ask' },
      { q: 8, t: base + 20, p: 10.1, s: 100, a: 'ask' },
      { q: 9, t: base + 40, p: 10.1, s: 300, a: 'ask' },
    ]);
    await expect(terminal.tapeRow(9)).toBeVisible();

    await terminal.page.getByTestId('tape-aggregate').click();

    // One row carrying all three, labelled with how many it swallowed.
    await expect(terminal.tapeRow(9)).toContainText('500');
    await expect(terminal.tapeRow(9)).toContainText('×3');
    await expect(terminal.tapeRow(8)).toHaveCount(0);
  });

  test('live prints land on top', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await expect(terminal.tapeRows()).toHaveCount(6);

    await backend.pushTape([{ q: 7, t: Date.now(), p: 10.2, s: 800, a: 'above' }]);

    await expect(terminal.tapeRows()).toHaveCount(7);
    await expect(terminal.tapeRows().first()).toHaveAttribute('data-testid', 'tape-row-7');
  });

  test('a batch that overlaps what is held does not double a row', async ({
    terminal,
    backend,
  }) => {
    // The broadcaster's cursor is shared by every client, so a late joiner is
    // deliberately sent rows its opening backlog already carried.
    await terminal.waitForChart();

    await backend.pushTape([
      ...makeTapePrints().slice(-2),
      { q: 7, t: Date.now(), p: 10.2, s: 100, a: 'ask' },
    ]);

    await expect(terminal.tapeRows()).toHaveCount(7);
  });

  test('freezing holds the window while the feed keeps running', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();

    await terminal.page.getByTestId('tape-pause').click();
    await backend.pushTape([{ q: 7, t: Date.now(), p: 10.2, s: 100, a: 'ask' }]);
    // Nothing to wait for, so give the frame a chance to be wrongly drawn.
    await terminal.page.waitForTimeout(200);
    await expect(terminal.tapeRows()).toHaveCount(6);

    await terminal.page.getByTestId('tape-pause').click();
    // Unfreezing lands on the live tape, backlog included.
    await expect(terminal.tapeRows()).toHaveCount(7);
  });

  test('a symbol switch breaks a freeze open', async ({ terminal, backend }) => {
    // The freeze survives; what it is holding does not. A frozen window left
    // under a new ticker would be showing the last company's prints, which is
    // the one thing a tape must never do.
    await terminal.waitForChart();
    await backend.pushTape([{ q: 7, t: Date.now(), p: 10.2, s: 100, a: 'ask' }]);
    await expect(terminal.tapeRows()).toHaveCount(7);

    await terminal.page.getByTestId('tape-pause').click();
    await terminal.setSymbol('TSLA');
    await terminal.waitForChart();

    await expect(terminal.tapeRows()).toHaveCount(6);
    await expect(terminal.page.getByTestId('tape-pause')).toHaveAttribute('aria-pressed', 'true');
  });

  test('and refills on the new symbol rather than latching the empty gap', async ({
    terminal,
    backend,
  }) => {
    // The store clears the tape the instant the symbol changes, and the new
    // company's buffer arrives a beat later — so there is a render where the
    // window is legitimately empty. A freeze that re-armed on *that* render
    // would hold the empty list for as long as the window stayed paused: a
    // lit pause button over a blank window, which reads as a dead feed
    // rather than as a freeze. The delay makes that gap certain instead of
    // lucky, which is the difference between this test and the one above.
    await terminal.waitForChart();
    await terminal.page.getByTestId('tape-pause').click();

    backend.setSnapshotDelay(300);
    await terminal.setSymbol('TSLA');
    await terminal.waitForChart();

    await expect(terminal.tapeRows()).toHaveCount(6);

    // And it re-armed rather than merely coming unstuck: the next print
    // stays behind the window.
    await backend.pushTape([{ q: 99, t: Date.now(), p: 10.4, s: 200, a: 'ask' }]);
    await terminal.page.waitForTimeout(200);
    await expect(terminal.tapeRows()).toHaveCount(6);
    await expect(terminal.page.getByTestId('tape-pause')).toHaveAttribute('aria-pressed', 'true');
  });

  test('says which way the visible tape leans', async ({ terminal }) => {
    await terminal.waitForChart();

    // 100 + 2,500 taken at or through the offer against 100 + 5,000 + 400
    // taken at or through the bid: 2,600 of 8,200, which rounds to 32%.
    await expect(terminal.page.getByTestId('tape-balance')).toHaveAttribute('data-buy-share', '32');
  });

  test('the lean follows the filters, so it cannot disagree with the rows', async ({
    terminal,
  }) => {
    await terminal.waitForChart();

    await terminal.page.getByTestId('tape-min-size').selectOption('1000');

    // Only the 2,500 buy and the 5,000 sell survive: 2,500 of 7,500 is 33%.
    await expect(terminal.page.getByTestId('tape-balance')).toHaveAttribute('data-buy-share', '33');
  });

  test('a symbol switch clears the window', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    await expect(terminal.tapeRows()).toHaveCount(6);

    await backend.pushTape([{ q: 7, t: Date.now(), p: 10.2, s: 100, a: 'ask' }]);
    await expect(terminal.tapeRows()).toHaveCount(7);

    await terminal.setSymbol('TSLA');
    await terminal.waitForChart();

    // The new symbol's own backlog, and nothing carried over from the last.
    await expect(terminal.tapeRows()).toHaveCount(6);
  });

  test('the filters survive a reload', async ({ terminal }) => {
    await terminal.waitForChart();

    await terminal.page.getByTestId('tape-min-size').selectOption('1000');
    await terminal.page.getByTestId('tape-aggregate').click();

    await terminal.page.reload();
    await terminal.waitForChart();

    await expect(terminal.page.getByTestId('tape-min-size')).toHaveValue('1000');
    await expect(terminal.page.getByTestId('tape-aggregate')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  test('a frozen tape is not what a reload comes back to', async ({ terminal }) => {
    // Coming back to a terminal to find a paused tape reads as a dead feed.
    await terminal.waitForChart();
    await terminal.page.getByTestId('tape-pause').click();

    await terminal.page.reload();
    await terminal.waitForChart();

    await expect(terminal.page.getByTestId('tape-pause')).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });
});

test.describe('a symbol that has not printed', () => {
  test.use({ backendOptions: { tape: [] } });

  test('says it is waiting rather than showing an empty box', async ({ terminal }) => {
    await terminal.waitForChart();

    await expect(terminal.page.getByTestId('tape-empty')).toContainText('Waiting');
    await expect(terminal.tapeRows()).toHaveCount(0);
  });
});
