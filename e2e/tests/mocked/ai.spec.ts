import { expect, test } from '../../fixtures/test';
import { makeSetup } from '../../fixtures/data';

/**
 * The AI tab — the setup, judged.
 *
 * Every other panel reports; this one answers. What a browser test can hold
 * is the contract around that answer, and four things earn one.
 *
 * That the score reaches the DOM as a number *and* a grade, because the grade
 * is Cameron's own and carries measured accuracy — a B is not "a slightly
 * worse A", it is four pillars of five at 65-80%.
 *
 * That a veto renders **above** the prose and in the disqualifier colour. The
 * book's finding on catastrophic losses is that they are never "the setup
 * looked bad", they are one specific gate overridden — so a gate that fired
 * must not be somewhere in a paragraph.
 *
 * That all five pillars always render, in order, even when the reader left
 * one out. The row is scanned, not read, and a gap in it would be taken for
 * a blank rather than for a missing answer.
 *
 * And that a judgement whose price has moved says so, because this reads a
 * moving target and one that ages into wrongness silently is worse than none.
 */
test.describe('the AI setup tab', () => {
  test('judges the whole screen, not one number', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('ai').click();

    const score = terminal.page.getByTestId('ai-score');
    await expect(score).toHaveAttribute('data-score', '6');
    await expect(score).toHaveAttribute('data-grade', 'B');
    await expect(terminal.page.getByTestId('ai-headline')).toContainText('easy to borrow');
    await expect(terminal.page.getByTestId('ai-judgement')).toContainText('WRVOL 61x');
  });

  test('a fired gate is its own block, not a sentence in a paragraph', async ({ terminal }) => {
    await terminal.waitForChart();
    await terminal.dockTab('ai').click();

    const vetoes = terminal.page.getByTestId('ai-vetoes');
    await expect(vetoes).toContainText('Easy to borrow');
    // Above the prose: a trader mid-run must not have to read to find it.
    const [vetoBox, proseBox] = await Promise.all([
      vetoes.boundingBox(),
      terminal.page.getByTestId('ai-judgement').boundingBox(),
    ]);
    expect(vetoBox!.y).toBeLessThan(proseBox!.y);
  });

  test('renders all five pillars in order, whatever came back', async ({ terminal, page }) => {
    // The reader left out `change` entirely. The row is scanned rather than
    // read, so the gap has to say "unknown" rather than look like a blank.
    await page.route('**/api/setup/*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          makeSetup('AAPL', {
            pillars: [
              { name: 'price', state: 'ok', note: '$3.42' },
              { name: 'float', state: 'strong', note: '2.10M' },
            ],
          }),
        ),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('ai').click();

    const chips = terminal.page.getByTestId('ai-pillars').locator('[data-testid^="ai-pillar-"]');
    await expect(chips).toHaveCount(5);
    await expect(terminal.page.getByTestId('ai-pillar-change')).toHaveAttribute(
      'data-state',
      'unknown',
    );
    await expect(terminal.page.getByTestId('ai-pillar-float')).toHaveAttribute(
      'data-state',
      'strong',
    );
  });

  test('says when the tape has moved out from under the reading', async ({ terminal, page }) => {
    await page.route('**/api/setup/*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeSetup('AAPL', { stale: true })),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('ai').click();

    await expect(terminal.page.getByTestId('ai-stale')).toBeVisible();
  });

  test('nothing is asked for until the tab is opened', async ({ terminal, page }) => {
    // A judgement costs a cent and a minute. A tab nobody is looking at must
    // not be spending either.
    const asked: string[] = [];
    await page.route('**/api/setup/*', (route) => {
      asked.push(route.request().url());
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeSetup()),
      });
    });
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('news').click();
    await terminal.page.waitForTimeout(300);
    expect(asked).toHaveLength(0);

    await terminal.dockTab('ai').click();
    await expect(terminal.page.getByTestId('ai-score')).toBeVisible();
    expect(asked.length).toBe(1);
  });

  test('refreshing asks for a fresh reading rather than the cached one', async ({
    terminal,
    page,
  }) => {
    const asked: string[] = [];
    await page.route('**/api/setup/*', (route) => {
      asked.push(route.request().url());
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeSetup()),
      });
    });
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('ai').click();
    await expect(terminal.page.getByTestId('ai-score')).toBeVisible();

    await terminal.page.getByTestId('ai-refresh').click();
    await expect.poll(() => asked.some((url) => url.includes('refresh=true'))).toBe(true);
  });

  test('says why there is nothing rather than showing an empty box', async ({ terminal, page }) => {
    await page.route('**/api/setup/*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          symbol: 'AAPL',
          status: 'no-cli',
          available: false,
          judgement: null,
          note: "The 'claude' CLI was not found on this machine.",
        }),
      }),
    );
    await terminal.goto();
    await terminal.waitForChart();
    await terminal.dockTab('ai').click();

    await expect(terminal.page.getByTestId('ai-note')).toContainText('was not found');
  });
});
