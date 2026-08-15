/**
 * A framework-free wrapper around lightweight-charts.
 *
 * React never owns bars. Thousands of them arrive per snapshot and the newest
 * one changes every second, so they live here and go straight to the canvas;
 * React only renders the small derived readouts. That keeps re-renders off the
 * hot path entirely.
 *
 * TIME AXIS — the thing that bites
 * lightweight-charts positions bars by *logical index*: every distinct
 * timestamp across every series, visible or not, occupies a slot. A series
 * still holding last timeframe's timestamps therefore inserts phantom gaps
 * into the axis even while hidden. Hiding is not enough — data has to be
 * cleared or the series removed, which is what `reconcileSeries` does on every
 * snapshot.
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

import { ConfluenceBands, type PriceBand } from './bands';
import { BarCountdown } from './countdown';
import type { MiniConfig } from './mini';
import { paletteFor, type ChartPalette, type ThemeName } from './theme';

const VOLUME_PANE_HEIGHT = 110;
const TRADES_PANE_HEIGHT = 80;
const MACD_PANE_HEIGHT = 90;
const DEFAULT_VISIBLE_BARS = 240;
// Headroom above the highest bar and below the lowest, as a fraction of the
// price pane. The library's 0.2/0.1 leaves a conspicuous empty band on top.
const PRICE_SCALE_MARGINS = { top: 0.08, bottom: 0.08 };
// How often the clock is read. The label only turns over once a second; this
// is just often enough that it never shows a second that has already passed.
const COUNTDOWN_POLL_MS = 250;
// The axis label's own height, which the countdown has to clear to sit under
// it. The library sizes it from the font, so this tracks the font too.
const AXIS_LABEL_HEIGHT = (fontSize: number) => Math.round(fontSize * 1.7);
const NAV_STEP = 0.1;
// Whole/half dollar gridlines cap out before they become wallpaper.
const MAX_DOLLAR_LINES = 28;
const INTRADAY_TIMEFRAMES: ReadonlySet<string> = new Set(['10s', '1m', '5m', '15m', '1h']);

export interface ChartEngineOptions {
  container: HTMLElement;
  theme: ThemeName;
  onCrosshairMove?: (time: number | null) => void;
  onVisibleRangeChange?: () => void;
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
  private trades: ISeriesApi<'Histogram'> | null = null;
  private macdLine: ISeriesApi<'Line'> | null = null;
  private macdSignal: ISeriesApi<'Line'> | null = null;
  private macdHist: ISeriesApi<'Histogram'> | null = null;
  private indicatorSeries = new Map<string, ISeriesApi<'Line'>>();
  private dollarLines: IPriceLine[] = [];
  private dollarRange: { low: number; high: number; step: number } | null = null;

  private bars: WireBar[] = [];
  private barIndex = new Map<number, number>();
  private seriesValues = new Map<string, Map<number, number>>();
  private specs: IndicatorSpec[] = [];
  private timeframe: Timeframe = '10s';
  private theme: ThemeName;
  private palette: ChartPalette;
  private readonly bands = new ConfluenceBands();
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

    // Zones ride on the candle series so they share its price scale, and
    // paint underneath it — context behind price, never over it.
    this.candles.attachPrimitive(this.bands);
    // Rides the same series so it shares the price scale the last-value label
    // is drawn on, which is what lets it sit directly underneath.
    this.candles.attachPrimitive(this.countdown);
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

    if (options.onVisibleRangeChange) {
      this.chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
        options.onVisibleRangeChange?.();
      });
    }

    this.observeResize();
  }

  // ── lifecycle ────────────────────────────────────────────────────────

  private chartOptions() {
    const palette = this.palette;
    return {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: palette.surface },
        textColor: palette.textMuted,
        fontFamily:
          "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        fontSize: this.mini ? 9 : 11,
        panes: { separatorColor: palette.border, separatorHoverColor: palette.grid },
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: palette.crosshair,
          width: 1 as const,
          style: LineStyle.Dashed,
          labelBackgroundColor: palette.crosshairLabel,
        },
        horzLine: {
          color: palette.crosshair,
          width: 1 as const,
          style: LineStyle.Dashed,
          labelBackgroundColor: palette.crosshairLabel,
        },
      },
      // Both scales stay visible on a mini chart — a price without an axis is
      // a shape, not a level — but the price scale gives back the width it
      // reserves for a full chart's key-level tags, which a mini has none of.
      rightPriceScale: {
        borderColor: palette.border,
        autoScale: true,
        minimumWidth: this.mini ? 44 : 64,
        // The library reserves a fifth of the pane above the highest bar,
        // which on a chart this dense is a band of empty surface where the
        // action should be. Trimmed to a margin that still keeps a breakout
        // off the ceiling.
        scaleMargins: PRICE_SCALE_MARGINS,
      },
      timeScale: {
        borderColor: palette.border,
        timeVisible: true,
        secondsVisible: this.timeframe === '10s',
        rightOffset: this.mini ? 1 : 4,
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
    // leave the canvas stale; this nudges it back.
    this.resizeObserver = new ResizeObserver(() => {
      if (!this.destroyed) this.chart.applyOptions({});
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
    this.indicatorSeries.clear();
    this.seriesValues.clear();
    this.chart.remove();
  }

  setTheme(theme: ThemeName): void {
    this.theme = theme;
    this.palette = paletteFor(theme);
    this.chart.applyOptions(this.chartOptions());
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
    if (this.bars.length) {
      this.renderPanes();
      this.renderDollarLines();
    }
  }

  private colorFor(spec: IndicatorSpec): string {
    return this.theme === 'dark' ? spec.color_dark : spec.color;
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
   * Anchored to the newest bar's close rather than to the axis, because that
   * is what the last-value label tracks — the two move together as the price
   * scale rescales. With no bars, or on a timeframe whose candle does not
   * close within the day, there is nothing to count and the label goes away.
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
      labelHeight: AXIS_LABEL_HEIGHT(this.mini ? 9 : 11),
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
    const anchorTime = this.bars[0]?.t;

    this.specs = input.specs;
    this.timeframe = input.timeframe;
    this.bars = input.bars;
    this.barIndex = new Map(input.bars.map((bar, index) => [bar.t, index]));

    // Timeframe-dependent formatters have to be reapplied before data lands,
    // or the axis briefly labels 1-minute bars as dates.
    this.chart.applyOptions(this.chartOptions());

    this.reconcileSeries(input.specs, input.timeframe, input.visibility);
    this.applyPricePrecision();
    this.renderCandles();
    this.renderPanes();
    this.renderIndicators(input.series);
    this.renderDollarLines();
    this.crowded.clear();
    this.tickCountdown();

    if (input.resetView) {
      this.resetView();
    } else if (keepLogical) {
      const shift = anchorTime !== undefined ? (this.barIndex.get(anchorTime) ?? 0) : 0;
      this.timeScale.setVisibleLogicalRange({
        from: keepLogical.from + shift,
        to: keepLogical.to + shift,
      });
    }
  }

  /**
   * Match the price scale to the ticker's magnitude.
   *
   * Two decimals is right for a $300 stock and useless for a $0.37 one, where
   * a cent is nearly 3% and every level would round to the same number.
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
  /**
   * Shade the confluence zones behind the candles.
   *
   * A shelf of levels has a thickness; drawing it as one thicker line said
   * that something was there but not where it began or ended, which is what a
   * stop is placed against.
   */
  setBands(bands: readonly PriceBand[]): void {
    this.bands.setBands(bands);
  }

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
   * When a level sits within a label's height of the last trade, the axis has
   * three boxes competing for the same few pixels and the library shuffles
   * them apart — which pushes the price label off the price, and takes the
   * countdown pinned beneath it along for the ride. That is backwards: a key
   * level's axis box is only its number, while the thing that names it is
   * drawn in the chart area and stays put, and the line itself is still
   * there to be read. The price and the seconds left on the bar are what the
   * eye is on at exactly that moment.
   *
   * So the colliding level gives up its axis box until the price moves off
   * it. Only the ones that actually overlap: everything else keeps its label.
   */
  private yieldAxisToPrice(): void {
    const last = this.lastBar();
    if (!last) return;
    const priceY = this.candles.priceToCoordinate(last.c);
    if (priceY === null) return;

    // The price label is centred on the price; the countdown sits directly
    // below it. A level's own box overlaps that pair anywhere in this span.
    const height = AXIS_LABEL_HEIGHT(this.mini ? 9 : 11);
    const values = this.latestValues();

    for (const [id, style] of Object.entries(this.levelStyles)) {
      const series = this.indicatorSeries.get(id);
      if (!series || !style.labelVisible) continue;

      const value = values[id];
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
   * Blank the chart immediately.
   *
   * Called the moment the user switches symbols: the old instrument's
   * candles must not sit under the new ticker's name while its history
   * loads — a wrong chart reads as data, and worse, as the wrong data.
   */
  clear(): void {
    this.bars = [];
    this.barIndex.clear();
    this.countdown.set(null);
    this.seriesValues.clear();
    for (const line of this.dollarLines) this.candles.removePriceLine(line);
    this.dollarLines = [];
    this.dollarRange = null;

    this.candles.setData([]);
    this.extendedHours.setData([]);
    this.volume?.setData([]);
    this.trades?.setData([]);
    this.macdLine?.setData([]);
    this.macdSignal?.setData([]);
    this.macdHist?.setData([]);
    for (const series of this.indicatorSeries.values()) series.setData([]);
  }

  applyBar(bar: WireBar, values: Record<string, number>): void {
    const existingIndex = this.barIndex.get(bar.t);
    if (existingIndex === undefined) {
      this.bars.push(bar);
      this.barIndex.set(bar.t, this.bars.length - 1);
    } else {
      this.bars[existingIndex] = bar;
    }

    const time = bar.t as UTCTimestamp;
    this.candles.update({ time, open: bar.o, high: bar.h, low: bar.l, close: bar.c });
    this.extendedHours.update({ time, value: bar.x ? 1 : 0 });
    this.volume?.update({ time, value: bar.v, color: this.volumeColor(bar) });
    this.trades?.update({ time, value: bar.n, color: this.volumeColor(bar) });

    for (const [id, value] of Object.entries(values)) {
      // A non-finite value poisons a series: every later paint of its pane
      // throws inside the library and the chart goes blank.
      if (!Number.isFinite(value)) continue;
      if (id.startsWith('macd')) {
        this.updateMacdPoint(id, time, value);
        this.rememberValue(id, bar.t, value);
        continue;
      }
      const series = this.indicatorSeries.get(id);
      if (!series) continue;
      series.update({ time, value });
      this.rememberValue(id, bar.t, value);
    }

    // A runner breaking to new highs grows the dollar grid as it goes.
    if (this.dollarRange && (bar.h > this.dollarRange.high || bar.l < this.dollarRange.low)) {
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
      this.bars.map((bar) => ({
        time: bar.t as UTCTimestamp,
        open: bar.o,
        high: bar.h,
        low: bar.l,
        close: bar.c,
      })),
    );
    this.extendedHours.setData(
      this.bars.map((bar) => ({ time: bar.t as UTCTimestamp, value: bar.x ? 1 : 0 })),
    );
  }

  private renderPanes(): void {
    const points = this.bars.map((bar) => ({
      time: bar.t as UTCTimestamp,
      color: this.volumeColor(bar),
    }));
    this.volume?.setData(points.map((point, i) => ({ ...point, value: this.bars[i]!.v })));
    this.trades?.setData(points.map((point, i) => ({ ...point, value: this.bars[i]!.n })));
  }

  private renderIndicators(series: SeriesMap): void {
    this.seriesValues.clear();
    for (const [id, chartSeries] of this.indicatorSeries) {
      const points = series[id] ?? [];
      chartSeries.setData(points.map(([time, value]) => ({ time: time as UTCTimestamp, value })));
      this.seriesValues.set(id, new Map(points));
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
      this.seriesValues.set(id, new Map(series[id] ?? []));
    }
  }

  /**
   * Whole/half dollar gridlines over the traded range.
   *
   * Round numbers are where resistance parks and profit is taken, so they
   * are drawn rather than inferred. The step widens with the range so a
   * high-priced or long-range chart never turns into wallpaper.
   */
  private renderDollarLines(): void {
    for (const line of this.dollarLines) this.candles.removePriceLine(line);
    this.dollarLines = [];
    this.dollarRange = null;

    // On a mini chart the grid would be denser than the candles it sits
    // behind, which is wallpaper rather than information.
    if (this.mini) return;
    if (!this.bars.length || !INTRADAY_TIMEFRAMES.has(this.timeframe)) return;

    let low = Infinity;
    let high = -Infinity;
    for (const bar of this.bars) {
      if (bar.l < low) low = bar.l;
      if (bar.h > high) high = bar.h;
    }
    if (!Number.isFinite(low) || !Number.isFinite(high)) return;

    const pad = Math.max((high - low) * 0.05, 0.5);
    const from = Math.max(0, low - pad);
    const to = high + pad;

    let step = 0.5;
    while ((to - from) / step > MAX_DOLLAR_LINES) {
      step = step === 0.5 ? 1 : step === 1 ? 5 : step === 5 ? 10 : step * 10;
      if (step > 1000) return;
    }

    const start = Math.ceil(from / step) * step;
    for (let price = start; price <= to; price += step) {
      const rounded = Number(price.toFixed(2));
      if (rounded <= 0) continue;
      const isWhole = Math.abs(rounded - Math.round(rounded)) < 1e-9;
      this.dollarLines.push(
        this.candles.createPriceLine({
          price: rounded,
          color: isWhole ? this.palette.wholeDollar : this.palette.halfDollar,
          lineWidth: 1,
          lineStyle: LineStyle.SparseDotted,
          axisLabelVisible: false,
          title: '',
        }),
      );
    }
    this.dollarRange = { low, high, step };
  }

  private rememberValue(id: string, time: number, value: number): void {
    let lookup = this.seriesValues.get(id);
    if (!lookup) {
      lookup = new Map();
      this.seriesValues.set(id, lookup);
    }
    lookup.set(time, value);
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
    // The allow-list is the whole of what makes a mini chart minimal. MACD,
    // the trades pane and every key level are built from this one map, so
    // filtering it here removes all three and nothing below has to know.
    const wanted = new Map(
      specs
        .filter((spec) => spec.timeframes[timeframe] !== undefined)
        .filter((spec) => this.include === null || this.include.has(spec.id))
        .map((spec) => [spec.id, spec]),
    );

    for (const [id, series] of [...this.indicatorSeries]) {
      if (!wanted.has(id)) {
        this.chart.removeSeries(series);
        this.indicatorSeries.delete(id);
        this.seriesValues.delete(id);
      }
    }

    // Sub-panes take consecutive indices after the price pane, in a fixed
    // order, so each keeps its place as others come and go per timeframe.
    let nextPane = 1;
    const volumeSpec = wanted.get('volume');
    this.volume = this.ensureHistogram(this.volume, volumeSpec, volumeSpec ? nextPane : 0);
    if (volumeSpec) nextPane += 1;
    const tradesSpec = wanted.get('trades');
    this.trades = this.ensureHistogram(this.trades, tradesSpec, tradesSpec ? nextPane : 0);
    if (tradesSpec) nextPane += 1;
    const macdSpec = [...wanted.values()].find((spec) => spec.pane === 'macd');
    this.ensureMacd(macdSpec, macdSpec ? nextPane : 0, visibility);
    if (macdSpec) nextPane += 1;

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
   * The MACD pane: line, signal, histogram.
   *
   * Colours follow the platform convention the whole point of MACD rests on
   * — blue MACD line, orange signal, histogram in the candle polarity fills.
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
    if (this.trades) heights.push(TRADES_PANE_HEIGHT);
    if (this.macdLine) heights.push(MACD_PANE_HEIGHT);
    heights.forEach((height, i) => panes[i + 1]?.setHeight(height));
  }

  setIndicatorVisible(id: string, visible: boolean): void {
    this.indicatorSeries.get(id)?.applyOptions({ visible });
    if (id === 'volume') this.volume?.applyOptions({ visible });
    if (id === 'trades') this.trades?.applyOptions({ visible });
    if (id === 'macd') {
      this.macdLine?.applyOptions({ visible });
      this.macdSignal?.applyOptions({ visible });
      this.macdHist?.applyOptions({ visible });
    }
  }

  // ── lookups ──────────────────────────────────────────────────────────

  getBars(): readonly WireBar[] {
    return this.bars;
  }

  barCount(): number {
    return this.bars.length;
  }

  lastBar(): WireBar | null {
    return this.bars.at(-1) ?? null;
  }

  barAt(time: number): WireBar | null {
    const index = this.barIndex.get(time);
    return index === undefined ? null : (this.bars[index] ?? null);
  }

  /** The close of the bar before `time`, for the change readout. */
  previousClose(time: number): number | null {
    const index = this.barIndex.get(time);
    if (index === undefined || index <= 0) return null;
    return this.bars[index - 1]?.c ?? null;
  }

  /**
   * Indicator values at a timestamp.
   *
   * Key-level series are stored compressed — two points per constant run — so
   * an exact hit is rare and the value in effect is the newest point at or
   * before the time asked for.
   */
  valuesAt(time: number): Record<string, number> {
    const values: Record<string, number> = {};
    for (const [id, lookup] of this.seriesValues) {
      const exact = lookup.get(time);
      if (exact !== undefined) {
        values[id] = exact;
        continue;
      }
      let bestTime = -Infinity;
      let bestValue: number | undefined;
      for (const [pointTime, value] of lookup) {
        if (pointTime <= time && pointTime > bestTime) {
          bestTime = pointTime;
          bestValue = value;
        }
      }
      if (bestValue !== undefined) values[id] = bestValue;
    }
    return values;
  }

  latestValues(): Record<string, number> {
    const values: Record<string, number> = {};
    for (const [id, lookup] of this.seriesValues) {
      let bestTime = -Infinity;
      let bestValue: number | undefined;
      for (const [pointTime, value] of lookup) {
        if (pointTime > bestTime) {
          bestTime = pointTime;
          bestValue = value;
        }
      }
      if (bestValue !== undefined) values[id] = bestValue;
    }
    return values;
  }

  // ── navigation ───────────────────────────────────────────────────────

  private get timeScale() {
    return this.chart.timeScale();
  }

  private nudge(scale: number): void {
    const range = this.timeScale.getVisibleLogicalRange();
    if (!range) return;
    const delta = (range.to - range.from) * scale;
    this.timeScale.setVisibleLogicalRange({ from: range.from + delta, to: range.to - delta });
  }

  private pan(scale: number): void {
    const range = this.timeScale.getVisibleLogicalRange();
    if (!range) return;
    const shift = (range.to - range.from) * scale;
    this.timeScale.setVisibleLogicalRange({ from: range.from + shift, to: range.to + shift });
  }

  zoomIn(): void {
    this.nudge(NAV_STEP);
  }

  zoomOut(): void {
    this.nudge(-NAV_STEP);
  }

  scrollLeft(): void {
    this.pan(-NAV_STEP);
  }

  scrollRight(): void {
    this.pan(NAV_STEP);
  }

  resetView(): void {
    if (!this.bars.length) return;
    const visible = this.mini?.visibleBars ?? DEFAULT_VISIBLE_BARS;
    this.chart.priceScale('right').applyOptions({ autoScale: true });
    this.timeScale.setVisibleLogicalRange({
      from: Math.max(0, this.bars.length - visible),
      to: this.bars.length - 1,
    });
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
      barCount: this.bars.length,
      lastBar: this.lastBar(),
      timeframe: this.timeframe,
      theme: this.theme,
      paneCount: this.chart.panes().length,
      // The height the sub-panes occupy — what the floating controls are
      // positioned above, and the only handle a test has on that.
      subPaneOffset: this.subPaneOffset(),
      // Zones are painted on the canvas, so the DOM cannot be asked whether a
      // shelf was shaded. This is the only handle a browser test has on them.
      bands: this.bands.bands.map((band) => ({
        low: band.low,
        high: band.high,
        color: band.color,
      })),
      seriesIds: [...this.indicatorSeries.keys()].sort(),
      pointCounts: Object.fromEntries(
        [...this.seriesValues].map(([id, lookup]) => [id, lookup.size]),
      ),
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
      hasTradesPane: this.trades !== null,
      hasMacdPane: this.macdLine !== null,
      dollarLineCount: this.dollarLines.length,
      // The countdown is painted into the price axis, so the DOM cannot be
      // asked whether it is there or what it says.
      // Levels that have stood down from the axis so the price label and its
      // countdown are not shuffled off the price.
      axisYieldedToPrice: [...this.crowded].sort(),
      countdown: this.countdown.state
        ? { text: this.countdown.state.text, closing: this.countdown.state.closing }
        : null,
      secondsVisible: this.timeframe === '10s',
      // The sub-pane histograms live outside `indicatorSeries`, so they need
      // reporting separately — otherwise a test asking about them reads
      // `undefined` and quietly passes.
      paneSeries: {
        volume: describe(this.volume),
        trades: describe(this.trades),
      },
    };
  }
}
