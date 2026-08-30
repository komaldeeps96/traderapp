/**
 * A complete backend, served from inside the browser.
 *
 * Playwright intercepts both the REST calls and the WebSocket, so the real
 * frontend bundle runs unmodified against a scripted server. That buys three
 * things the live stack cannot: determinism (identical data every run),
 * independence from market hours and credentials, and the ability to force
 * situations that are otherwise hard to reach — a dropped socket, a delayed
 * feed, a symbol with no data.
 */

import type { Page, WebSocketRoute } from '@playwright/test';

import {
  INDICATORS,
  MANY_INDICATORS,
  SCAN_CODES,
  SCANNER_TIERS,
  TIMEFRAMES,
  makeApiUsage,
  makeArticle,
  makeFilings,
  makeFundamentals,
  makeInfo,
  makeNews,
  makeQuote,
  makeScannerMessage,
  makeScannerRows,
  makeRegimeMessage,
  makeSnapshot,
  makeStatus,
  type ScannerTierId,
  type SnapshotOptions,
} from './data';

export interface MockBackendOptions {
  /** Symbol the session restores on load. */
  sessionSymbol?: string;
  sessionTimeframe?: string;
  /** Scanner needs IBKR; off by default, matching an Alpaca-only setup. */
  scannerAvailable?: boolean;
  source?: 'ibkr' | 'alpaca' | 'none';
  delayed?: boolean;
  /** Symbols that should answer with "no data". */
  emptySymbols?: string[];
  /** Delay before a snapshot is sent, for testing the loading state. */
  snapshotDelayMs?: number;
  /** Starting price, for exercising sub-dollar tickers. */
  basePrice?: number;
  /** Serve the full overhead level stack, burying the last price in the panel. */
  manyLevels?: boolean;
}

export interface MockBackend {
  /** Commands the page has sent, newest last. */
  commands: () => Array<Record<string, unknown>>;
  waitForCommand: (action: string, timeoutMs?: number) => Promise<Record<string, unknown>>;
  send: (message: unknown) => Promise<void>;
  pushStatus: (overrides?: Record<string, unknown>) => Promise<void>;
  pushScanner: (
    scannerId: ScannerTierId,
    rows?: ReturnType<typeof makeScannerRows>,
    running?: boolean,
  ) => Promise<void>;
  pushRegime: (running?: boolean) => Promise<void>;
  pushQuote: (overrides?: Partial<Record<string, number>>) => Promise<void>;
  pushInfo: (overrides?: Partial<Record<string, unknown>>) => Promise<void>;
  pushApiUsage: (overrides?: { alpaca?: number; ibkr?: number }) => Promise<void>;
  pushError: (code: string, message: string) => Promise<void>;
  /** Drop the socket to exercise reconnection. */
  dropConnection: () => Promise<void>;
  lastSnapshot: () => ReturnType<typeof makeSnapshot> | null;
  setSnapshotDelay: (ms: number) => void;
}

export async function installMockBackend(
  page: Page,
  options: MockBackendOptions = {},
): Promise<MockBackend> {
  const {
    sessionSymbol = 'AAPL',
    sessionTimeframe = '10s',
    scannerAvailable = false,
    source = 'alpaca',
    delayed = false,
    emptySymbols = [],
  } = options;

  let snapshotDelayMs = options.snapshotDelayMs ?? 0;
  let socket: WebSocketRoute | null = null;
  let snapshot: ReturnType<typeof makeSnapshot> | null = null;
  const received: Array<Record<string, unknown>> = [];

  /** A string field off a parsed command, or the fallback if it is not one. */
  const text = (value: unknown, fallback: string): string =>
    typeof value === 'string' ? value : fallback;

  await json(page, '**/api/indicators', options.manyLevels ? MANY_INDICATORS : INDICATORS);
  await json(page, '**/api/timeframes', TIMEFRAMES);
  await json(page, '**/api/session', {
    symbol: sessionSymbol,
    timeframe: sessionTimeframe,
    default_symbol: 'AAPL',
    default_timeframe: '10s',
  });
  // The dock's fundamentals panel. Served for any symbol; specs that need a
  // different read override it with `page.route` after installing.
  await json(page, '**/api/fundamentals/**', makeFundamentals());
  await json(page, '**/api/filings/**', makeFilings());
  // Order matters: the article route is registered first so the broader news
  // pattern does not swallow it.
  await json(page, '**/api/news/*/article*', makeArticle());
  await json(page, '**/api/news/*', makeNews());
  await json(page, '**/api/scanner/tiers', {
    scan_codes: SCAN_CODES,
    tiers: SCANNER_TIERS,
    note: scannerAvailable
      ? null
      : 'Market scanner requires a running IBKR TWS or Gateway connection.',
  });
  await page.routeWebSocket(/\/ws(\?.*)?$/, (ws) => {
    socket = ws;

    // The real server opens with status, one scanner frame per market-cap
    // tier, regime, then api — seven frames in all.
    ws.send(JSON.stringify(makeStatus({ source, delayed })));
    for (const tier of SCANNER_TIERS) {
      ws.send(JSON.stringify(makeScannerMessage(tier.id, [], scannerAvailable)));
    }
    ws.send(JSON.stringify(makeRegimeMessage()));
    ws.send(JSON.stringify(makeApiUsage()));

    ws.onMessage((raw) => {
      let command: Record<string, unknown>;
      try {
        command = JSON.parse(String(raw)) as Record<string, unknown>;
      } catch {
        return;
      }
      received.push(command);

      switch (command.action) {
        case 'ping':
          ws.send(JSON.stringify({ type: 'pong' }));
          break;

        case 'subscribe': {
          const symbol = text(command.symbol, '');
          const timeframe = text(command.timeframe, '10s');
          // Extra timeframes on the same symbol — the mini charts. The real
          // server answers with one snapshot each, primary first.
          const extras = Array.isArray(command.extra_timeframes)
            ? command.extra_timeframes.map((entry) => text(entry, ''))
            : [];

          if (emptySymbols.includes(symbol)) {
            ws.send(
              JSON.stringify({
                type: 'error',
                code: 'no_data',
                message: `No market data available for ${symbol}.`,
              }),
            );
            break;
          }

          const build = (tf: string) =>
            makeSnapshot({
              symbol,
              timeframe: tf,
              source,
              delayed,
              ...(options.basePrice !== undefined ? { basePrice: options.basePrice } : {}),
              ...(options.manyLevels ? { manyLevels: true } : {}),
              ...barCountFor(tf),
            });

          const payload = build(timeframe);
          snapshot = payload;

          const follow = () => {
            ws.send(JSON.stringify(payload));
            for (const extra of extras) {
              if (extra !== timeframe) ws.send(JSON.stringify(build(extra)));
            }
            // The real server follows a snapshot with the level 1 quote, and
            // the info strip lands with the first broadcast tick.
            const close = payload.bars.at(-1)?.c ?? 10;
            ws.send(
              JSON.stringify(
                makeQuote(symbol, { bid: close - 0.02, ask: close + 0.02, t: payload.generated_at }),
              ),
            );
            ws.send(JSON.stringify(makeInfo(symbol)));
          };

          if (snapshotDelayMs > 0) {
            setTimeout(follow, snapshotDelayMs);
          } else {
            follow();
          }
          break;
        }

        case 'scanner.configure': {
          const scannerId = text(command.scanner_id, 'small_cap') as ScannerTierId;
          ws.send(JSON.stringify(makeScannerMessage(scannerId, [], scannerAvailable)));
          break;
        }

        default:
          break;
      }
    });
  });

  async function send(message: unknown): Promise<void> {
    await waitForSocket();
    socket!.send(JSON.stringify(message));
  }

  async function waitForSocket(timeoutMs = 5000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (!socket) {
      if (Date.now() > deadline) throw new Error('the page never opened a WebSocket');
      await page.waitForTimeout(25);
    }
  }

  return {
    commands: () => [...received],

    async waitForCommand(action, timeoutMs = 5000) {
      const deadline = Date.now() + timeoutMs;
      for (;;) {
        const match = [...received].reverse().find((entry) => entry.action === action);
        if (match) return match;
        if (Date.now() > deadline) {
          throw new Error(
            `no ${action} command within ${timeoutMs}ms; saw: ${received
              .map((entry) => entry.action)
              .join(', ')}`,
          );
        }
        await page.waitForTimeout(25);
      }
    },

    send,

    pushStatus: (overrides = {}) => send(makeStatus({ source, delayed, ...overrides })),

    pushScanner: (scannerId, rows = [], running = true) =>
      send(makeScannerMessage(scannerId, rows, running)),

    pushRegime: (running = true) => send(makeRegimeMessage(running)),

    pushQuote: (overrides = {}) => send(makeQuote(snapshot?.symbol ?? 'AAPL', overrides)),

    pushInfo: (overrides = {}) => send(makeInfo(snapshot?.symbol ?? 'AAPL', overrides)),

    pushApiUsage: (overrides = {}) => send(makeApiUsage(overrides)),

    pushError: (code, message) => send({ type: 'error', code, message }),

    async dropConnection() {
      await waitForSocket();
      const current = socket;
      socket = null;
      await current!.close({ code: 1006, reason: 'connection lost' });
    },

    lastSnapshot: () => snapshot,

    setSnapshotDelay(ms: number) {
      snapshotDelayMs = ms;
    },
  };
}

/** Fewer bars on higher timeframes, as resampling would produce. */
function barCountFor(timeframe: string): SnapshotOptions {
  switch (timeframe) {
    case '5m':
      return { barCount: 60 };
    case '15m':
      return { barCount: 30 };
    case '30m':
      return { barCount: 24 };
    case '1h':
      return { barCount: 20 };
    case '4h':
      return { barCount: 12 };
    case '1d':
      return { barCount: 120 };
    case '1w':
      return { barCount: 52 };
    default:
      // 10s and 1m both fill a session's worth of view.
      return { barCount: 240 };
  }
}


async function json(page: Page, pattern: string, body: unknown): Promise<void> {
  await page.route(pattern, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify(body),
    }),
  );
}
