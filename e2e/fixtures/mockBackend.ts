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
  makeBrief,
  makeFilings,
  makeFinancials,
  makeFundamentals,
  makeMetrics,
  makeConcepts,
  makeOwnership,
  makePeers,
  makeSwingRows,
  makeSwingScreens,
  makeWatchlistMessage,
  makeWatchlistRow,
  makeInfo,
  makeNews,
  makeSetup,
  makeOrder,
  makeQuote,
  makeScannerMessage,
  makeScannerRows,
  makeRegimeMessage,
  makeSnapshot,
  makeStatus,
  makeTape,
  makeTapePrints,
  makeTradingMessage,
  type ScannerTierId,
  type SnapshotOptions,
  type TapePrintFixture,
} from './data';

export interface MockBackendOptions {
  /** Symbol the session restores on load. */
  sessionSymbol?: string;
  /** Fields to override on every streamed `info` frame. */
  infoOverrides?: Record<string, unknown>;
  /** Indicator toggles the server has stored, keyed by timeframe. */
  sessionIndicators?: Record<string, Record<string, boolean>>;
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
  /** Symbols already on the server's watchlist when the page loads. */
  watchlist?: string[];
  /**
   * The tape a subscribe opens with. Defaults to one row of every verdict;
   * pass `[]` for a name that has not printed.
   */
  tape?: TapePrintFixture[];
  /** Arm the order-entry strip. Off by default, as the real server is. */
  trading?: Record<string, unknown>;
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
  /** Push prints as the broadcaster does — appended, not a replacement. */
  pushTape: (prints: TapePrintFixture[]) => Promise<void>;
  pushTrading: (overrides?: Record<string, unknown>) => Promise<void>;
  pushOrder: (overrides?: Record<string, unknown>) => Promise<void>;
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
    sessionIndicators = {},
    infoOverrides = {},
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
    indicators: sessionIndicators,
  });
  // The dock's fundamentals panel. Served for any symbol; specs that need a
  // different read override it with `page.route` after installing.
  await json(page, '**/api/fundamentals/**', makeFundamentals());
  // One handler reading the query rather than two competing globs: `**`
  // crosses a '/' and would match the quarterly URL too, leaving which
  // fixture answers a question about route precedence.
  await page.route('**/api/financials/**', (route) => {
    const quarterly = new URL(route.request().url()).searchParams.get('period') === 'quarterly';
    void route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify(
        quarterly
          ? {
              ...makeFinancials(),
              period: 'quarterly',
              periods: [
                { key: 'FY2026 Q3', end: '2026-06-27', fiscal_year: 2026 },
                { key: 'FY2026 Q2', end: '2026-03-28', fiscal_year: 2026 },
              ],
            }
          : makeFinancials(),
      ),
    });
  });
  await json(page, '**/api/metrics/**', makeMetrics());
  // One handler, because both URLs are one path segment deep and Playwright
  // uses the *last* matching route registered — so a '**/api/swing/*' pattern
  // silently answers /api/swing/screens too.
  await page.route('**/api/swing/*', (route) => {
    const catalogue = new URL(route.request().url()).pathname.endsWith('/screens');
    void route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify(catalogue ? makeSwingScreens() : makeSwingRows()),
    });
  });
  // The watchlist the mock server is holding. Add and remove edit *this*, and
  // the whole list is broadcast back — the same contract the real server has,
  // which is what lets a spec assert that the panel renders what came back
  // rather than what it optimistically drew.
  let watchlist: string[] = [...(options.watchlist ?? [])];
  const tape = options.tape ?? makeTapePrints();

  await page.route('**/api/watchlist', (route) => {
    void route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify({ symbols: watchlist, rows: watchlist.map(makeWatchlistRow), note: null }),
    });
  });
  await json(page, '**/api/concepts/**', makeConcepts());
  await json(page, '**/api/ownership/**', makeOwnership());
  await json(page, '**/api/peers/**', makePeers());
  await json(page, '**/api/filings/**', makeFilings());
  // Order matters: the article and brief routes are registered first so the
  // broader news pattern does not swallow them.
  await json(page, '**/api/news/*/article*', makeArticle());
  await json(page, '**/api/news/*/brief*', makeBrief());
  await json(page, '**/api/news/*', makeNews());
  await json(page, '**/api/setup/*', makeSetup());
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
    // tier, regime, api, then the trading state — eight frames in all.
    ws.send(JSON.stringify(makeStatus({ source, delayed })));
    for (const tier of SCANNER_TIERS) {
      ws.send(JSON.stringify(makeScannerMessage(tier.id, [], scannerAvailable)));
    }
    ws.send(JSON.stringify(makeRegimeMessage()));
    ws.send(JSON.stringify(makeApiUsage()));
    // Sent whether or not trading is armed: with it off the strip has to
    // learn that, rather than rendering as a panel that silently does nothing.
    ws.send(JSON.stringify(makeTradingMessage(options.trading ?? {})));
    // Sent only when there is one, exactly as the server does — an empty list
    // costs a fresh connection no frame at all.
    if (watchlist.length > 0) ws.send(JSON.stringify(makeWatchlistMessage(watchlist)));

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
            // Then the tape it has already printed, as a replacement — the
            // real server sends this frame on every subscribe, empty buffer
            // included, because that empty frame is what clears the previous
            // symbol's prints out of the window.
            ws.send(JSON.stringify(makeTape(symbol, tape)));
            ws.send(JSON.stringify(makeInfo(symbol, infoOverrides)));
          };

          if (snapshotDelayMs > 0) {
            setTimeout(follow, snapshotDelayMs);
          } else {
            follow();
          }
          break;
        }

        case 'watchlist.add': {
          const symbol = text(command.symbol, '').toUpperCase();
          if (symbol && !watchlist.includes(symbol)) watchlist = [...watchlist, symbol];
          ws.send(JSON.stringify(makeWatchlistMessage(watchlist)));
          break;
        }

        case 'watchlist.remove': {
          const symbol = text(command.symbol, '').toUpperCase();
          watchlist = watchlist.filter((entry) => entry !== symbol);
          ws.send(JSON.stringify(makeWatchlistMessage(watchlist)));
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

    pushTape: (prints) => send(makeTape(snapshot?.symbol ?? 'AAPL', prints, false)),

    pushTrading: (overrides = {}) => send(makeTradingMessage({ ...options.trading, ...overrides })),

    pushOrder: (overrides = {}) => send(makeOrder(overrides)),

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
