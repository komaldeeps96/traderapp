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
  subPaneOffset: number;
  /** Shaded confluence zones — canvas-painted, so unreachable from the DOM. */
  bands: Array<{ low: number; high: number; color: string }>;
  /** The measure tool — also canvas-painted. */
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
   * The main chart's floating zoom/pan cluster.
   *
   * Scoped rather than reached by accessible name alone: the mini charts carry
   * their own zoom buttons, so "the Zoom in button" is now a question about
   * which chart.
   */
  get chartControls(): Locator {
    return this.page.getByTestId('chart-controls');
  }

  /** The 1m/5m context column. Absent below its breakpoint. */
  get miniCharts(): Locator {
    return this.page.getByTestId('mini-charts');
  }

  miniChart(timeframe: string): Locator {
    return this.page.getByTestId(`mini-chart-${timeframe}`);
  }

  miniReset(timeframe: '1m' | '5m'): Locator {
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
   * The chart tracks a stream of pointer moves rather than a final position.
   * A real mouse always enters as a continuous stream, but Playwright's
   * synthetic pointer does not reliably produce one on its first entry in
   * Firefox and WebKit, so the move is repeated — varying the approach — until
   * the readout confirms a bar is actually under the crosshair. Failing loudly
   * after that beats a test that silently asserts nothing.
   */
  async hoverChart(fractionX = 0.5, fractionY = 0.5): Promise<void> {
    const box = await this.chart.boundingBox();
    if (!box) throw new Error('the chart has no box');

    const targetX = box.x + box.width * fractionX;
    const targetY = box.y + box.height * fractionY;

    for (let attempt = 0; attempt < 6; attempt += 1) {
      // Park outside the chart so entering it is a genuine crossing.
      await this.page.mouse.move(box.x + box.width * 0.5, Math.max(1, box.y - 20));
      await this.page.waitForTimeout(20);

      // Approach from the far side of the target; the extreme edges are dead
      // zones and entering at the target itself gives the chart no movement.
      const entryFraction = attempt % 2 === 0 ? (fractionX > 0.5 ? 0.25 : 0.75) : 0.5;
      await this.page.mouse.move(
        box.x + box.width * entryFraction,
        box.y + box.height * 0.45,
        { steps: 4 },
      );
      await this.page.mouse.move(targetX, targetY, { steps: 12 });
      await this.page.waitForTimeout(80);

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
    await this.page.waitForTimeout(60);
  }

  // ── introspection ────────────────────────────────────────────────────

  chartState(): Promise<ChartState> {
    return this.page.evaluate(() => window.__traderapp!.chart() as ChartState);
  }

  /** What a mini chart actually drew. Null when the column is not rendered. */
  miniChartState(timeframe: string): Promise<ChartState | null> {
    return this.page.evaluate(
      (tf) => window.__traderapp!.miniChart(tf) as ChartState | null,
      timeframe,
    );
  }

  async waitForMiniCharts(): Promise<void> {
    await this.page.waitForFunction(
      () =>
        (['1m', '5m'] as const).every(
          (tf) => ((window.__traderapp?.miniChart(tf) as { barCount?: number } | null)?.barCount ?? 0) > 0,
        ),
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
