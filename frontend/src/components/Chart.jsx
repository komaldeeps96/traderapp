import React, { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from 'react';
import { createChart, ColorType, CrosshairMode, CandlestickSeries, HistogramSeries, LineSeries, AreaSeries } from 'lightweight-charts';

const DEFAULT_VOL_PANE_HEIGHT = 160;
const DEFAULT_VISIBLE_BARS = 240;
const TZ_NY = 'America/New_York';

/**
 * IMPORTANT — lightweight-charts time axis behaviour
 *
 * lightweight-charts uses a **logical index** system.  Every unique timestamp
 * across ALL series (including invisible ones) gets its own sequential slot
 * with equal pixel spacing.  This means:
 *
 *  • Stale data in a hidden series WILL create phantom gaps on the time axis.
 *  • When switching timeframes we MUST clear data from every series that is
 *    not active in the new timeframe — hiding alone is not enough.
 *  • `clearAllSeriesData()` exists specifically for this purpose and must be
 *    called as part of every timeframe transition.
 */

// Pre-compiled formatters for high performance (avoids rule compilation in V8 on every tick)
const fmtDay = new Intl.DateTimeFormat('en-US', {
  timeZone: TZ_NY,
  month: 'short',
  day: 'numeric'
});

const fmtMin = new Intl.DateTimeFormat('en-US', {
  timeZone: TZ_NY,
  hour12: false,
  hour: '2-digit',
  minute: '2-digit'
});

function fmtTime(ts, tf) {
  const d = new Date(ts * 1000);
  if (tf === '1d') return fmtDay.format(d);
  return fmtMin.format(d);
}

function tickMarkFmt(ts, tickMarkType, tf) {
  const d = new Date(ts * 1000);
  if (tickMarkType <= 2) return fmtDay.format(d);
  if (tf === '1d') return fmtDay.format(d);
  return fmtMin.format(d);
}

function compactVolFmt(val) {
  if (val >= 1e6) return (val / 1e6).toFixed(2) + 'M';
  if (val >= 1e3) return (val / 1e3).toFixed(0) + 'K';
  return val.toFixed(0);
}

const Chart = forwardRef(({ onCrosshair }, ref) => {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const mainExtSeriesRef = useRef(null);
  const seriesMapRef = useRef({});
  const barsRef = useRef([]);
  const indicatorConfigRef = useRef([]);
  const timeframeRef = useRef('');
  const pendingDataRef = useRef(false);
  const onCrosshairRef = useRef(onCrosshair);
  onCrosshairRef.current = onCrosshair;

  // ── internal helpers ──────────────────────────────────────

  function getActiveIndicators() {
    return indicatorConfigRef.current.filter(
      ind => ind.timeframes && ind.timeframes[timeframeRef.current] !== undefined
    );
  }

  /**
   * Clear data from every chart series (candle, ext-hours tint, volume, and
   * every indicator).  This guarantees no stale timestamps remain on the time
   * axis after a timeframe switch.
   */
  function clearAllSeriesData() {
    candleSeriesRef.current?.setData([]);
    mainExtSeriesRef.current?.setData([]);
    const seriesMap = seriesMapRef.current;
    for (const key of Object.keys(seriesMap)) {
      if (key === 'mainExtSeries' || key === 'candleSeries') continue;
      seriesMap[key]?.setData([]);
    }
  }

  /**
   * Apply ALL timeframe-dependent chart options in one place.
   * Having a single function prevents options from drifting out of sync
   * (e.g. forgetting to update `secondsVisible` when only the formatter
   * was being changed).
   */
  function applyTimeframeOptions(timeframe) {
    const chart = chartRef.current;
    if (!chart) return;
    chart.applyOptions({
      localization: {
        timeFormatter: (ts) => fmtTime(ts, timeframe),
      },
      timeScale: {
        tickMarkFormatter: (ts, type) => tickMarkFmt(ts, type, timeframe),
        secondsVisible: false,
      },
    });
  }

  /**
   * Ensure every indicator in `config` has a chart series.  Series that
   * already exist are reused; new ones are created.  Series that are not
   * active for `timeframe` are hidden **and their data is cleared** to
   * prevent phantom time-axis slots.
   */
  function reconcileIndicatorSeries(config, timeframe) {
    const chart = chartRef.current;
    if (!chart) return;

    const seriesMap = seriesMapRef.current;
    const indicatorOpts = { crosshairMarkerVisible: false, autoscaleInfoProvider: () => null };

    for (const ind of config) {
      const tfCfg = ind.timeframes && ind.timeframes[timeframe];

      // Series already exists — update visibility and clear stale data
      if (seriesMap[ind.id]) {
        seriesMap[ind.id].applyOptions({ visible: !!tfCfg });
        if (!tfCfg) {
          seriesMap[ind.id].setData([]);
        }
        continue;
      }

      // No series yet and indicator is not active for this tf — skip
      if (!tfCfg) continue;

      // Create new series
      if (ind.type === 'volume') {
        seriesMap[ind.id] = chart.addSeries(HistogramSeries, {
          color: ind.color,
          priceFormat: { type: 'custom', formatter: compactVolFmt, minMove: 1 },
          priceScaleId: 'right',
          lastValueVisible: false,
          priceLineVisible: false,
          title: '',
        }, 1);
      } else {
        seriesMap[ind.id] = chart.addSeries(LineSeries, {
          color: ind.color,
          lineWidth: tfCfg.line_width || 1,
          lineStyle: tfCfg.line_style === 'dashed' ? 2 : 0,
          priceLineVisible: tfCfg.price_line_visible ?? false,
          lastValueVisible: tfCfg.last_value_visible ?? false,
          title: ind.type === 'daily' ? ind.label : undefined,
          ...indicatorOpts,
        }, 0);
      }
    }

    setTimeout(() => {
      const panes = chart.panes();
      if (panes.length > 1) {
        panes[1].setHeight(DEFAULT_VOL_PANE_HEIGHT);
      }
    }, 100);
  }

  // ── public API ────────────────────────────────────────────

  /**
   * Atomic timeframe transition.  Replaces the previous fragile sequence of
   *   clearChart() → setIndicatorConfig() → setIndicatorVisibility()×N
   * that the caller had to orchestrate manually.
   *
   * @param {Array}  config        Full indicator config array
   * @param {string} timeframe     Target timeframe ('1m', '1d')
   * @param {Object} visibilityMap Map of indicator id → boolean visibility
   */
  function switchTimeframe(config, timeframe, visibilityMap) {
    indicatorConfigRef.current = config;
    timeframeRef.current = timeframe;

    // 1. Reset local bar state
    barsRef.current = [];
    pendingDataRef.current = true;

    // 2. Clear every series so no stale timestamps remain
    clearAllSeriesData();

    // 3. Apply all timeframe-dependent chart options
    applyTimeframeOptions(timeframe);

    // 4. Create / show / hide indicator series for the new timeframe
    reconcileIndicatorSeries(config, timeframe);

    // 5. Apply user visibility preferences for active indicators
    const seriesMap = seriesMapRef.current;
    for (const ind of config) {
      if (ind.type === 'volume') continue;
      const isActive = ind.timeframes && ind.timeframes[timeframe] !== undefined;
      if (isActive && seriesMap[ind.id]) {
        seriesMap[ind.id].applyOptions({ visible: visibilityMap[ind.id] ?? false });
      }
    }
  }

  function setIndicatorVisibility(indId, visible) {
    const series = seriesMapRef.current[indId];
    if (series) series.applyOptions({ visible });
  }

  function setHistoryData(barsData) {
    const candleSeries = candleSeriesRef.current;
    const mainExtSeries = mainExtSeriesRef.current;
    if (!candleSeries) return;

    const wasPending = pendingDataRef.current;
    pendingDataRef.current = false;

    const bars = barsData;
    barsRef.current = bars;

    const activeIndicators = getActiveIndicators();
    const candles = [];
    const volPoints = [];
    const extPoints = [];
    const indicatorPoints = {};

    for (const ind of activeIndicators) {
      indicatorPoints[ind.id] = [];
    }

    for (const bar of bars) {
      const t = Math.floor(bar.time);
      const isReg = bar.is_regular !== false;
      const val = isReg ? 0 : 1;

      extPoints.push({ time: t, value: val });
      candles.push({ time: t, open: bar.open, high: bar.high, low: bar.low, close: bar.close });
      volPoints.push({
        time: t,
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(8, 153, 129, 0.5)' : 'rgba(242, 54, 69, 0.5)',
      });

      for (const ind of activeIndicators) {
        const val = bar[ind.id];
        if (val !== null && val !== undefined) {
          indicatorPoints[ind.id].push({ time: t, value: val });
        }
      }
    }

    const range = wasPending ? null : chartRef.current.timeScale().getVisibleLogicalRange();

    mainExtSeries.setData(extPoints);
    candleSeries.setData(candles);
    seriesMapRef.current.volume?.setData(volPoints);

    for (const ind of activeIndicators) {
      if (ind.type === 'volume') continue;
      const s = seriesMapRef.current[ind.id];
      if (s && indicatorPoints[ind.id].length > 0) {
        s.setData(indicatorPoints[ind.id]);
      }
    }

    if (range) {
      chartRef.current.timeScale().setVisibleLogicalRange(range);
    } else if (bars.length > 0) {
      chartRef.current.timeScale().setVisibleLogicalRange({
        from: Math.max(0, bars.length - DEFAULT_VISIBLE_BARS),
        to: bars.length - 1,
      });
    }
  }

  function updateBar(bar) {
    const candleSeries = candleSeriesRef.current;
    const mainExtSeries = mainExtSeriesRef.current;
    if (!candleSeries) return;
    if (pendingDataRef.current) return;

    const t = Math.floor(bar.time);
    const bars = barsRef.current;
    const seriesMap = seriesMapRef.current;

    const last = bars[bars.length - 1];
    if (last && last.time === bar.time) {
      bars[bars.length - 1] = bar;
    } else {
      bars.push(bar);
    }

    const isReg = bar.is_regular !== false;
    const val = isReg ? 0 : 1;

    mainExtSeries.update({ time: t, value: val });
    candleSeries.update({ time: t, open: bar.open, high: bar.high, low: bar.low, close: bar.close });

    seriesMap.volume?.update({
      time: t,
      value: bar.volume,
      color: bar.close >= bar.open ? 'rgba(8, 153, 129, 0.5)' : 'rgba(242, 54, 69, 0.5)',
    });

    for (const ind of getActiveIndicators()) {
      if (ind.type === 'volume') continue;
      const val = bar[ind.id];
      if (val !== null && val !== undefined) {
        seriesMap[ind.id]?.update({ time: t, value: val });
      }
    }
  }

  // ── navigation helpers ────────────────────────────────────

  function zoomIn() {
    const chart = chartRef.current;
    if (!chart) return;
    const ts = chart.timeScale();
    const range = ts.getVisibleLogicalRange();
    if (range) {
      const diff = (range.to - range.from) * 0.1;
      ts.setVisibleLogicalRange({ from: range.from + diff, to: range.to - diff });
    }
  }

  function zoomOut() {
    const chart = chartRef.current;
    if (!chart) return;
    const ts = chart.timeScale();
    const range = ts.getVisibleLogicalRange();
    if (range) {
      const diff = (range.to - range.from) * 0.1;
      ts.setVisibleLogicalRange({ from: range.from - diff, to: range.to + diff });
    }
  }

  function scrollLeft() {
    const chart = chartRef.current;
    if (!chart) return;
    const ts = chart.timeScale();
    const range = ts.getVisibleLogicalRange();
    if (range) {
      const shift = (range.to - range.from) * 0.1;
      ts.setVisibleLogicalRange({ from: range.from - shift, to: range.to - shift });
    }
  }

  function scrollRight() {
    const chart = chartRef.current;
    if (!chart) return;
    const ts = chart.timeScale();
    const range = ts.getVisibleLogicalRange();
    if (range) {
      const shift = (range.to - range.from) * 0.1;
      ts.setVisibleLogicalRange({ from: range.from + shift, to: range.to + shift });
    }
  }

  function autoFit() {
    const chart = chartRef.current;
    if (!chart) return;
    chart.priceScale('right').applyOptions({ autoScale: true });
    const bars = barsRef.current;
    if (bars.length > 0) {
      chart.timeScale().setVisibleLogicalRange({
        from: Math.max(0, bars.length - DEFAULT_VISIBLE_BARS),
        to: bars.length - 1,
      });
    }
  }

  // ── read-only accessors ───────────────────────────────────

  function getLatestBar() {
    const bars = barsRef.current;
    return bars.length > 0 ? bars[bars.length - 1] : null;
  }

  function getBars() {
    return barsRef.current;
  }

  function getVolumePaneBottom() {
    const chart = chartRef.current;
    if (!chart) return DEFAULT_VOL_PANE_HEIGHT + 31;
    try {
      const panes = chart.panes();
      if (panes.length > 1) {
        return panes[1].getHeight() + 31;
      }
    } catch (e) { /* disposed */ }
    return DEFAULT_VOL_PANE_HEIGHT + 31;
  }

  // ── imperative handle ─────────────────────────────────────

  useImperativeHandle(ref, () => ({
    switchTimeframe,
    setIndicatorVisibility,
    setHistoryData,
    updateBar,
    zoomIn,
    zoomOut,
    scrollLeft,
    scrollRight,
    autoFit,
    getLatestBar,
    getBars,
    getVolumePaneBottom,
  }));

  // ── chart creation ────────────────────────────────────────

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#787b86',
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, Ubuntu, sans-serif",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: '#f0f3fa' },
        horzLines: { color: '#f0f3fa' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#9598a1', width: 1, style: 2, labelBackgroundColor: '#131722' },
        horzLine: { color: '#9598a1', width: 1, style: 2, labelBackgroundColor: '#131722' },
      },
      localization: {
        timeFormatter: (ts) => fmtTime(ts, '1m'),
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: '#d1d4dc',
        tickMarkFormatter: (ts, type) => tickMarkFmt(ts, type, '1m'),
      },
      rightPriceScale: {
        borderColor: '#d1d4dc',
        autoScale: true,
        entireTextOnly: false,
        minimumWidth: 50,
      },
    });

    chartRef.current = chart;

    const mainExtSeries = chart.addSeries(AreaSeries, {
      priceScaleId: '',
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
      topColor: 'rgba(33, 150, 243, 0.05)',
      bottomColor: 'rgba(33, 150, 243, 0.05)',
      lineColor: 'rgba(0, 0, 0, 0)',
      lineWidth: 0,
      autoscaleInfoProvider: () => ({
        priceRange: {
          minValue: 0,
          maxValue: 1,
        },
      }),
    }, 0);
    mainExtSeries.priceScale().applyOptions({
      scaleMargins: { top: 0, bottom: 0 },
    });
    mainExtSeriesRef.current = mainExtSeries;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    }, 0);
    candleSeriesRef.current = candleSeries;

    seriesMapRef.current = { mainExtSeries, candleSeries };

    setTimeout(() => {
      const panes = chart.panes();
      if (panes.length > 1) {
        panes[1].setHeight(DEFAULT_VOL_PANE_HEIGHT);
      }
    }, 200);

    const handleResize = () => {
      chart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight,
      });
    };

    window.addEventListener('resize', handleResize);
    setTimeout(handleResize, 100);

    chart.subscribeCrosshairMove((param) => {
      const cb = onCrosshairRef.current;
      if (cb) {
        cb(!param.time || param.point === undefined ? null : param.time);
      }
    });

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      mainExtSeriesRef.current = null;
      seriesMapRef.current = {};
      barsRef.current = [];
    };
  }, []);

  return <div ref={containerRef} className="flex-1 w-full min-h-0 relative" />;
});

Chart.displayName = 'Chart';

export default Chart;
