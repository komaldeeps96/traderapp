import React, { useState, useRef, useCallback, useEffect } from 'react';
import Chart from '../components/Chart.jsx';
import ToolbarOverlay from '../components/Toolbar/ToolbarOverlay.jsx';
import IndicatorList from '../components/Toolbar/IndicatorList.jsx';
import { useWebSocket } from '../hooks/useWebSocket';
import { useChartData } from '../hooks/useChartData';
import { useIndicatorConfig } from '../hooks/useIndicatorConfig';
import { useCrosshair } from '../hooks/useCrosshair';
import { useVolumePane } from '../hooks/useVolumePane';
import { fetchActiveTicker, fetchActiveTimeframe } from '../services/httpClient';

export default function Dashboard() {
  const chartRef = useRef(null);
  const ohlcvRef = useRef(null);
  const indicatorListRef = useRef(null);

  const [ticker, setTicker] = useState('');
  const [timeframe, setTimeframe] = useState('1m');
  const tickerRef = useRef('');
  const timeframeRef = useRef('1m');

  const { connected, subscribe, handleMessage } = useWebSocket();
  const { barsRef, latestBarRef, processHistory, processUpdate, clearData } = useChartData();
  const { config, visibility, configRef, visibilityRef, setTimeframe: setTfVisibility, toggleIndicator } = useIndicatorConfig();
  const { hoverTimeRef, handleCrosshair, getHoverBar } = useCrosshair();
  const volPaneBottom = useVolumePane(chartRef);

  function updateDisplays() {
    const bar = latestBarRef.current;
    const bars = barsRef.current;
    const hoverTime = hoverTimeRef.current;
    const activeBar = hoverTime ? getHoverBar(bars) : bar;
    ohlcvRef.current?.setData(bar, bars, hoverTime);
    indicatorListRef.current?.setData(activeBar);
  }

  const subscribeRef = useRef((newTicker, newTimeframe) => {
    const oldTf = timeframeRef.current;
    setTfVisibility(newTimeframe, oldTf);

    tickerRef.current = newTicker;
    timeframeRef.current = newTimeframe;

    setTicker(newTicker);
    setTimeframe(newTimeframe);
    clearData();
    hoverTimeRef.current = null;

    // Single atomic call replaces the old fragile sequence of
    // setIndicatorConfig → clearChart → setIndicatorVisibility×N
    chartRef.current?.switchTimeframe(
      configRef.current,
      newTimeframe,
      visibilityRef.current,
    );
    updateDisplays();

    subscribe(newTicker, newTimeframe);
  });

  handleMessage((msg) => {
    if (msg.type === 'error') {
      console.error('Backend error:', msg.message);
      return;
    }
    if (msg.ticker !== tickerRef.current || msg.timeframe !== timeframeRef.current) {
      return;
    }

    if (msg.type === 'bar_history') {
      processHistory(msg.data);
      chartRef.current?.setHistoryData(msg.data);
      updateDisplays();
    } else if (msg.type === 'bar_update') {
      processUpdate(msg.data);
      chartRef.current?.updateBar(msg.data);
      updateDisplays();
    }
  });

  const doToggleIndicator = useCallback((indId) => {
    toggleIndicator(indId);
    chartRef.current?.setIndicatorVisibility(indId, !visibility[indId]);
  }, [toggleIndicator, visibility]);

  const doCrosshair = useCallback((time) => {
    handleCrosshair(time);
    updateDisplays();
  }, [handleCrosshair]);

  useEffect(() => {
    if (config.length > 0) {
      chartRef.current?.switchTimeframe(
        config,
        timeframeRef.current,
        visibilityRef.current,
      );
    }
  }, [config]);

  useEffect(() => {
    if (connected) {
      Promise.all([fetchActiveTicker(), fetchActiveTimeframe()])
        .then(([tickerData, tfData]) => {
          const t = tickerData.active_ticker;
          const tf = tfData.active_timeframe || '1m';
          if (t) subscribeRef.current(t, tf);
        })
        .catch(() => {});
    }
  }, [connected]);

  const handleSubscribe = useCallback((...args) => subscribeRef.current(...args), []);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-gray-50 dark:bg-gray-950 font-sans">
      {/* Sidebar Pane (IndicatorList & Branding) */}
      <div className="w-[330px] h-full border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 flex flex-col shrink-0">
        <div className="p-4 border-b border-gray-200/50 dark:border-gray-800/50 flex flex-col gap-1 select-none">
          <div className="flex items-center justify-between">
            <h1 className="text-sm font-bold text-gray-950 dark:text-gray-50 flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded bg-blue-600 dark:bg-blue-500 animate-pulse"></span>
              <span>TraderApp Terminal</span>
            </h1>
            <span className="text-[9px] font-bold text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/50 px-1.5 py-0.5 rounded uppercase tracking-wider">
              PRO LIVE
            </span>
          </div>
          <p className="text-[10px] text-gray-400 dark:text-gray-500 font-semibold uppercase tracking-wider">
            Real-time Indicators & Key Levels
          </p>
        </div>
        <div className="flex-1 p-4 flex flex-col gap-4 overflow-hidden">
          <IndicatorList
            ref={indicatorListRef}
            indicators={config}
            timeframe={timeframe}
            visibility={visibility}
            onToggle={doToggleIndicator}
          />
        </div>
      </div>

      {/* Main Chart Area */}
      <div className="flex-1 h-full relative min-w-0 bg-white dark:bg-gray-950 flex flex-col">
        <Chart ref={chartRef} onCrosshair={doCrosshair} />
        <ToolbarOverlay
          ticker={ticker}
          timeframe={timeframe}
          connected={connected}
          indicators={config}
          visibility={visibility}
          volPaneBottom={volPaneBottom}
          ohlcvRef={ohlcvRef}
          onSubscribe={handleSubscribe}
          onToggleIndicator={doToggleIndicator}
          onZoomIn={() => chartRef.current?.zoomIn()}
          onZoomOut={() => chartRef.current?.zoomOut()}
          onScrollLeft={() => chartRef.current?.scrollLeft()}
          onScrollRight={() => chartRef.current?.scrollRight()}
          onAutoFit={() => chartRef.current?.autoFit()}
        />
      </div>
    </div>
  );
}
