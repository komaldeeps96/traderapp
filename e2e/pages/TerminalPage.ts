/**
 * Page object for the terminal.
 *
 * The chart is a canvas, so assertions come from two places: the DOM for
 * everything around it, and the engine's own `inspect()` for what was actually
 * drawn.
 */

import { expect, type Locator, type Page } from '@playwright/test';

import type { ScannerTierId } from '../fixtures/data';

export interface ChartState {
  barCount: number;
  lastBar: { t: number; o: number; h: number; l: number; c: number; v: number; n: number } | null;
  timeframe: string;
  theme: string;
  paneCount: number;
  /** Price pane first, then each sub-pane, in pixels. */
  paneHeights: number[];
  subPaneOffset: number;
  /** The measure tool — canvas-painted, so unreachable from the DOM. */
  measure: {
    active: boolean;
    selection: {
      bars: number;
      priceDelta: number;
      percent: number;
      volume: number;
      direction: 'up' | 'down';
    } | null;
  };
  seriesIds: string[];
  pointCounts: Record<string, number>;
  visible: Record<string, boolean>;
  lineWidths: Record<string, number>;
  lineColors: Record<string, string>;
  axisLabels: Record<string, boolean>;
  visibleRange: { from: number; to: number } | null;
  hasVolumePane: boolean;
  hasMacdPane: boolean;
  dollarLineCount: number;
  /** The ATH price line, canvas-painted like the dollar grid. */
  athLine: number | null;
  /** Key levels that stood down from the axis for the price label. */
  axisYieldedToPrice: string[];
  /** Bar countdown on the price axis; painted, so invisible to the DOM. */
  countdown: { text: string; closing: boolean } | null;
  paneSeries: {
    volume: { axisLabel: boolean; title: string } | null;
    trades: { axisLabel: boolean; title: string } | null;
  };
}

export interface TerminalState {
  symbol: string;
  timeframe: string;
  status: string;
  connected: boolean;
  source: string;
  delayed: boolean;
  barCount: number;
  visibility: Record<string, boolean>;
  miniTimeframes: string[];
}

export class TerminalPage {
  constructor(readonly page: Page) {}

  // ── locators ─────────────────────────────────────────────────────────

  get chart(): Locator {
    return this.page.getByTestId('chart-canvas');
  }

  /** The header sits inside <main>, so it is not a `banner` landmark. */
  get toolbar(): Locator {
    return this.page.getByTestId('toolbar');
  }

  get symbolInput(): Locator {
    return this.page.getByTestId('symbol-input');
  }

  get sourceBadge(): Locator {
    return this.page.getByTestId('source-badge');
  }

  get delayedBadge(): Locator {
    return this.page.getByTestId('delayed-badge');
  }

  get ohlcv(): Locator {
    return this.page.getByTestId('ohlcv');
  }

  get errorBanner(): Locator {
    return this.page.getByTestId('error-banner');
  }

  get keyLevels(): Locator {
    return this.page.getByTestId('key-levels');
  }

  get keyLevelRows(): Locator {
    return this.page.locator('[data-testid^="level-row-"]');
  }

  get priceMarker(): Locator {
    return this.page.getByTestId('price-marker');
  }

  /** One of the four market-cap-tiered scanner panels — 'small_cap' by default. */
  scannerPanel(tierId: ScannerTierId = 'small_cap'): Locator {
    return this.page.getByTestId(`scanner-${tierId}`);
  }

  scannerNote(tierId: ScannerTierId = 'small_cap'): Locator {
    return this.page.getByTestId(`scanner-${tierId}-note`);
  }

  scannerRows(tierId: ScannerTierId = 'small_cap'): Locator {
    return this.page.locator(`[data-testid^="scanner-${tierId}-row-"]`);
  }

  get themeToggle(): Locator {
    return this.page.getByTestId('theme-toggle');
  }

  /**
   * The main chart's floating zoom/pan cluster. Scoped rather than reached by
   * accessible name alone, since the mini charts carry their own zoom buttons.
   */
  get chartControls(): Locator {
    return this.page.getByTestId('chart-controls');
  }

  /** The context charts in the dock. Absent below their breakpoint. */
  get miniCharts(): Locator {
    return this.page.getByTestId('mini-charts');
  }

  /** The right-hand rail that holds them, and the other three tabs. */
  get dock(): Locator {
    return this.page.getByTestId('dock');
  }

  dockTab(id: 'charts' | 'fundamentals' | 'news' | 'filings'): Locator {
    return this.page.getByTestId(`dock-tab-${id}`);
  }

  /** Every tab on the rail. A tab is well inside the visual tolerance, so
   *  the baselines count them rather than trusting the pixels. */
  dockTabs(): Locator {
    return this.dock.getByRole('tablist', { name: 'Dock panels' }).getByRole('tab');
  }

  dockPanel(id: 'fundamentals' | 'news' | 'filings'): Locator {
    return this.page.getByTestId(`dock-${id}`);
  }

  miniChart(timeframe: string): Locator {
    return this.page.getByTestId(`mini-chart-${timeframe}`);
  }

  miniReset(timeframe: string): Locator {
    return this.page.getByTestId(`mini-reset-${timeframe}`);
  }

  timeframeTab(timeframe: string): Locator {
    return this.page.getByTestId(`timeframe-${timeframe}`);
  }

  indicatorChip(id: string): Locator {
    return this.page.getByTestId(`indicator-${id}`);
  }

  /** A band's row. Its key is the ids of its members joined by '+'. */
  levelRow(key: string): Locator {
    return this.page.getByTestId(`level-row-${key}`);
  }

  /** The price of each band, read from the row rather than parsed from text. */
  keyLevelValues(): Promise<number[]> {
    return this.page.$$eval('[data-testid^="level-row-"]', (rows) =>
      rows.map((row) => Number(row.getAttribute('data-value'))),
    );
  }

  ohlcvField(field: 'open' | 'high' | 'low' | 'close' | 'volume' | 'trades'): Locator {
    return this.page.getByTestId(`ohlcv-${field}`);
  }

  // ── actions ──────────────────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/');
  }

  async waitForChart(): Promise<void> {
    await expect(this.chart).toBeVisible();
    await this.page.waitForFunction(() => window.__traderapp?.ready() === true, undefined, {
      timeout: 15_000,
    });
    // One frame so the canvas has actually painted before a screenshot.
    await this.page.waitForFunction(() => {
      const chart = window.__traderapp?.chart() as { barCount?: number } | null;
      return (chart?.barCount ?? 0) > 0;
    });
  }

  async setSymbol(symbol: string): Promise<void> {
    await this.symbolInput.fill(symbol);
    await this.symbolInput.press('Enter');
  }

  async selectTimeframe(timeframe: string): Promise<void> {
    await this.timeframeTab(timeframe).click();
  }

  /**
   * Place the crosshair on the bar at a fraction across the chart's width.
   *
   * The chart tracks a stream of pointer moves rather than a final position,
   * and Playwright's synthetic pointer does not reliably produce one on first
   * entry in Firefox and WebKit — so the move repeats, varying the approach,
   * until the readout confirms a bar is under the crosshair.
   */
  async hoverChart(fractionX = 0.5, fractionY = 0.5): Promise<void> {
    const box = await this.chart.boundingBox();
    if (!box) throw new Error('the chart has no box');

    const targetX = box.x + box.width * fractionX;
    const targetY = box.y + box.height * fractionY;

    for (let attempt = 0; attempt < 6; attempt += 1) {
      // Park outside the chart so entering it is a genuine crossing.
      await this.page.mouse.move(box.x + box.width * 0.5, Math.max(1, box.y - 20));
      await nextFrames(this.page, 1);

      // Approach from the far side of the target; the extreme edges are dead
      // zones and entering at the target itself gives the chart no movement.
      const entryFraction = attempt % 2 === 0 ? (fractionX > 0.5 ? 0.25 : 0.75) : 0.5;
      await this.page.mouse.move(
        box.x + box.width * entryFraction,
        box.y + box.height * 0.45,
        { steps: 4 },
      );
      await this.page.mouse.move(targetX, targetY, { steps: 12 });
      await nextFrames(this.page, 2);

      if ((await this.ohlcv.getAttribute('data-hovering')) === 'true') return;
    }

    throw new Error(
      `the crosshair never landed on a bar at x=${fractionX}; ` +
        'is that position inside the plotted data?',
    );
  }

  async moveMouseAway(): Promise<void> {
    const box = await this.chart.boundingBox();
    if (box) {
      // Leave through the top edge so a leave event is generated, rather than
      // teleporting straight to the corner.
      await this.page.mouse.move(box.x + box.width / 2, box.y + 4, { steps: 6 });
    }
    await this.page.mouse.move(2, 2, { steps: 6 });
    await nextFrames(this.page, 2);
  }

  // ── introspection ────────────────────────────────────────────────────

  chartState(): Promise<ChartState> {
    return this.page.evaluate(() => window.__traderapp!.chart() as ChartState);
  }

  /** Bars across the visible range. The time scale applies changes on its own frame. */
  async visibleRangeWidth(): Promise<number> {
    const range = (await this.chartState()).visibleRange!;
    return range.to - range.from;
  }

  /**
   * The width once it has stopped moving. The layout keeps settling after the
   * first snapshot — panels mount, the canvas resizes — and a baseline read in
   * that window belongs to a view that is about to change.
   */
  async settledRangeWidth(): Promise<number> {
    let previous = Number.NaN;
    await expect
      .poll(
        async () => {
          const width = await this.visibleRangeWidth();
          const still = width === previous;
          previous = width;
          return still;
        },
        { intervals: [250] },
      )
      .toBe(true);
    return previous;
  }

  /** What a mini chart actually drew. Null when the column is not rendered. */
  miniChartState(timeframe: string): Promise<ChartState | null> {
    return this.page.evaluate(
      (tf) => window.__traderapp!.miniChart(tf) as ChartState | null,
      timeframe,
    );
  }

  /**
   * Wait until every mini slot has drawn something. Asked of the store's own
   * `miniTimeframes` rather than a hardcoded list, so a spec that retimes a
   * slot waits for the charts that actually exist.
   */
  async waitForMiniCharts(): Promise<void> {
    await this.page.waitForFunction(
      () => {
        const hooks = window.__traderapp;
        const timeframes = (hooks?.state() as { miniTimeframes?: string[] } | undefined)
          ?.miniTimeframes;
        if (!hooks || !timeframes?.length) return false;
        return timeframes.every(
          (tf) => ((hooks.miniChart(tf) as { barCount?: number } | null)?.barCount ?? 0) > 0,
        );
      },
      undefined,
      { timeout: 15_000 },
    );
  }

  state(): Promise<TerminalState> {
    return this.page.evaluate(() => window.__traderapp!.state() as TerminalState);
  }

  theme(): Promise<string | null> {
    return this.page.evaluate(() => document.documentElement.dataset.theme ?? null);
  }
}

declare global {
  interface Window {
    __traderapp?: {
      chart: () => unknown;
      miniChart: (timeframe: string) => unknown;
      state: () => unknown;
      ready: () => boolean;
    };
  }
}

/**
 * Let the page paint: the crosshair publishes on animation frames, so a frame
 * is the unit to wait in, not milliseconds that stretch on a loaded machine.
 */
async function nextFrames(page: Page, count: number): Promise<void> {
  await page.evaluate(
    (frames) =>
      new Promise<void>((resolve) => {
        const step = (left: number) =>
          left === 0 ? resolve() : requestAnimationFrame(() => step(left - 1));
        step(frames);
      }),
    count,
  );
}
