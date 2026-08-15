/**
 * A stand-in for Alpaca's market data API.
 *
 * The full-stack suite runs the real backend — real provider, real indicator
 * maths, real WebSocket — but pointed at this instead of the live market. That
 * keeps the suite runnable with no credentials, outside market hours, and with
 * data that does not change between runs.
 *
 * Started by Playwright; see webServer in playwright.config.ts.
 */

import { createServer } from 'node:http';

const PORT = Number(process.env.PORT ?? 9899);

// Fixed session so every run produces identical bars.
const SESSION_START = Date.UTC(2024, 2, 5, 9, 0);
const MINUTE = 60_000;
const DAY = 24 * 60 * 60 * 1000;

function seeded(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

function seedFor(symbol) {
  let hash = 7;
  for (const char of symbol) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash;
}

function round(value) {
  return Math.round(value * 100) / 100;
}

function bar(timestamp, close, random) {
  const open = round(close - (random() - 0.5) * 0.08);
  return {
    t: new Date(timestamp).toISOString().replace(/\.\d{3}Z$/, 'Z'),
    o: open,
    h: round(Math.max(open, close) + random() * 0.05),
    l: round(Math.min(open, close) - random() * 0.05),
    c: round(close),
    v: Math.round(2000 + random() * 20000),
    n: Math.round(20 + random() * 200),
    vw: round(close),
  };
}

function minuteBars(symbol, count) {
  const random = seeded(seedFor(symbol));
  const bars = [];
  let price = 10 + (seedFor(symbol) % 7);
  for (let i = 0; i < count; i += 1) {
    price = Math.max(0.5, price + (random() - 0.48) * 0.08);
    bars.push(bar(SESSION_START + i * MINUTE, price, random));
  }
  return bars;
}

function dailyBars(symbol, count) {
  const random = seeded(seedFor(symbol) + 1);
  const bars = [];
  let price = 9 + (seedFor(symbol) % 5);
  // Walk back from the session date, skipping weekends.
  let cursor = SESSION_START - DAY;
  const stamps = [];
  while (stamps.length < count) {
    const day = new Date(cursor).getUTCDay();
    if (day !== 0 && day !== 6) stamps.push(cursor);
    cursor -= DAY;
  }
  stamps.reverse();
  for (const stamp of stamps) {
    price = Math.max(0.5, price + (random() - 0.5) * 0.4);
    bars.push(bar(stamp, price, random));
  }
  return bars;
}

function tapeFor(symbol, count) {
  const random = seeded(seedFor(symbol) + 2);
  const trades = [];
  let price = 10 + (seedFor(symbol) % 7);
  // The tape covers the last hour of the minute-bar session.
  const start = SESSION_START + 330 * MINUTE;
  for (let i = 0; i < count; i += 1) {
    price = Math.max(0.5, price + (random() - 0.5) * 0.02);
    trades.push({
      t: new Date(start + i * 2000).toISOString(),
      p: round(price),
      s: Math.round(50 + random() * 400),
    });
  }
  return trades;
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? '/', `http://localhost:${PORT}`);

  if (url.pathname === '/health') {
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ status: 'ok' }));
    return;
  }

  if (url.pathname === '/v2/stocks/bars') {
    const symbol = (url.searchParams.get('symbols') ?? 'AAPL').split(',')[0];
    const timeframe = url.searchParams.get('timeframe') ?? '1Min';

    // An unknown ticker returns no bars, exactly as Alpaca does.
    const bars =
      symbol === 'NODATA'
        ? []
        : timeframe === '1Day'
          ? dailyBars(symbol, 300)
          : minuteBars(symbol, 390);

    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ bars: { [symbol]: bars }, next_page_token: null }));
    return;
  }

  if (url.pathname === '/v2/stocks/trades') {
    // The raw tape, from which the backend rebuilds 10-second bars. One page,
    // trades two seconds apart across the tail of the fixture session.
    const symbol = (url.searchParams.get('symbols') ?? 'AAPL').split(',')[0];
    const trades = symbol === 'NODATA' ? [] : tapeFor(symbol, 1800);
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ trades: { [symbol]: trades }, next_page_token: null }));
    return;
  }

  response.writeHead(404, { 'content-type': 'application/json' });
  response.end(JSON.stringify({ message: 'not found' }));
});

// The backend also opens a streaming socket. Refusing the upgrade immediately
// leaves it on Alpaca's normal reconnect backoff instead of hanging.
server.on('upgrade', (_request, socket) => {
  socket.destroy();
});

server.listen(PORT, '127.0.0.1', () => {
  process.stdout.write(`alpaca fixture listening on http://127.0.0.1:${PORT}\n`);
});
