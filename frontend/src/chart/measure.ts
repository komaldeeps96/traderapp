/**
 * The measure tool: drag a region, read what happened inside it.
 *
 * Answers the three questions a trader asks of a move in one gesture — how
 * far (price change and percent), how fast (bars and clock time), and on how
 * much (cumulative volume). The last one is the tell this cohort trades on:
 * a 5% pop on 40K shares and a 5% pop on 2M shares are different events.
 *
 * Drawn as a series primitive like the confluence bands, so it needs no extra
 * DOM and repaints itself whenever the chart does. Anchors are stored as
 * bar time + price rather than pixels or logical indices: pixels go stale on
 * every pan, and logical indices shift when a history backfill prepends bars
 * mid-measurement. Times survive both.
 */

import type {
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts';

import { formatCompact, formatPercent, priceDecimals } from '@/lib/format';
import { timeframeSeconds } from '@/lib/session';
import type { Timeframe, WireBar } from '@/types/protocol';

/** A measurement anchor: a bar (by index and time) and an unsnapped price. */
export interface MeasurePoint {
  index: number;
  time: number;
  price: number;
}

export interface MeasureStats {
  priceDelta: number;
  percent: number;
  /** Bar distance between the anchors, the way TradingView counts it. */
  bars: number;
  seconds: number;
  volume: number;
  direction: 'up' | 'down';
}

// TradingView's measure colours, kept on both themes: the tool is a copy of
// a gesture readers already know, and half its legibility is the convention.
const UP_COLOR = '#2962ff';
const DOWN_COLOR = '#f23645';
const FILL_ALPHA = '26'; // ~15%
const LABEL_PAD = 6;
const LABEL_GAP = 8;
const LINE_HEIGHT = 15;
const ARROW_SIZE = 5;

export function measureStats(
  bars: readonly WireBar[],
  timeframe: Timeframe,
  from: MeasurePoint,
  to: MeasurePoint,
): MeasureStats {
  const barSpan = Math.abs(to.index - from.index);
  const lo = Math.min(from.index, to.index);
  const hi = Math.max(from.index, to.index);
  let volume = 0;
  for (let i = lo; i <= hi && i < bars.length; i += 1) volume += bars[i]?.v ?? 0;
  const priceDelta = to.price - from.price;
  return {
    priceDelta,
    percent: from.price !== 0 ? (priceDelta / from.price) * 100 : 0,
    bars: barSpan,
    seconds: barSpan * timeframeSeconds(timeframe),
    volume,
    direction: priceDelta >= 0 ? 'up' : 'down',
  };
}

/** "9m 50s" — clock time for the bar span, in the largest two units. */
export function formatDuration(totalSeconds: number): string {
  const units: [string, number][] = [
    ['d', 86_400],
    ['h', 3_600],
    ['m', 60],
    ['s', 1],
  ];
  const parts: string[] = [];
  let rest = Math.round(totalSeconds);
  for (const [label, size] of units) {
    if (rest >= size) {
      parts.push(`${Math.floor(rest / size)}${label}`);
      rest %= size;
    }
    if (parts.length === 2) break;
  }
  return parts.length ? parts.join(' ') : '0s';
}

interface Selection {
  from: MeasurePoint;
  to: MeasurePoint;
  stats: MeasureStats;
}

class MeasureRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly tool: MeasureTool) {}

  draw(target: {
    useBitmapCoordinateSpace: (
      fn: (scope: {
        context: CanvasRenderingContext2D;
        bitmapSize: { width: number; height: number };
        horizontalPixelRatio: number;
        verticalPixelRatio: number;
      }) => void,
    ) => void;
  }): void {
    const { selection, series, chart } = this.tool;
    if (!selection || !series || !chart) return;

    const timeScale = chart.timeScale();
    const x1 = timeScale.timeToCoordinate(selection.from.time as Time);
    const x2 = timeScale.timeToCoordinate(selection.to.time as Time);
    const y1 = series.priceToCoordinate(selection.from.price);
    const y2 = series.priceToCoordinate(selection.to.price);
    if (x1 === null || x2 === null || y1 === null || y2 === null) return;

    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
      const { stats } = selection;
      const color = stats.direction === 'up' ? UP_COLOR : DOWN_COLOR;
      const left = Math.min(x1, x2) * hr;
      const right = Math.max(x1, x2) * hr;
      const top = Math.min(y1, y2) * vr;
      const bottom = Math.max(y1, y2) * vr;

      context.fillStyle = color + FILL_ALPHA;
      context.fillRect(left, top, right - left, bottom - top);

      context.strokeStyle = color;
      context.fillStyle = color;
      context.lineWidth = Math.max(1, Math.round(hr));
      const midY = (top + bottom) / 2;
      const midX = (left + right) / 2;
      const head = ARROW_SIZE * hr;

      // Horizontal arrow, pointing in the direction of the drag.
      drawArrow(context, x1 * hr, midY, x2 * hr, midY, head);
      // Vertical arrow, pointing from the anchor price to the current one.
      drawArrow(context, midX, y1 * vr, midX, y2 * vr, head);

      // The readout, above the region for a rise and below for a fall, the
      // way the eye continues the move — clamped into the pane either way.
      const lines = this.lines(stats, selection);
      const font = `${Math.round(11 * hr)}px ui-monospace, SFMono-Regular, Menlo, monospace`;
      context.font = font;
      const textWidth = Math.max(...lines.map((line) => context.measureText(line).width));
      const boxWidth = textWidth + LABEL_PAD * 2 * hr;
      const boxHeight = (lines.length * LINE_HEIGHT + LABEL_PAD) * vr;
      const boxX = clamp(midX - boxWidth / 2, 0, bitmapSize.width - boxWidth);
      const above = stats.direction === 'up';
      const boxY = clamp(
        above ? top - boxHeight - LABEL_GAP * vr : bottom + LABEL_GAP * vr,
        0,
        bitmapSize.height - boxHeight,
      );

      context.fillStyle = color;
      roundedRect(context, boxX, boxY, boxWidth, boxHeight, 3 * hr);
      context.fill();

      context.fillStyle = '#ffffff';
      context.textAlign = 'center';
      context.textBaseline = 'middle';
      lines.forEach((line, i) => {
        context.fillText(line, boxX + boxWidth / 2, boxY + (LABEL_PAD / 2 + (i + 0.5) * LINE_HEIGHT) * vr);
      });
    });
  }

  private lines(stats: MeasureStats, selection: Selection): string[] {
    const digits = priceDecimals(selection.from.price);
    const sign = stats.priceDelta >= 0 ? '+' : '';
    return [
      `${sign}${stats.priceDelta.toFixed(digits)} (${formatPercent(stats.percent)})`,
      `${stats.bars} bars · ${formatDuration(stats.seconds)}`,
      `Vol ${formatCompact(stats.volume, 1)}`,
    ];
  }
}

function drawArrow(
  context: CanvasRenderingContext2D,
  fromX: number,
  fromY: number,
  toX: number,
  toY: number,
  head: number,
): void {
  context.beginPath();
  context.moveTo(fromX, fromY);
  context.lineTo(toX, toY);
  context.stroke();

  const angle = Math.atan2(toY - fromY, toX - fromX);
  context.beginPath();
  context.moveTo(toX, toY);
  context.lineTo(toX - head * Math.cos(angle - Math.PI / 6), toY - head * Math.sin(angle - Math.PI / 6));
  context.lineTo(toX - head * Math.cos(angle + Math.PI / 6), toY - head * Math.sin(angle + Math.PI / 6));
  context.closePath();
  context.fill();
}

function roundedRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): void {
  context.beginPath();
  context.moveTo(x + radius, y);
  context.arcTo(x + width, y, x + width, y + height, radius);
  context.arcTo(x + width, y + height, x, y + height, radius);
  context.arcTo(x, y + height, x, y, radius);
  context.arcTo(x, y, x + width, y, radius);
  context.closePath();
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(Math.max(value, lo), Math.max(lo, hi));
}

class MeasurePaneView implements IPrimitivePaneView {
  constructor(private readonly tool: MeasureTool) {}

  zOrder() {
    // Over the candles: a measurement is a deliberate, temporary act and
    // wants to be read, unlike the bands living behind the price action.
    return 'top' as const;
  }

  renderer(): IPrimitivePaneRenderer {
    return new MeasureRenderer(this.tool);
  }
}

export class MeasureTool implements ISeriesPrimitive {
  series: ISeriesApi<SeriesType> | null = null;
  chart: SeriesAttachedParameter<Time, SeriesType>['chart'] | null = null;
  selection: Selection | null = null;

  private readonly views: readonly IPrimitivePaneView[] = [new MeasurePaneView(this)];
  private requestUpdate: (() => void) | null = null;

  attached(param: SeriesAttachedParameter<Time, SeriesType>): void {
    this.series = param.series;
    this.chart = param.chart;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.series = null;
    this.chart = null;
    this.requestUpdate = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }

  setSelection(from: MeasurePoint, to: MeasurePoint, stats: MeasureStats): void {
    this.selection = { from, to, stats };
    this.requestUpdate?.();
  }

  clear(): void {
    if (!this.selection) return;
    this.selection = null;
    this.requestUpdate?.();
  }
}
