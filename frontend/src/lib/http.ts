/** REST calls for the configuration the chart needs before it can draw. */

import type {
  IndicatorSpec,
  ScannerConfigResponse,
  SessionInfo,
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
  scannerConfig: (signal?: AbortSignal) =>
    getJson<ScannerConfigResponse>('/api/scanner/config', signal),
};
