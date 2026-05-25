import { useState, useEffect, useRef, useCallback } from 'react';
import { wsClient } from '../services/wsClient';

export function useWebSocket() {
  const [connected, setConnected] = useState(false);
  const onMessageRef = useRef(() => {});

  useEffect(() => {
    wsClient.onMessage((msg) => onMessageRef.current(msg));
    wsClient.onStatusChange((isConnected) => setConnected(isConnected));
    wsClient.connect();

    return () => {
      // Unregister callbacks but do NOT destroy the singleton connection
      wsClient.onMessage(null);
      wsClient.onStatusChange(null);
    };
  }, []);

  const subscribe = useCallback((ticker, timeframe) => {
    wsClient.subscribe(ticker, timeframe);
  }, []);

  const handleMessage = useCallback((handler) => {
    onMessageRef.current = handler;
  }, []);

  return { connected, subscribe, handleMessage };
}
