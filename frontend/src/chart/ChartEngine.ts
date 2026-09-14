/**
 * A framework-free wrapper around lightweight-charts.
 *
 * React never owns bars: they arrive by the thousand and the newest changes
 * every second, so they go straight to the canvas and React renders only the
 * small derived readouts.
 *
 * **Time axis.** lightweight-charts positions bars by *logical index* — every
 * distinct timestamp across every series, visible or not, occupies a slot. A
 * hidden series still holding last timeframe's timestamps inserts phantom gaps,
 * so data has to be cleared or the series removed. `reconcileSeries` does that
 * on every snapshot.
 */

import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type LogicalRange,
  type SeriesOptionsCommon,
  type UTCTimestamp,
} from 'lightweight-charts';

import { formatAxisTime, formatBarTime, formatCompact, priceDecimals } from '@/lib/format';
import {
  formatCountdown,
  hasCandleCountdown,
  isCandleClosing,
  secondsToCandleClose,
} from '@/lib/session';
import type { LevelStyle } from '@/store/selectors';
import { indicatorLabel, type IndicatorSpec, type SeriesMap, type Timeframe, type WireBar } from '@/types/protocol';

import { BarData } from './barData';
import { BarCountdown } from './countdown';
import { DollarGrid } from './dollarGrid';
import { MeasureTool } from './measure';
import { MeasureGesture } from './measureGesture';
import type { MiniConfig } from './mini';
import { paletteFor, type ChartPalette, type ThemeName } from './theme';
import { ZoomMemory } from './zoomMemory';

const VOLUME_PANE_HEIGHT = 110;
const MACD_PANE_HEIGHT = 90;
const DEFAULT_VISIBLE_BARS = 240;
// Headroom above the highest bar and below the lowest, as a fraction of the
// price pane. The library's 0.2/0.1 leaves a conspicuous empty band on top.
const PRICE_SCALE_MARGINS = { top: 0.08, bottom: 0.08 };
// How often the clock is read. The label only turns over once a second; this
// is just often enough that it never shows a second that has already passed.
const COUNTDOWN_POLL_MS = 250;
// Axis and crosshair type. A mini chart drops a couple of points: its axis
// carries the same numbers in a third of the width.
const FONT_SIZE = { full: 11, mini: 9 } as const;
// The axis label's own height, which the countdown has to clear to sit under
// it. The library sizes it from the font, so this tracks the font too.
const AXIS_LABEL_HEIGHT = (fontSize: number) => Math.round(fontSize * 1.7);
// One scroll click, as a fraction of the visible width.
const NAV_STEP = 0.1;
// Width multiplier for one zoom-in click; zooming out applies its
// reciprocal, so the two are exact inverses.
const ZOOM_FACTOR = 0.8;

export interface ChartEngineOptions {
  container: HTMLElement;
  theme: ThemeName;
  onCrosshairMove?: (time: number | null) => void;
  onVisibleRangeChange?: () => void;
  /**
   * Persist the visible bar count under `{zoomSlot}:{timeframe}` and restore
   * it whenever a snapshot resets the view, so a terminal restart keeps the
   * zoom that was dialled in. Absent, the view always opens at the default.
   */
  zoomSlot?: string;
  /**
   * Run as a mini chart: only the listed indicators, no dollar gridlines, a
   * shorter volume pane and a tighter frame. See `chart/mini.ts`.
   */
  mini?: MiniConfig;
}

interface SnapshotInput {
  bars: WireBar[];
  series: SeriesMap;
  specs: IndicatorSpec[];
  timeframe: Timeframe;
  visibility: Record<string, boolean>;
  /** True when the symbol or timeframe changed, so the view should reset. */
  resetView: boolean;
}

const LINE_STYLES = {
  solid: LineStyle.Solid,
  dashed: LineStyle.Dashed,
  dotted: LineStyle.Dotted,
} as const;

/** Report a sub-pane series for the test surface, or null when absent. */
function describe(series: ISeriesApi<'Histogram'> | null) {
  if (!series) return null;
  const options = series.options();
  return { axisLabel: options.lastValueVisible, title: options.title };
}

export class ChartEngine {
  private chart: IChartApi;
  private candles: ISeriesApi<'Candlestick'>;
  private extendedHours: ISeriesApi<'Area'>;
  private volume: ISeriesApi<'Histogram'> | null = null;
  private macdLine: ISeriesApi<'Line'> | null = null;
  private macdSignal: ISeriesApi<'Line'> | null = null;
  private macdHist: ISeriesApi<'Histogram'> | null = null;
  private indicatorSeries = new Map<string, ISeriesApi<'Line'>>();
  private readonly dollars: DollarGrid;
  private athLine: IPriceLine | null = null;
  private athPrice: number | null = null;

  private readonly data = new BarData();
  private specs: IndicatorSpec[] = [];
  private timeframe: Timeframe = '10s';
  private readonly zoom: ZoomMemory;
  /** Specs streamed for the readout strip but never painted. */
  private readoutIds = new Set<string>();
  private theme: ThemeName;
  private palette: ChartPalette;
  private readonly measure = new MeasureTool();
  private readonly measureGesture: MeasureGesture;
  private levelStyles: Record<string, LevelStyle> = {};
  /** Levels currently giving up their axis label to the price. */
  private readonly crowded = new Set<string>();
  private readonly countdown = new BarCountdown();
  private countdownTimer: ReturnType<typeof setInterval> | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private destroyed = false;
  private readonly mini: MiniConfig | null;
  /** Allowed indicator ids on a mini chart; null on the full chart. */
  private readonly include: ReadonlySet<string> | null;

  constructor(private readonly options: ChartEngineOptions) {
    this.theme = options.theme;
    this.palette = paletteFor(options.theme);
    this.mini = options.mini ?? null;
    this.include = options.mini ? new Set(options.mini.include) : null;

    this.chart = createChart(options.container, this.chartOptions());

    this.extendedHours = this.chart.addSeries(
      AreaSeries,
      {
        // Its own hidden scale, pinned to 0..1, so the wash fills the full
        // height without ever influencing the price scale.
        priceScaleId: 'extended-hours',
        lineColor: 'rgba(0,0,0,0)',
        lineWidth: 1,
        topColor: this.palette.extendedHours,
        bottomColor: this.palette.extendedHours,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 1 } }),
      },
      0,
    );
    this.extendedHours.priceScale().applyOptions({ scaleMargins: { top: 0, bottom: 0 } });

    this.candles = this.chart.addSeries(
      CandlestickSeries,
      {
        upColor: this.palette.up,
        downColor: this.palette.down,
        wickUpColor: this.palette.up,
        wickDownColor: this.palette.down,
        borderVisible: false,
      },
      0,
    );

    this.candles.attachPrimitive(this.measure);
    // Rides the same series so it shares the price scale the last-value label
    // is drawn on, which is what lets it sit directly underneath.
    this.candles.attachPrimitive(this.countdown);
    this.dollars = new DollarGrid(this.candles);
    this.zoom = new ZoomMemory(options.zoomSlot);
    this.measureGesture = new MeasureGesture({
      container: options.container,
      chart: this.chart,
      candles: this.candles,
      tool: this.measure,
      bars: () => this.data.bars,
      timeframe: () => this.timeframe,
    });
    this.applyCountdownColors();
    this.countdownTimer = setInterval(() => {
      this.tickCountdown();
      // Zooming the price scale moves the gap between the price label and a
      // level without any new bar arriving, so this is re-checked on the
      // same beat. It only reaches the chart when the overlap changes.
      this.yieldAxisToPrice();
    }, COUNTDOWN_POLL_MS);

    this.chart.subscribeCrosshairMove((param) => {
      const time = param.time === undefined || param.point === undefined ? null : Number(param.time);
      this.options.onCrosshairMove?.(time);
    });

    if (options.onVisibleRangeChange || options.zoomSlot) {
      this.chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
        options.onVisibleRangeChange?.();
        if (this.data.count) {
          this.zoom.remember(this.timeframe, () => this.timeScale.getVisibleLogicalRange());
        }
      });
    }

    this.observeResize();
  }

  // ── lifecycle ────────────────────────────────────────────────────────

  private chartOptions() {
    const theme = this.themeOptions();
    const formatters = this.formatterOptions();
    return {
      autoSize: true,
      layout: {
        ...theme.layout,
        fontFamily:
          "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        fontSize: this.fontSize,
      },
      grid: theme.grid,
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { ...theme.crosshair.vertLine, width: 1 as const, style: LineStyle.Dashed },
        horzLine: { ...theme.crosshair.horzLine, width: 1 as const, style: LineStyle.Dashed },
      },
      // Both scales stay visible on a mini chart — a price without an axis is
      // a shape, not a level — but the price scale gives back the width it
      // reserves for a full chart's key-level tags, which a mini has none of.
      rightPriceScale: {
        ...theme.rightPriceScale,
        autoScale: true,
        minimumWidth: this.mini ? 44 : 64,
        // The library reserves a fifth of the pane above the highest bar,
        // which on a chart this dense is a band of empty surface where the
        // action should be. Trimmed to a margin that still keeps a breakout
        // off the ceiling.
        scaleMargins: PRICE_SCALE_MARGINS,
      },
      timeScale: {
        ...theme.timeScale,
        ...formatters.timeScale,
        timeVisible: true,
        rightOffset: this.mini ? 1 : 4,
      },
      localization: formatters.localization,
    };
  }

  /**
   * Colours only. Re-applying the rest resets the right offset and the price
   * scale's auto-scaling, which scrolls a chart read back in time to its live
   * edge and undoes a manual vertical zoom.
   */
  private themeOptions() {
    const palette = this.palette;
    return {
      layout: {
        background: { type: ColorType.Solid, color: palette.surface },
        textColor: palette.textMuted,
        panes: { separatorColor: palette.border, separatorHoverColor: palette.grid },
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      crosshair: {
        vertLine: { color: palette.crosshair, labelBackgroundColor: palette.crosshairLabel },
        horzLine: { color: palette.crosshair, labelBackgroundColor: palette.crosshairLabel },
      },
      rightPriceScale: { borderColor: palette.border },
      timeScale: { borderColor: palette.border },
    };
  }

  /** What depends on the timeframe: the axis and crosshair time labels. */
  private formatterOptions() {
    return {
      timeScale: {
        secondsVisible: this.timeframe === '10s',
        tickMarkFormatter: (time: UTCTimestamp) => formatAxisTime(Number(time), this.timeframe),
      },
      localization: {
        timeFormatter: (time: UTCTimestamp) => formatBarTime(Number(time), this.timeframe),
      },
    };
  }

  private observeResize(): void {
    if (typeof ResizeObserver === 'undefined') return;
    // autoSize handles most cases, but a pane resize during a hidden tab can
    // leave the canvas stale; this nudges it back. The library also rescales
    // panes in proportion on a resize, and the sub-panes are fixed heights.
    this.resizeObserver = new ResizeObserver(() => {
      if (this.destroyed) return;
      this.chart.applyOptions({});
      this.applyPaneHeights();
    });
    this.resizeObserver.observe(this.options.container);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    if (this.countdownTimer !== null) clearInterval(this.countdownTimer);
    this.countdownTimer = null;
    this.zoom.dispose();
    this.setMeasureMode(false);
    this.indicatorSeries.clear();
    this.data.clear();
    this.chart.remove();
  }

  setTheme(theme: ThemeName): void {
    this.theme = theme;
    this.palette = paletteFor(theme);
    this.chart.applyOptions(this.themeOptions());
    this.candles.applyOptions({
      upColor: this.palette.up,
      downColor: this.palette.down,
      wickUpColor: this.palette.up,
      wickDownColor: this.palette.down,
    });
    this.extendedHours.applyOptions({
      topColor: this.palette.extendedHours,
      bottomColor: this.palette.extendedHours,
    });
    for (const spec of this.specs) {
      const series = this.indicatorSeries.get(spec.id);
      series?.applyOptions({ color: this.colorFor(spec) });
    }
    const macdSpec = this.specs.find((spec) => spec.pane === 'macd');
    if (macdSpec) {
      this.macdLine?.applyOptions({ color: this.colorFor(macdSpec) });
      this.macdSignal?.applyOptions({ color: this.signalColor() });
    }
    this.applyCountdownColors();
    // Redrawn at the same price in the new colour; setAllTimeHigh skips an
    // unchanged price.
    const ath = this.athPrice;
    this.athPrice = null;
    this.setAllTimeHigh(ath);
    if (this.data.count) {
      this.renderPanes();
      this.renderDollarLines();
    }
  }

  private colorFor(spec: IndicatorSpec): string {
    return this.theme === 'dark' ? spec.color_dark : spec.color;
  }

  /**
   * The axis font size, in one place.
   *
   * The chart options that set it and the two places deriving the label height
   * from it must agree; disagreement is silent, the chip just drifts off its
   * label.
   */
  private get fontSize(): number {
    return this.mini ? FONT_SIZE.mini : FONT_SIZE.full;
  }

  private get axisLabelHeight(): number {
    return AXIS_LABEL_HEIGHT(this.fontSize);
  }

  // ── bar countdown ────────────────────────────────────────────────────

  private applyCountdownColors(): void {
    this.countdown.setColors({
      background: this.palette.countdown,
      text: this.palette.countdownText,
      closing: this.palette.countdownClosing,
      closingText: this.palette.countdownClosingText,
    });
  }

  /**
   * Park the countdown under the last-price label.
   *
   * Anchored to the newest bar's close, which is what the last-value label
   * tracks, so the two move together as the scale rescales. With no bars, or on
   * a timeframe whose candle does not close within the day, it goes away.
   */
  private tickCountdown(): void {
    if (this.destroyed) return;
    const last = this.lastBar();
    if (!last || !hasCandleCountdown(this.timeframe)) {
      this.countdown.set(null);
      return;
    }

    const remaining = secondsToCandleClose(this.timeframe, Date.now() / 1000);
    this.countdown.set({
      price: last.c,
      text: formatCountdown(this.timeframe, remaining),
      closing: isCandleClosing(this.timeframe, remaining),
      labelHeight: this.axisLabelHeight,
    });
  }

  // ── data ─────────────────────────────────────────────────────────────

  applySnapshot(input: SnapshotInput): void {
    // A repeat snapshot is a background backfill: it typically prepends
    // history, which shifts every logical index. The viewport is restored by
    // shifting the logical range by however far the old first bar moved —
    // exact for prepends and appends alike, and it keeps the right-edge
    // whitespace that a time-based restore would clamp away.
    const keepLogical = input.resetView ? null : this.timeScale.getVisibleLogicalRange();
    const anchorTime = this.data.bars[0]?.t;

    this.specs = input.specs;
    this.timeframe = input.timeframe;
    this.data.load(input.bars);

    // Timeframe-dependent formatters have to be reapplied before data lands,
    // or the axis briefly labels 1-minute bars as dates.
    this.chart.applyOptions(this.formatterOptions());

    this.reconcileSeries(input.specs, input.timeframe, input.visibility);
    this.applyPricePrecision();
    this.renderCandles();
    this.renderPanes();
    this.renderIndicators(input.series);
    this.renderDollarLines();
    // Rebuilt series come back in their configured colours; restyled here, in
    // the same frame, rather than a React effect later.
    this.setLevelStyles(this.levelStyles);
    this.tickCountdown();

    if (input.resetView) {
      // A measurement is a statement about one symbol on one timeframe;
      // carried across a switch it would be quietly wrong. So is a manual
      // vertical zoom: a new chart starts auto-scaled.
      this.measure.clear();
      this.chart.priceScale('right').applyOptions({ autoScale: true });
      this.resetView(this.zoom.saved(this.timeframe));
    } else if (keepLogical) {
      const shift = anchorTime !== undefined ? this.data.indexOf(anchorTime) : 0;
      if (shift === undefined) {
        // The window moved past the old first bar — a laptop waking overnight —
        // so the old range means nothing against the new data.
        this.resetView(this.zoom.saved(this.timeframe));
      } else {
        this.timeScale.setVisibleLogicalRange({
          from: keepLogical.from + shift,
          to: keepLogical.to + shift,
        });
      }
    }
  }

  /**
   * Match the price scale to the ticker's magnitude: two decimals is right for
   * a $300 stock and useless at $0.37, where every level rounds to the same
   * number.
   */
  private applyPricePrecision(): void {
    const last = this.lastBar();
    if (!last) return;

    const precision = priceDecimals(last.c);
    const priceFormat = {
      type: 'price' as const,
      precision,
      minMove: Number((10 ** -precision).toFixed(precision)),
    };

    this.candles.applyOptions({ priceFormat });
    for (const series of this.indicatorSeries.values()) {
      series.applyOptions({ priceFormat });
    }
  }

  /**
   * Colour and weight the key levels.
   *
   * Reapplied after every snapshot, because rebuilding the series resets them
   * to their configured defaults.
   */
  setLevelStyles(styles: Record<string, LevelStyle>): void {
    this.levelStyles = styles;
    for (const [id, style] of Object.entries(styles)) {
      const series = this.indicatorSeries.get(id);
      if (!series) continue;
      series.applyOptions({
        color: style.color,
        lineWidth: style.lineWidth,
        lastValueVisible: style.labelVisible,
        title: style.labelVisible ? style.title : '',
      });
    }
    this.crowded.clear();
    this.yieldAxisToPrice();
  }

  /**
   * Give the price and its countdown right of way on the axis.
   *
   * A level within a label's height of the last trade puts three boxes in the
   * same few pixels, and the library shuffles them apart — pushing the price
   * label off the price and the countdown with it. The level's line and its
   * in-chart name stay readable without its axis box, so the colliding level
   * gives that up until price moves off. Only the ones that actually overlap.
   */
  private yieldAxisToPrice(): void {
    const last = this.lastBar();
    if (!last) return;
    const priceY = this.candles.priceToCoordinate(last.c);
    if (priceY === null) return;

    // The price label is centred on the price; the countdown sits directly
    // below it. A level's own box overlaps that pair anywhere in this span.
    const height = this.axisLabelHeight;

    for (const [id, style] of Object.entries(this.levelStyles)) {
      const series = this.indicatorSeries.get(id);
      if (!series || !style.labelVisible) continue;

      const value = this.data.latestValue(id);
      const y = value === undefined ? null : series.priceToCoordinate(value);
      const overlaps = y !== null && y > priceY - height && y < priceY + 2 * height;
      if (overlaps === this.crowded.has(id)) continue;

      if (overlaps) this.crowded.add(id);
      else this.crowded.delete(id);
      series.applyOptions({
        lastValueVisible: !overlaps,
        title: overlaps ? '' : style.title,
      });
    }
  }

  /**
   * Blank the chart immediately, the moment the user switches symbols: the old
   * instrument's candles must not sit under the new ticker's name while its
   * history loads.
   */
  clear(): void {
    this.data.clear();
    this.setAllTimeHigh(null);
    this.countdown.set(null);
    this.dollars.clear();

    this.candles.setData([]);
    this.extendedHours.setData([]);
    this.volume?.setData([]);
    this.macdLine?.setData([]);
    this.macdSignal?.setData([]);
    this.macdHist?.setData([]);
    for (const series of this.indicatorSeries.values()) series.setData([]);
  }

  applyBar(bar: WireBar, values: Record<string, number>): void {
    if (!this.data.upsert(bar)) return;

    const time = bar.t as UTCTimestamp;
    this.candles.update({ time, open: bar.o, high: bar.h, low: bar.l, close: bar.c });
    this.extendedHours.update({ time, value: bar.x ? 1 : 0 });
    this.volume?.update({ time, value: bar.v, color: this.volumeColor(bar) });

    for (const [id, value] of Object.entries(values)) {
      // A non-finite value poisons a series: every later paint of its pane
      // throws inside the library and the chart goes blank.
      if (!Number.isFinite(value)) continue;
      if (id.startsWith('macd')) {
        this.updateMacdPoint(id, time, value);
        this.data.remember(id, bar.t, value);
        continue;
      }
      const series = this.indicatorSeries.get(id);
      if (!series) {
        if (this.readoutIds.has(id)) this.data.remember(id, bar.t, value);
        continue;
      }
      series.update({ time, value });
      this.data.remember(id, bar.t, value);
    }

    // A runner breaking to new highs grows the dollar grid as it goes.
    if (this.dollars.outgrown(bar)) {
      this.renderDollarLines();
    }

    this.tickCountdown();
    this.yieldAxisToPrice();
  }

  private updateMacdPoint(id: string, time: UTCTimestamp, value: number): void {
    if (id === 'macd') this.macdLine?.update({ time, value });
    else if (id === 'macd_signal') this.macdSignal?.update({ time, value });
    else if (id === 'macd_hist') {
      this.macdHist?.update({ time, value, color: this.histColor(value) });
    }
  }

  private histColor(value: number): string {
    return value >= 0 ? this.palette.upFill : this.palette.downFill;
  }

  private renderCandles(): void {
    this.candles.setData(
      this.data.bars.map((bar) => ({
        time: bar.t as UTCTimestamp,
        open: bar.o,
        high: bar.h,
        low: bar.l,
        close: bar.c,
      })),
    );
    this.extendedHours.setData(
      this.data.bars.map((bar) => ({ time: bar.t as UTCTimestamp, value: bar.x ? 1 : 0 })),
    );
  }

  private renderPanes(): void {
    const points = this.data.bars.map((bar) => ({
      time: bar.t as UTCTimestamp,
      color: this.volumeColor(bar),
    }));
    this.volume?.setData(points.map((point, i) => ({ ...point, value: this.data.bars[i]!.v })));
  }

  private renderIndicators(series: SeriesMap): void {
    this.data.clearSeries();
    for (const [id, chartSeries] of this.indicatorSeries) {
      const points = series[id] ?? [];
      chartSeries.setData(points.map(([time, value]) => ({ time: time as UTCTimestamp, value })));
      this.data.setSeries(id, points);
    }
    for (const id of this.readoutIds) {
      this.data.setSeries(id, series[id] ?? []);
    }
    this.renderMacd(series);
  }

  private renderMacd(series: SeriesMap): void {
    if (!this.macdLine) return;
    const toLine = (points: [number, number][] | undefined) =>
      (points ?? []).map(([time, value]) => ({ time: time as UTCTimestamp, value }));

    this.macdLine.setData(toLine(series['macd']));
    this.macdSignal?.setData(toLine(series['macd_signal']));
    this.macdHist?.setData(
      (series['macd_hist'] ?? []).map(([time, value]) => ({
        time: time as UTCTimestamp,
        value,
        color: this.histColor(value),
      })),
    );
    for (const id of ['macd', 'macd_signal', 'macd_hist']) {
      this.data.setSeries(id, series[id] ?? []);
    }
  }

  /**
   * Draw the all-time high as a labelled price line.
   *
   * A price line rather than a series: the value is one number from
   * TradingView, and a price line neither expands the autoscale (an ATH ten
   * times above price must not flatten the chart) nor needs reconciliation.
   */
  setAllTimeHigh(price: number | null): void {
    if (price === this.athPrice) return;
    this.athPrice = price;
    if (this.athLine) {
      this.candles.removePriceLine(this.athLine);
      this.athLine = null;
    }
    if (price == null || price <= 0 || this.mini) return;
    this.athLine = this.candles.createPriceLine({
      price,
      color: this.palette.down,
      lineWidth: 1,
      lineStyle: LineStyle.LargeDashed,
      axisLabelVisible: true,
      title: 'ATH',
    });
  }

  athLevel(): number | null {
    return this.athPrice;
  }

  private renderDollarLines(): void {
    this.dollars.draw(this.data.bars, this.timeframe, this.palette, this.mini !== null);
  }

  private volumeColor(bar: WireBar): string {
    return bar.c >= bar.o ? this.palette.upFill : this.palette.downFill;
  }

  /**
   * Create, update, or drop series so exactly the indicators active on this
   * timeframe exist. Dropping matters: a leftover series keeps its timestamps
   * on the shared logical axis and tears gaps into the chart.
   */
  private reconcileSeries(
    specs: IndicatorSpec[],
    timeframe: Timeframe,
    visibility: Record<string, boolean>,
  ): void {
    // The allow-list is the whole of what makes a mini chart minimal. Both
    // the MACD pane and every key level are built from this one map, so
    // filtering it here removes them and nothing below has to know.
    const wanted = new Map(
      specs
        .filter((spec) => spec.timeframes[timeframe] !== undefined)
        .filter((spec) => this.include === null || this.include.has(spec.id))
        .map((spec) => [spec.id, spec]),
    );

    // Readout-only specs get values recorded for the strip's lookups but no
    // chart series — a volume ratio painted on a price pane would crawl
    // along zero and drag the autoscale with it.
    this.readoutIds = new Set(
      [...wanted.values()].filter((spec) => spec.readout_only).map((spec) => spec.id),
    );
    for (const id of this.readoutIds) wanted.delete(id);

    for (const [id, series] of [...this.indicatorSeries]) {
      if (!wanted.has(id)) {
        this.chart.removeSeries(series);
        this.indicatorSeries.delete(id);
        this.data.dropSeries(id);
      }
    }

    // Sub-panes take consecutive indices after the price pane, in a fixed
    // order, so each keeps its place as others come and go per timeframe.
    let nextPane = 1;
    const volumeSpec = wanted.get('volume');
    this.volume = this.ensureHistogram(this.volume, volumeSpec, volumeSpec ? nextPane : 0);
    if (volumeSpec) nextPane += 1;
    const macdSpec = [...wanted.values()].find((spec) => spec.pane === 'macd');
    this.ensureMacd(macdSpec, macdSpec ? nextPane : 0, visibility);

    for (const [id, spec] of wanted) {
      if (spec.pane !== 'price') continue;
      let series = this.indicatorSeries.get(id);
      if (!series) {
        series = this.chart.addSeries(LineSeries, this.lineOptions(spec, visibility), 0);
        this.indicatorSeries.set(id, series);
      } else {
        series.applyOptions(this.lineOptions(spec, visibility));
      }
    }

    this.applyPaneHeights();
  }

  /**
   * The MACD pane: line, signal, histogram. Colours follow the platform
   * convention — blue MACD, orange signal, histogram in the candle polarity.
   */
  private ensureMacd(
    spec: IndicatorSpec | undefined,
    pane: number,
    visibility: Record<string, boolean>,
  ): void {
    if (!spec) {
      if (this.macdLine) this.chart.removeSeries(this.macdLine);
      if (this.macdSignal) this.chart.removeSeries(this.macdSignal);
      if (this.macdHist) this.chart.removeSeries(this.macdHist);
      this.macdLine = this.macdSignal = this.macdHist = null;
      return;
    }
    const visible = visibility[spec.id] ?? true;
    if (this.macdLine) {
      this.macdLine.applyOptions({ color: this.colorFor(spec), visible });
      this.macdSignal?.applyOptions({ color: this.signalColor(), visible });
      this.macdHist?.applyOptions({ visible });
      return;
    }

    const common = {
      priceLineVisible: false,
      crosshairMarkerVisible: false,
      priceFormat: { type: 'price' as const, precision: 4, minMove: 0.0001 },
    };
    this.macdHist = this.chart.addSeries(
      HistogramSeries,
      { ...common, lastValueVisible: false, title: '', visible },
      pane,
    );
    this.macdLine = this.chart.addSeries(
      LineSeries,
      {
        ...common,
        color: this.colorFor(spec),
        lineWidth: 1,
        lastValueVisible: true,
        title: '',
        visible,
      },
      pane,
    );
    this.macdSignal = this.chart.addSeries(
      LineSeries,
      {
        ...common,
        color: this.signalColor(),
        lineWidth: 1,
        lastValueVisible: false,
        title: '',
        visible,
      },
      pane,
    );
  }

  private signalColor(): string {
    return this.theme === 'dark' ? '#d95926' : '#eb6834';
  }

  private lineOptions(spec: IndicatorSpec, visibility: Record<string, boolean>) {
    return {
      color: this.colorFor(spec),
      lineWidth: spec.line_width as 1 | 2 | 3 | 4,
      lineStyle: LINE_STYLES[spec.line_style],
      priceLineVisible: spec.price_line,
      lastValueVisible: spec.last_value,
      // The 10s chart renames the minute EMAs (EMA 9 -> EMA 54); the axis tag
      // must agree with the sidebar chip.
      title: spec.last_value ? indicatorLabel(spec, this.timeframe) : '',
      visible: visibility[spec.id] ?? true,
      crosshairMarkerVisible: false,
      // Key levels can sit far outside the visible price range; letting them
      // drive autoscale would zoom the candles into a flat line.
      autoscaleInfoProvider: () => null,
    } satisfies Partial<SeriesOptionsCommon> & Record<string, unknown>;
  }

  private ensureHistogram(
    current: ISeriesApi<'Histogram'> | null,
    spec: IndicatorSpec | undefined,
    pane: number,
  ): ISeriesApi<'Histogram'> | null {
    if (!spec) {
      if (current) this.chart.removeSeries(current);
      return null;
    }
    if (current) return current;
    return this.chart.addSeries(
      HistogramSeries,
      {
        priceFormat: { type: 'custom', formatter: (v: number) => formatCompact(v), minMove: 1 },
        priceLineVisible: false,
        lastValueVisible: false,
        // No axis tag. It rides at the height of the last value, so on a
        // normal session it drifts into the middle of the pane and lands on
        // the zoom controls. The sidebar and the toolbar readout both carry
        // the number already.
        title: '',
      },
      pane,
    );
  }

  private applyPaneHeights(): void {
    const panes = this.chart.panes();
    const heights: number[] = [];
    if (this.volume) heights.push(this.mini?.volumePaneHeight ?? VOLUME_PANE_HEIGHT);
    if (this.macdLine) heights.push(MACD_PANE_HEIGHT);
    heights.forEach((height, i) => panes[i + 1]?.setHeight(height));
  }

  setIndicatorVisible(id: string, visible: boolean): void {
    this.indicatorSeries.get(id)?.applyOptions({ visible });
    if (id === 'volume') this.volume?.applyOptions({ visible });
    if (id === 'macd') {
      this.macdLine?.applyOptions({ visible });
      this.macdSignal?.applyOptions({ visible });
      this.macdHist?.applyOptions({ visible });
    }
  }

  // ── lookups ──────────────────────────────────────────────────────────

  barCount(): number {
    return this.data.count;
  }

  lastBar(): WireBar | null {
    return this.data.last();
  }

  sessionVolumeAt(time: number): number | null {
    return this.data.sessionVolumeAt(time);
  }

  barAt(time: number): WireBar | null {
    return this.data.at(time);
  }

  previousClose(time: number): number | null {
    return this.data.previousClose(time);
  }

  valuesAt(time: number): Record<string, number> {
    return this.data.valuesAt(time);
  }

  /** Every series' newest value. Once per snapshot: each is a scan. */
  latestValues(): Record<string, number> {
    return this.data.latestValues();
  }

  // ── navigation ───────────────────────────────────────────────────────

  private get timeScale() {
    return this.chart.timeScale();
  }

  /**
   * Scale the visible range about its centre. A factor below 1 zooms in.
   *
   * Multiplicative so zooming out undoes zooming in exactly: trimming a tenth
   * from both edges gives 0.8x and adding a tenth back gives 1.2x, leaving
   * every in-and-out pair 4% tighter than it started.
   */
  private scaleRange(factor: number): void {
    const range = this.timeScale.getVisibleLogicalRange();
    if (!range) return;
    const centre = (range.from + range.to) / 2;
    const half = ((range.to - range.from) * factor) / 2;
    this.timeScale.setVisibleLogicalRange({ from: centre - half, to: centre + half });
  }

  private pan(scale: number): void {
    const range = this.timeScale.getVisibleLogicalRange();
    if (!range) return;
    const shift = (range.to - range.from) * scale;
    this.timeScale.setVisibleLogicalRange({ from: range.from + shift, to: range.to + shift });
  }

  zoomIn(): void {
    this.scaleRange(ZOOM_FACTOR);
  }

  zoomOut(): void {
    this.scaleRange(1 / ZOOM_FACTOR);
  }

  scrollLeft(): void {
    this.pan(-NAV_STEP);
  }

  scrollRight(): void {
    this.pan(NAV_STEP);
  }

  /**
   * Reframe to the latest bars. The Reset button calls this bare — reset
   * means the default width — while a snapshot's view reset passes the
   * persisted width back in, so a restart or symbol switch keeps the zoom.
   */
  resetView(visibleBars?: number): void {
    if (!this.data.bars.length) return;
    const visible = visibleBars ?? this.mini?.visibleBars ?? DEFAULT_VISIBLE_BARS;
    this.chart.priceScale('right').applyOptions({ autoScale: true });
    this.timeScale.setVisibleLogicalRange({
      from: Math.max(0, this.data.bars.length - visible),
      to: this.data.bars.length - 1,
    });
  }

  /** Toggle measure mode; see `MeasureGesture`. */
  setMeasureMode(on: boolean): void {
    this.measureGesture.set(on);
  }

  isMeasuring(): boolean {
    return this.measureGesture.active;
  }

  fitContent(): void {
    this.timeScale.fitContent();
  }

  visibleRange(): LogicalRange | null {
    return this.timeScale.getVisibleLogicalRange();
  }

  /**
   * Height of everything below the price pane: the sub-panes plus the time
   * axis. Anything floating over the price pane measures its offset from
   * this, so it keeps its place when a pane separator is dragged.
   */
  subPaneOffset(): number {
    try {
      const panes = this.chart.panes();
      let total = 0;
      for (let index = 1; index < panes.length; index += 1) {
        total += panes[index]?.getHeight() ?? 0;
      }
      return total + this.timeScale.height();
    } catch {
      // The chart has been disposed; a sensible default beats throwing.
      return VOLUME_PANE_HEIGHT + 30;
    }
  }

  // ── test surface ─────────────────────────────────────────────────────

  /**
   * A canvas cannot be asserted against from the DOM, so the engine exposes
   * what it drew. Playwright reads this to check that a series actually
   * received points and that visibility toggles landed.
   */
  inspect() {
    return {
      barCount: this.data.count,
      lastBar: this.lastBar(),
      timeframe: this.timeframe,
      theme: this.theme,
      paneCount: this.chart.panes().length,
      paneHeights: this.chart.panes().map((pane) => pane.getHeight()),
      // The height the sub-panes occupy — what the floating controls are
      // positioned above, and the only handle a test has on that.
      subPaneOffset: this.subPaneOffset(),
      // Painted on the canvas, so this is the only handle a browser test has.
      measure: {
        active: this.measureGesture.active,
        selection: this.measure.selection
          ? {
              bars: this.measure.selection.stats.bars,
              priceDelta: this.measure.selection.stats.priceDelta,
              percent: this.measure.selection.stats.percent,
              volume: this.measure.selection.stats.volume,
              direction: this.measure.selection.stats.direction,
            }
          : null,
      },
      seriesIds: [...this.indicatorSeries.keys()].sort(),
      pointCounts: this.data.pointCounts(),
      visible: Object.fromEntries(
        [...this.indicatorSeries].map(([id, series]) => [id, series.options().visible]),
      ),
      lineWidths: Object.fromEntries(
        [...this.indicatorSeries].map(([id, series]) => [id, series.options().lineWidth]),
      ),
      lineColors: Object.fromEntries(
        [...this.indicatorSeries].map(([id, series]) => [id, series.options().color]),
      ),
      axisLabels: Object.fromEntries(
        [...this.indicatorSeries].map(([id, series]) => [id, series.options().lastValueVisible]),
      ),
      visibleRange: this.visibleRange(),
      hasVolumePane: this.volume !== null,
      hasMacdPane: this.macdLine !== null,
      dollarLineCount: this.dollars.count,
      athLine: this.athPrice,
      // Levels that have stood down from the axis so the price label and its
      // countdown are not shuffled off the price.
      axisYieldedToPrice: [...this.crowded].sort(),
      // The countdown is painted into the price axis, so the DOM cannot be
      // asked whether it is there or what it says.
      countdown: this.countdown.state
        ? { text: this.countdown.state.text, closing: this.countdown.state.closing }
        : null,
      secondsVisible: this.timeframe === '10s',
      // The volume histogram lives outside `indicatorSeries`, so it needs
      // reporting separately — otherwise a test asking about it reads
      // `undefined` and quietly passes.
      paneSeries: {
        volume: describe(this.volume),
      },
    };
  }
}
