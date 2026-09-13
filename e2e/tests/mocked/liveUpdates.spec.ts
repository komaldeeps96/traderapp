import { makeNextBar } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/** The bar already on screen, revised to `close`: a sentinel that adds no bar. */
function reviseLast(snapshot: Parameters<typeof makeNextBar>[0], close: number) {
  const t = snapshot.bars.at(-1)!.t;
  return makeNextBar(snapshot, { t, o: close, h: close, l: close, c: close });
}

test.describe('live updates', () => {
  test('appends a new bar to the chart', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const before = (await terminal.chartState()).barCount;

    await backend.send(makeNextBar(backend.lastSnapshot()!));

    await expect.poll(async () => (await terminal.chartState()).barCount).toBe(before + 1);
  });

  test('moves the price readout', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const snapshot = backend.lastSnapshot()!;

    await backend.send(makeNextBar(snapshot, { c: 99.5, h: 99.9, l: 90 }));

    await expect(terminal.ohlcvField('close')).toHaveText('99.50');
  });

  test('updates an existing bar in place rather than duplicating it', async ({
    terminal,
    backend,
  }) => {
    await terminal.waitForChart();
    const snapshot = backend.lastSnapshot()!;

    const update = makeNextBar(snapshot, { c: 50 });
    await backend.send(update);
    await expect.poll(async () => (await terminal.chartState()).barCount).toBeGreaterThan(
      snapshot.bars.length,
    );
    const afterFirst = (await terminal.chartState()).barCount;

    // The same period arriving again is a revision, not a new bar.
    await backend.send({ ...update, bar: { ...update.bar, c: 55 } });
    await expect(terminal.ohlcvField('close')).toHaveText('55.00');
    expect((await terminal.chartState()).barCount).toBe(afterFirst);
  });

  test('moves the indicator values', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const before = await terminal.indicatorChip('ema9').textContent();

    await backend.send(makeNextBar(backend.lastSnapshot()!, { c: 77 }));

    await expect.poll(async () => terminal.indicatorChip('ema9').textContent()).not.toBe(before);
  });

  test('ignores an update for a symbol that is not on screen', async ({ terminal, backend }) => {
    // A late frame for a symbol the user already left must never be drawn.
    await terminal.waitForChart();
    const snapshot = backend.lastSnapshot()!;
    const { barCount } = await terminal.chartState();

    const stale = makeNextBar(snapshot, { c: 12345 });
    await backend.send({ ...stale, symbol: 'SOMETHINGELSE' });
    await backend.send(reviseLast(snapshot, 42));

    await expect(terminal.ohlcvField('close')).toHaveText('42.00');
    expect((await terminal.chartState()).barCount).toBe(barCount);
  });

  test('ignores an update for a different timeframe', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const snapshot = backend.lastSnapshot()!;
    const { barCount } = await terminal.chartState();

    const stale = makeNextBar(snapshot, { c: 54321 });
    await backend.send({ ...stale, timeframe: '1h' });
    await backend.send(reviseLast(snapshot, 42));

    await expect(terminal.ohlcvField('close')).toHaveText('42.00');
    expect((await terminal.chartState()).barCount).toBe(barCount);
  });

  test('keeps showing the hovered bar rather than the live one', async ({ terminal, backend }) => {
    // The crosshair tracks a pixel, and appending a bar shifts the chart, so
    // the bar under the cursor may legitimately change. What must not happen
    // is the readout jumping to the newest bar while the user is reading
    // history.
    await terminal.waitForChart();
    await terminal.hoverChart(0.3);
    await expect(terminal.ohlcv).toHaveAttribute('data-hovering', 'true');

    await backend.send(makeNextBar(backend.lastSnapshot()!, { c: 88 }));
    await expect.poll(async () => (await terminal.chartState()).lastBar!.c).toBe(88);

    await expect(terminal.ohlcv).toHaveAttribute('data-hovering', 'true');
    await expect(terminal.ohlcvField('close')).not.toHaveText('88.00');
  });

  test('survives a burst of updates', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const snapshot = backend.lastSnapshot()!;
    const base = makeNextBar(snapshot);

    for (let i = 0; i < 25; i += 1) {
      await backend.send({ ...base, bar: { ...base.bar, c: 10 + i * 0.1 } });
    }

    await expect(terminal.ohlcvField('close')).toHaveText('12.40');
  });
});
