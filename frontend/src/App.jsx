import React, { useState, useEffect, useRef, useCallback } from 'react';
import ChartWidget from './components/ChartWidget';

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [ticker, setTicker] = useState('');
  const [timeframe, setTimeframe] = useState('10s');
  const [chartData, setChartData] = useState(null);

  const [indicatorConfig, setIndicatorConfig] = useState([]);
  const [indicatorVisibility, setIndicatorVisibility] = useState({});

  const visibilityRef = useRef({}); // { '10s': { ema54: true, ... }, '1m': {...}, '1d': {...} }

  const socketRef = useRef(null);
  const tickerRef = useRef(ticker);
  const timeframeRef = useRef(timeframe);

  // Fetch indicator config on mount
  useEffect(() => {
    fetch('http://localhost:8000/api/indicators')
      .then(r => r.json())
      .then(config => {
        setIndicatorConfig(Array.isArray(config) ? config : []);
      })
      .catch(() => {});
  }, []);

  const getDefaults = useCallback((tf) => {
    const defaults = {};
    for (const ind of indicatorConfig) {
      if (ind.timeframes && ind.timeframes[tf] !== undefined) {
        defaults[ind.id] = ind.timeframes[tf].default_enabled ?? true;
      }
    }
    return defaults;
  }, [indicatorConfig]);

  // Apply default visibility when indicator config loads (initial page load)
  useEffect(() => {
    if (indicatorConfig.length > 0 && timeframe && Object.keys(indicatorVisibility).length === 0) {
      const saved = visibilityRef.current[timeframe] || {};
      setIndicatorVisibility({ ...getDefaults(timeframe), ...saved });
    }
  }, [indicatorConfig]);

  // WebSocket connection — created once
  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws');
    socketRef.current = ws;

    ws.onopen = async () => {
      setIsConnected(true);
      try {
        const res = await fetch('http://localhost:8000/api/active-ticker');
        const data = await res.json();
        if (data.active_ticker) {
          setTicker(data.active_ticker);
          tickerRef.current = data.active_ticker;
          ws.send(JSON.stringify({ action: 'subscribe', ticker: data.active_ticker, timeframe: '10s' }));
        }
      } catch {
        // backend unreachable or no saved ticker — user will enter manually
      }
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);

        if (message.type === 'error') {
          console.error('Backend Error:', message.message);
          alert(`Error: ${message.message}`);
          return;
        }

        // Filter: only accept data for our current subscription
        if (message.ticker !== tickerRef.current || message.timeframe !== timeframeRef.current) {
          return;
        }

        if (message.type === 'bar_history') {
          console.log(`History received: ${message.data.length} bars for ${message.ticker}/${message.timeframe}`);
          setChartData({ type: 'history', bars: message.data });
        } else if (message.type === 'bar_update') {
          setChartData({ type: 'update', bar: message.data });
        }
      } catch (err) {
        console.error('Error parsing message:', err);
      }
    };

    ws.onclose = () => setIsConnected(false);
    ws.onerror = (err) => console.error('WebSocket error:', err);

    return () => ws.close();
  }, []);

  const handleSubscribe = useCallback((newTicker, newTimeframe) => {
    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      const oldTf = timeframeRef.current;

      // Save current visibility for old timeframe
      if (oldTf) {
        visibilityRef.current[oldTf] = { ...indicatorVisibility };
      }

      // Unsubscribe from the current ticker
      ws.send(JSON.stringify({ action: 'unsubscribe', ticker: tickerRef.current, timeframe: timeframeRef.current }));

      tickerRef.current = newTicker;
      timeframeRef.current = newTimeframe;

      setTicker(newTicker);
      setTimeframe(newTimeframe);
      setChartData(null);

      // Load visibility for new timeframe (saved overrides defaults)
      const saved = visibilityRef.current[newTimeframe] || {};
      setIndicatorVisibility({ ...getDefaults(newTimeframe), ...saved });

      ws.send(JSON.stringify({ action: 'subscribe', ticker: newTicker, timeframe: newTimeframe }));
    }
  }, [indicatorVisibility, getDefaults]);

  const toggleIndicator = useCallback((id) => {
    setIndicatorVisibility(prev => ({ ...prev, [id]: !prev[id] }));
  }, []);

  return (
    <div className="w-full h-screen flex flex-col bg-gray-50 overflow-hidden font-sans text-gray-800">
      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 relative">
          <ChartWidget
            chartData={chartData}
            ticker={ticker}
            timeframe={timeframe}
            isConnected={isConnected}
            onSubscribe={handleSubscribe}
            indicatorConfig={indicatorConfig}
            indicatorVisibility={indicatorVisibility}
            toggleIndicator={toggleIndicator}
          />
        </div>
      </div>
    </div>
  );
}

export default App;
