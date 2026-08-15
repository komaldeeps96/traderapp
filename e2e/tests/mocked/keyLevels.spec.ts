import { makeNextBar } from '../../fixtures/data';
import { expect, test } from '../../fixtures/test';

/**
 * The key-levels table is the momentum workflow: which band is next in the
 * way, how far it is, and how many levels agree on it. These tests protect
 * that ordering, the arithmetic, and the confluence grouping.
 */
test.describe('key levels', () => {
  test('lists the levels', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.keyLevels).toBeVisible();
    expect(await terminal.keyLevelRows.count()).toBeGreaterThan(3);
  });

  test('includes the levels that drive a momentum trade', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.keyLevels).toContainText('PM High');
    await expect(terminal.keyLevels).toContainText('PM Low');
    await expect(terminal.keyLevels).toContainText('52W High');
  });

  test('sorts from highest price to lowest', async ({ terminal }) => {
    await terminal.waitForChart();
    const prices = await terminal.keyLevelValues();
    expect(prices.every((price) => Number.isFinite(price))).toBe(true);
    expect(prices).toEqual([...prices].sort((a, b) => b - a));
  });

  test('marks the last price in its true position', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.priceMarker).toBeVisible();

    const order = await terminal.page.$$eval(
      '[data-testid^="level-row-"], [data-testid="price-marker"]',
      (rows) => rows.map((row) => row.getAttribute('data-testid')),
    );
    const markerIndex = order.indexOf('price-marker');
    // Everything above the marker is overhead supply and everything below is
    // support — that split is what makes the table readable at a glance.
    const sides = await terminal.page.$$eval('[data-testid^="level-row-"]', (rows) =>
      rows.map((row) => row.getAttribute('data-side')),
    );
    expect(sides.slice(0, markerIndex).every((side) => side === 'above')).toBe(true);
    expect(sides.slice(markerIndex).every((side) => side !== 'above')).toBe(true);
  });

  test('shows a signed percentage distance', async ({ terminal }) => {
    await terminal.waitForChart();
    const distances = await terminal.page.$$eval('[data-testid^="level-row-"]', (rows) =>
      rows.map((row) => row.querySelectorAll('td')[3]?.textContent ?? ''),
    );
    expect(distances.length).toBeGreaterThan(0);
    expect(distances.every((text) => /^[+-]\d+\.\d{2}%$/.test(text))).toBe(true);
  });

  test('follows the crosshair back through history', async ({ terminal }) => {
    await terminal.waitForChart();
    const before = await terminal.priceMarker.textContent();
    await terminal.hoverChart(0.25);
    await expect.poll(async () => terminal.priceMarker.textContent()).not.toBe(before);
  });
});

test.describe('confluence bands', () => {
  test('groups levels that sit at the same price', async ({ terminal }) => {
    await terminal.waitForChart();
    const band = terminal.page.locator('[data-testid^="level-row-"][data-strength="3"]');
    await expect(band).toHaveCount(1);
  });

  test('shows how many levels agree', async ({ terminal }) => {
    await terminal.waitForChart();
    const band = terminal.page.locator('[data-testid^="level-row-"][data-strength="3"]');
    await expect(band).toContainText('×3');
    await expect(band).toContainText('3 levels');
  });

  test('names the levels that make up the band', async ({ terminal }) => {
    await terminal.waitForChart();
    const band = terminal.page.locator('[data-testid^="level-row-"][data-strength="3"]');
    await expect(band).toContainText('Prev Day Close');
    await expect(band).toContainText('1D SMA 20');
  });

  test('shows the extent of the band', async ({ terminal }) => {
    await terminal.waitForChart();
    const band = terminal.page.locator('[data-testid^="level-row-"][data-strength="3"]');
    await expect(band).toContainText('–');
  });

  test('does not let a long member list squeeze out price and distance', async ({ terminal }) => {
    // A band lists every level in it, which in an auto-layout table grew the
    // label column until the numbers had no width left at all.
    await terminal.waitForChart();
    const band = terminal.page.locator('[data-testid^="level-row-"][data-strength="3"]');

    for (const column of [2, 3]) {
      const cell = band.locator('td').nth(column);
      await expect(cell).not.toBeEmpty();
      const box = await cell.boundingBox();
      expect(box!.width).toBeGreaterThan(30);
    }
  });

  test('shades a stacked shelf as a zone rather than one thicker line', async ({
    terminal,
  }) => {
    // A shelf has a thickness, and where it starts and stops is what a stop
    // is placed against. One heavier line said it was there and nothing more.
    await terminal.waitForChart();
    const state = await terminal.chartState();
    expect(state.bands.length).toBeGreaterThan(0);
    const band = state.bands[0];
    expect(band.high).toBeGreaterThan(band.low);
    expect(band.color).toMatch(/^rgba\(/);
  });

  test('labels a band once instead of once per level', async ({ terminal }) => {
    // Nine colliding axis labels was the problem this solves.
    await terminal.waitForChart();
    const state = await terminal.chartState();
    const members = ['prev_day_close', 'prev_day_high', 'd_sma20'];
    const labelled = members.filter((id) => state.axisLabels[id]);
    expect(labelled).toHaveLength(1);
  });

  test('counts bands rather than levels in the header', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.page.getByTestId('key-levels-count')).toContainText('bands');
  });

  test('hides every level in a band with one toggle', async ({ terminal }) => {
    await terminal.waitForChart();
    const band = terminal.page.locator('[data-testid^="level-row-"][data-strength="3"]');
    await band.getByRole('button').click();

    await expect
      .poll(async () => (await terminal.chartState()).visible.prev_day_close)
      .toBe(false);
    const state = await terminal.chartState();
    expect(state.visible.prev_day_high).toBe(false);
    expect(state.visible.d_sma20).toBe(false);
  });
});

test.describe('actionable levels', () => {
  test('colours the nearest band above as resistance', async ({ terminal }) => {
    await terminal.waitForChart();
    const rows = terminal.page.locator('[data-testid^="level-row-"][data-emphasis="resistance"]');
    await expect(rows).toHaveCount(1);
    await expect(rows).toHaveAttribute('data-side', 'above');
  });

  test('colours the nearest band below as support', async ({ terminal }) => {
    await terminal.waitForChart();
    const rows = terminal.page.locator('[data-testid^="level-row-"][data-emphasis="support"]');
    await expect(rows).toHaveCount(1);
    await expect(rows).toHaveAttribute('data-side', 'below');
  });

  test('leaves the rest recessive', async ({ terminal }) => {
    await terminal.waitForChart();
    const normal = terminal.page.locator('[data-testid^="level-row-"][data-emphasis="normal"]');
    expect(await normal.count()).toBeGreaterThan(0);
  });

  test('paints those two on the chart and nothing else', async ({ terminal }) => {
    await terminal.waitForChart();
    const state = await terminal.chartState();
    const levelIds = [
      'pm_high',
      'pm_low',
      'prev_day_close',
      'prev_day_high',
      'prev_day_low',
      'high_52w',
      'low_52w',
      'd_sma20',
    ];
    const coloured = levelIds.filter((id) => {
      const colour = state.lineColors[id];
      return colour && colour !== '#898781';
    });
    // The two actionable bands, and only those, earn colour — though a band
    // may contribute more than one line.
    expect(coloured.length).toBeGreaterThan(0);
    expect(coloured.length).toBeLessThan(levelIds.length);
  });

  test('measures distance from the crosshair, not the live price', async ({ terminal }) => {
    // Which band is nearest only changes when the price crosses one, so the
    // thing to check is that the distances are recomputed against whichever
    // bar is under the crosshair.
    const resistance = terminal.page.locator('[data-emphasis="resistance"]').first();

    await terminal.waitForChart();
    const live = await resistance.locator('td').nth(3).textContent();

    await terminal.hoverChart(0.2);
    await expect.poll(async () => resistance.locator('td').nth(3).textContent()).not.toBe(live);
  });
});

test.describe('sub-dollar tickers', () => {
  test.use({ backendOptions: { basePrice: 0.42 } });

  test('keeps enough decimals to tell levels apart', async ({ terminal }) => {
    // At $0.40 a cent is over 2%, so two decimals would round distinct levels
    // onto the same number.
    await terminal.waitForChart();
    const prices = await terminal.page.$$eval('[data-testid^="level-row-"]', (rows) =>
      rows.map((row) => row.querySelectorAll('td')[2]?.textContent?.trim() ?? ''),
    );
    expect(prices.some((text) => /^\d\.\d{4}/.test(text))).toBe(true);
  });

  test('shows the price marker with the same precision', async ({ terminal }) => {
    await terminal.waitForChart();
    await expect(terminal.priceMarker).toContainText(/\d\.\d{4}/);
  });
});

/**
 * Finding the price in a long list.
 *
 * On a gapper with a quarter's and a year's highs stacked overhead, the last
 * price sits far enough down the table that the panel opens on levels nobody
 * is trading against. The viewport here is short on purpose: it is the state
 * a real screen reaches by having more levels, not fewer pixels, and it is
 * the only way to force the overflow deterministically.
 */
test.describe('keeping the price in view', () => {
  // Six longer-period highs stacked overhead, as a faded runner carries. The
  // viewport is trimmed as well so the panel is genuinely short of room.
  test.use({ backendOptions: { manyLevels: true }, viewport: { width: 1440, height: 420 } });

  const geometry = (page: import('@playwright/test').Page) =>
    page.evaluate(() => {
      const marker = document.querySelector('[data-testid="price-marker"]');
      const scroller = marker?.closest('.overflow-y-auto');
      if (!marker || !scroller) return null;
      const markerBox = marker.getBoundingClientRect();
      const scrollBox = scroller.getBoundingClientRect();
      return {
        overflows: scroller.scrollHeight > scroller.clientHeight + 1,
        scrollTop: scroller.scrollTop,
        markerCentre: markerBox.top + markerBox.height / 2 - scrollBox.top,
        viewportHeight: scrollBox.height,
      };
    });

  test('scrolls the last price into view without being asked', async ({ terminal }) => {
    await terminal.waitForChart();
    const box = await geometry(terminal.page);

    expect(box!.overflows).toBe(true);
    expect(box!.markerCentre).toBeGreaterThan(0);
    expect(box!.markerCentre).toBeLessThan(box!.viewportHeight);
  });

  test('puts it in the middle rather than merely on screen', async ({ terminal }) => {
    await terminal.waitForChart();
    const box = await geometry(terminal.page);

    // Within a quarter of the panel's height of dead centre. Loose enough to
    // survive a row-height change, tight enough that "somewhere on screen"
    // would not pass.
    const drift = Math.abs(box!.markerCentre - box!.viewportHeight / 2);
    expect(drift).toBeLessThan(box!.viewportHeight / 4);
  });

  test('does not fight a manual scroll', async ({ terminal, backend }) => {
    // Price ticking does not move the marker's place in the list, so scrolling
    // away to read the 52-week high has to survive the next update.
    await terminal.waitForChart();
    await terminal.page.evaluate(() => {
      document.querySelector('[data-testid="price-marker"]')!.closest('.overflow-y-auto')!.scrollTop = 0;
    });

    await backend.pushQuote({ bid: 10.05, ask: 10.09 });
    await terminal.page.waitForTimeout(250);

    expect((await geometry(terminal.page))!.scrollTop).toBe(0);
  });
});

/**
 * Who owns the price axis when a level and the last trade collide.
 *
 * Three boxes end up competing for the same few pixels — the level's value,
 * the price, and the countdown pinned under it — and the library's answer is
 * to shuffle them apart, which pushes the price label off the price it names.
 *
 * The level yields instead. Its axis box is only a number; the text that says
 * *which* level it is sits in the chart area and does not move, and the line
 * itself is still drawn. The price and the seconds left on the bar are what
 * the eye is on at exactly the moment they meet.
 */
test.describe('price label priority', () => {
  test('leaves level labels alone when nothing is near the price', async ({ terminal }) => {
    await terminal.waitForChart();
    expect((await terminal.chartState()).axisYieldedToPrice).toEqual([]);
  });

  test('stands a level down when the price reaches it', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const snapshot = backend.lastSnapshot()!;
    // The pre-market high, as a price rather than a percentage — this is the
    // breakout moment, when the two labels genuinely land on each other.
    const pmHigh = snapshot.series.pm_high[0][1];

    await backend.send(makeNextBar(snapshot, { c: pmHigh, h: pmHigh, l: pmHigh - 0.05 }));

    await expect
      .poll(async () => (await terminal.chartState()).axisYieldedToPrice)
      .toContain('pm_high');
  });

  test('gives the label back when the price moves away', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const snapshot = backend.lastSnapshot()!;
    const pmHigh = snapshot.series.pm_high[0][1];

    await backend.send(makeNextBar(snapshot, { c: pmHigh, h: pmHigh, l: pmHigh - 0.05 }));
    await expect
      .poll(async () => (await terminal.chartState()).axisYieldedToPrice)
      .toContain('pm_high');

    await backend.send(
      makeNextBar(snapshot, { c: pmHigh * 0.9, h: pmHigh, l: pmHigh * 0.88 }),
    );

    await expect
      .poll(async () => (await terminal.chartState()).axisYieldedToPrice)
      .not.toContain('pm_high');
  });

  test('only the colliding level stands down', async ({ terminal, backend }) => {
    await terminal.waitForChart();
    const snapshot = backend.lastSnapshot()!;
    const pmHigh = snapshot.series.pm_high[0][1];

    await backend.send(makeNextBar(snapshot, { c: pmHigh, h: pmHigh, l: pmHigh - 0.05 }));

    await expect
      .poll(async () => (await terminal.chartState()).axisYieldedToPrice.length)
      .toBeGreaterThan(0);
    const state = await terminal.chartState();
    // The 52-week low is nowhere near; it keeps its label.
    expect(state.axisYieldedToPrice).not.toContain('low_52w');
    expect(state.axisLabels.low_52w).toBe(true);
  });
});
