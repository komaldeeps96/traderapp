import { LineStyle, type IPriceLine, type ISeriesApi } from 'lightweight-charts';

import type { Timeframe, WireBar } from '@/types/protocol';

import type { ChartPalette } from './theme';

// Whole/half dollar gridlines cap out before they become wallpaper.
const MAX_DOLLAR_LINES = 28;
const INTRADAY_TIMEFRAMES: ReadonlySet<string> = new Set([
  '10s',
  '1m',
  '5m',
  '15m',
  '30m',
  '1h',
  '4h',
]);

export interface DollarLevels {
  prices: number[];
  /** The traded range the prices were drawn over. */
  low: number;
  high: number;
}

/**
 * Whole/half dollar prices over the traded range.
 *
 * Round numbers are where resistance parks, so they are drawn rather than
 * inferred. The step widens with the range so a high-priced or long-range
 * chart never turns into wallpaper.
 */
export function dollarLevels(bars: readonly WireBar[]): DollarLevels | null {
  let low = Infinity;
  let high = -Infinity;
  for (const bar of bars) {
    if (bar.l < low) low = bar.l;
    if (bar.h > high) high = bar.h;
  }
  if (!Number.isFinite(low) || !Number.isFinite(high)) return null;

  const pad = Math.max((high - low) * 0.05, 0.5);
  const from = Math.max(0, low - pad);
  const to = high + pad;

  let step = 0.5;
  while ((to - from) / step > MAX_DOLLAR_LINES) {
    step = step === 0.5 ? 1 : step === 1 ? 5 : step === 5 ? 10 : step * 10;
    if (step > 1000) return null;
  }

  const prices: number[] = [];
  for (let price = Math.ceil(from / step) * step; price <= to; price += step) {
    const rounded = Number(price.toFixed(2));
    if (rounded > 0) prices.push(rounded);
  }
  return { prices, low, high };
}

/** The dollar gridlines on one chart's candle series. */
export class DollarGrid {
  private lines: IPriceLine[] = [];
  private range: { low: number; high: number } | null = null;

  constructor(private readonly series: ISeriesApi<'Candlestick'>) {}

  get count(): number {
    return this.lines.length;
  }

  /**
   * Redraw over `bars`: intraday timeframes only, and never on a mini chart,
   * where the grid would be denser than the candles it sits behind.
   */
  draw(bars: readonly WireBar[], timeframe: Timeframe, palette: ChartPalette, mini: boolean): void {
    this.clear();
    if (mini || !INTRADAY_TIMEFRAMES.has(timeframe)) return;
    const levels = dollarLevels(bars);
    if (!levels) return;

    for (const price of levels.prices) {
      const whole = Math.abs(price - Math.round(price)) < 1e-9;
      this.lines.push(
        this.series.createPriceLine({
          price,
          color: whole ? palette.wholeDollar : palette.halfDollar,
          lineWidth: 1,
          lineStyle: LineStyle.SparseDotted,
          axisLabelVisible: false,
          title: '',
        }),
      );
    }
    this.range = { low: levels.low, high: levels.high };
  }

  /** A bar outside the drawn range: a runner breaking to new highs grows the grid. */
  outgrown(bar: WireBar): boolean {
    return this.range !== null && (bar.h > this.range.high || bar.l < this.range.low);
  }

  clear(): void {
    for (const line of this.lines) this.series.removePriceLine(line);
    this.lines = [];
    this.range = null;
  }
}
