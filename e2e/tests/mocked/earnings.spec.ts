import { SESSION_START } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/**
 * The earnings chip.
 *
 * A swing position held through a report is a different trade from the one
 * that was opened, and the usual way that happens is not knowing. The date
 * was already in the terminal, buried in the dock as an ISO string with no
 * sense of how soon — which is the only part that changes a decision.
 */

/**
 * Epoch seconds for a report `days` after the fixture's own clock.
 *
 * Counted from `generated_at` rather than from wall time: the fixtures are
 * frozen in March 2024 so runs are byte-identical, and the chip measures the
 * gap between the two fields of one `info` frame.
 */
const INFO_GENERATED_AT = SESSION_START + 240 * 10;

function inDays(days: number): number {
  return INFO_GENERATED_AT + days * 86_400;
}

test.describe('earnings proximity', () => {
  test('says nothing when no report is scheduled', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('tp-earnings')).toHaveCount(0);
  });

  test.describe('a report inside the week', () => {
    test.use({ backendOptions: { infoOverrides: { earnings_next: inDays(3) } } });

    test('is shown, and loudly', async ({ terminal }) => {
      await terminal.waitForChart();
      const chip = terminal.page.getByTestId('tp-earnings');
      await expect(chip).toBeVisible();
      await expect(chip).toContainText('3d');
      await expect(chip).toHaveClass(/text-down/);
    });
  });

  test.describe('a report a fortnight out', () => {
    test.use({ backendOptions: { infoOverrides: { earnings_next: inDays(12) } } });

    test('is shown, but quieter', async ({ terminal }) => {
      await terminal.waitForChart();
      const chip = terminal.page.getByTestId('tp-earnings');
      await expect(chip).toContainText('12d');
      await expect(chip).not.toHaveClass(/text-down/);
    });
  });

  test.describe('a report today', () => {
    test.use({ backendOptions: { infoOverrides: { earnings_next: inDays(0) } } });

    test('says so rather than counting zero days', async ({ terminal }) => {
      await terminal.waitForChart();
      await expect(terminal.page.getByTestId('tp-earnings')).toContainText('TODAY');
    });
  });

  test.describe('a date that has passed', () => {
    test.use({ backendOptions: { infoOverrides: { earnings_next: inDays(-3) } } });

    test('is dropped rather than counted backwards', async ({ terminal }) => {
      // The source keeps serving the last scheduled date for a while after
      // the event, and "ERN -3d" reads as a date still to come.
      await terminal.waitForChart();
      await expect(terminal.page.getByTestId('tp-earnings')).toHaveCount(0);
    });
  });

  test.describe('a report next quarter', () => {
    test.use({ backendOptions: { infoOverrides: { earnings_next: inDays(120) } } });

    test('is beyond the horizon and not drawn', async ({ terminal }) => {
      // Four months out is not a fact about today's position.
      await terminal.waitForChart();
      await expect(terminal.page.getByTestId('tp-earnings')).toHaveCount(0);
    });
  });
});
