import { useCallback, useEffect } from 'react';

import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';

/**
 * Load the feed when the symbol changes, and again on every reconnect: a
 * headline published while the socket was down never arrives live. The dock
 * runs this whichever tab is open, and it writes to the store, so a live
 * headline over the WebSocket merges into a list that already exists.
 */
export function useNewsFeed(symbol: string): void {
  const setNews = useTerminalStore((state) => state.setNews);
  const setStatus = useTerminalStore((state) => state.setNewsStatus);
  const connected = useTerminalStore((state) => state.connected);

  const load = useCallback(
    async (signal: AbortSignal) => {
      setStatus('loading');
      try {
        const response = await api.news(symbol, signal);
        if (signal.aborted) return;
        setNews(response.symbol, response.headlines, response.providers);
        setStatus('ready');
      } catch {
        if (!signal.aborted) setStatus('error');
      }
    },
    [symbol, setNews, setStatus],
  );

  useEffect(() => {
    if (!symbol || !connected) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [symbol, connected, load]);
}
