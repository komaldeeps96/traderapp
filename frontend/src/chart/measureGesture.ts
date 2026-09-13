import type { IChartApi, ISeriesApi } from 'lightweight-charts';

import type { Timeframe, WireBar } from '@/types/protocol';

import { measureStats, type MeasurePoint, type MeasureTool } from './measure';

export interface MeasureTarget {
  container: HTMLElement;
  chart: IChartApi;
  candles: ISeriesApi<'Candlestick'>;
  tool: MeasureTool;
  bars: () => readonly WireBar[];
  timeframe: () => Timeframe;
}

/**
 * The measure drag. While on, the drag gesture is borrowed from the chart —
 * panning and wheel-zoom are suspended so a drag selects a region instead of
 * scrolling one — and given back the moment the mode ends.
 */
export class MeasureGesture {
  private on = false;
  private anchor: MeasurePoint | null = null;

  constructor(private readonly target: MeasureTarget) {}

  get active(): boolean {
    return this.on;
  }

  set(on: boolean): void {
    if (this.on === on) return;
    this.on = on;
    const { chart, container } = this.target;
    chart.applyOptions({ handleScroll: !on, handleScale: !on });
    container.style.cursor = on ? 'crosshair' : '';
    if (on) {
      container.addEventListener('pointerdown', this.onDown);
      container.addEventListener('pointermove', this.onMove);
      container.addEventListener('pointerup', this.onUp);
    } else {
      container.removeEventListener('pointerdown', this.onDown);
      container.removeEventListener('pointermove', this.onMove);
      container.removeEventListener('pointerup', this.onUp);
      this.anchor = null;
      this.target.tool.clear();
    }
  }

  private readonly onDown = (event: PointerEvent): void => {
    const point = this.pointAt(event);
    if (!point) return;
    this.anchor = point;
    this.target.tool.clear();
    (event.target as Element | null)?.setPointerCapture?.(event.pointerId);
  };

  private readonly onMove = (event: PointerEvent): void => {
    if (!this.anchor) return;
    const point = this.pointAt(event);
    if (!point) return;
    this.target.tool.setSelection(
      this.anchor,
      point,
      measureStats(this.target.bars(), this.target.timeframe(), this.anchor, point),
    );
  };

  private readonly onUp = (): void => {
    // The selection stays painted after release; the next drag replaces it.
    this.anchor = null;
  };

  /**
   * The bar and price under the pointer. The bar index is snapped to a real
   * bar — a measurement over whitespace counts bars that exist — while the
   * price is left exactly where the pointer put it.
   */
  private pointAt(event: PointerEvent): MeasurePoint | null {
    const bars = this.target.bars();
    if (!bars.length) return null;
    const rect = this.target.container.getBoundingClientRect();
    const logical = this.target.chart.timeScale().coordinateToLogical(event.clientX - rect.left);
    const price = this.target.candles.coordinateToPrice(event.clientY - rect.top);
    if (logical === null || price === null) return null;
    const index = Math.min(Math.max(Math.round(logical), 0), bars.length - 1);
    const bar = bars[index];
    if (!bar) return null;
    return { index, time: bar.t, price };
  }
}
