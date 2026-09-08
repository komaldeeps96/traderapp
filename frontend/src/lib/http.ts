/** REST calls for the configuration the chart needs before it can draw. */

import type {
  ArticleResponse,
  ConceptsResponse,
  FilingsResponse,
  FinancialPeriodKind,
  FinancialsResponse,
  FundamentalsResponse,
  MetricsResponse,
  OwnershipResponse,
  PeersResponse,
  NewsBriefResponse,
  NewsResponse,
  SetupResponse,
  IndicatorSpec,
  ScannerTiersResponse,
  SessionInfo,
  SwingRowsResponse,
  SwingScreensResponse,
  WatchlistResponse,
  TimeframeInfo,
} from '@/types/protocol';

export const API_PORT = '8000';

function baseUrl(): string {
  const override = import.meta.env?.VITE_API_URL;
  if (override) return override;
  if (typeof window === 'undefined') return `http://localhost:${API_PORT}`;

  // Served by the API itself (production, and the Docker image): same origin.
  // Served by Vite's dev or preview server on another port: the API is still
  // on 8000.
  const { protocol, hostname, port, origin } = window.location;
  return port && port !== API_PORT ? `${protocol}//${hostname}:${API_PORT}` : origin;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${baseUrl()}${path}`, {
    signal: signal ?? null,
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    throw new ApiError(`${path} failed: ${response.status}`, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  indicators: (signal?: AbortSignal) => getJson<IndicatorSpec[]>('/api/indicators', signal),
  timeframes: (signal?: AbortSignal) => getJson<TimeframeInfo[]>('/api/timeframes', signal),
  session: (signal?: AbortSignal) => getJson<SessionInfo>('/api/session', signal),
  scannerTiers: (signal?: AbortSignal) =>
    getJson<ScannerTiersResponse>('/api/scanner/tiers', signal),
  // Warmed server-side at subscribe time, so this is normally a cache read.
  fundamentals: (symbol: string, signal?: AbortSignal) =>
    getJson<FundamentalsResponse>(`/api/fundamentals/${encodeURIComponent(symbol)}`, signal),
  financials: (symbol: string, period: FinancialPeriodKind, signal?: AbortSignal) =>
    getJson<FinancialsResponse>(
      `/api/financials/${encodeURIComponent(symbol)}?period=${period}`,
      signal,
    ),
  metrics: (symbol: string, period: FinancialPeriodKind, signal?: AbortSignal) =>
    getJson<MetricsResponse>(
      `/api/metrics/${encodeURIComponent(symbol)}?period=${period}`,
      signal,
    ),
  swingScreens: (signal?: AbortSignal) =>
    getJson<SwingScreensResponse>('/api/swing/screens', signal),
  swingRows: (screenId: string, signal?: AbortSignal) =>
    getJson<SwingRowsResponse>(`/api/swing/${encodeURIComponent(screenId)}`, signal),
  // The socket pushes this after every edit; the fetch is only for a reload
  // that lands before the socket is up.
  watchlist: (signal?: AbortSignal) =>
    getJson<WatchlistResponse>('/api/watchlist', signal),
  // Priced per filing, so it is fetched when the tab opens and never warmed.
  ownership: (symbol: string, signal?: AbortSignal) =>
    getJson<OwnershipResponse>(`/api/ownership/${encodeURIComponent(symbol)}`, signal),
  peers: (symbol: string, signal?: AbortSignal) =>
    getJson<PeersResponse>(`/api/peers/${encodeURIComponent(symbol)}`, signal),
  concepts: (
    symbol: string,
    query: string,
    period: FinancialPeriodKind,
    signal?: AbortSignal,
  ) =>
    getJson<ConceptsResponse>(
      `/api/concepts/${encodeURIComponent(symbol)}?q=${encodeURIComponent(query)}&period=${period}`,
      signal,
    ),
  filings: (symbol: string, signal?: AbortSignal) =>
    getJson<FilingsResponse>(`/api/filings/${encodeURIComponent(symbol)}`, signal),
  news: (symbol: string, signal?: AbortSignal) =>
    getJson<NewsResponse>(`/api/news/${encodeURIComponent(symbol)}`, signal),
  /**
   * The whole screen, judged. Slow on purpose — the server assembles the
   * snapshot and runs a `claude` process against it — so callers pass a
   * signal and the panel shows that it is thinking.
   */
  setup: (symbol: string, refresh: boolean, signal?: AbortSignal) =>
    getJson<SetupResponse>(
      `/api/setup/${encodeURIComponent(symbol)}${refresh ? '?refresh=true' : ''}`,
      signal,
    ),
  /**
   * One day of headlines, read and scored. Slow on purpose — the server runs
   * a `claude` process and awaits it — so callers pass a signal and the panel
   * shows that it is reading.
   */
  newsBrief: (symbol: string, refresh: boolean, signal?: AbortSignal) =>
    getJson<NewsBriefResponse>(
      `/api/news/${encodeURIComponent(symbol)}/brief${refresh ? '?refresh=true' : ''}`,
      signal,
    ),
  // Provider and id are query parameters: IBKR article ids carry a "$"
  // (DJ-N$1f364634), which is legal in a query string and a nuisance in a path.
  article: (symbol: string, provider: string, articleId: string, signal?: AbortSignal) =>
    getJson<ArticleResponse>(
      `/api/news/${encodeURIComponent(symbol)}/article?provider=${encodeURIComponent(
        provider,
      )}&article_id=${encodeURIComponent(articleId)}`,
      signal,
    ),
};
