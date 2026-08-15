import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ServerMessage } from '@/types/protocol';

import { WsClient } from './wsClient';

/** A WebSocket stand-in whose lifecycle the test drives by hand. */
class FakeSocket {
  static instances: FakeSocket[] = [];

  readyState: number = WebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    if (this.readyState === WebSocket.CLOSED) return;
    this.readyState = WebSocket.CLOSED;
    this.onclose?.();
  }

  // ── test controls ──
  open() {
    this.readyState = WebSocket.OPEN;
    this.onopen?.();
  }

  emit(message: ServerMessage) {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
  }

  emitRaw(data: string) {
    this.onmessage?.({ data } as MessageEvent);
  }

  get commands(): Array<Record<string, unknown>> {
    return this.sent.map((entry) => JSON.parse(entry) as Record<string, unknown>);
  }

  static latest(): FakeSocket {
    const socket = FakeSocket.instances.at(-1);
    if (!socket) throw new Error('no socket was created');
    return socket;
  }

  static reset() {
    FakeSocket.instances = [];
  }
}

function makeClient(overrides: Partial<ConstructorParameters<typeof WsClient>[0]> = {}) {
  return new WsClient({
    url: 'ws://test/ws',
    createSocket: (url) => new FakeSocket(url) as unknown as WebSocket,
    // Deterministic backoff: no jitter randomness in tests.
    random: () => 1,
    ...overrides,
  });
}

describe('WsClient', () => {
  beforeEach(() => {
    FakeSocket.reset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('connecting', () => {
    it('opens a socket', () => {
      makeClient().connect();
      expect(FakeSocket.instances).toHaveLength(1);
    });

    it('reports connection status', () => {
      const client = makeClient();
      const states: boolean[] = [];
      client.onStatusChange((connected) => states.push(connected));

      client.connect();
      FakeSocket.latest().open();
      expect(states).toEqual([true]);
    });

    it('does not open a second socket while one is live', () => {
      const client = makeClient();
      client.connect();
      FakeSocket.latest().open();
      client.connect();
      expect(FakeSocket.instances).toHaveLength(1);
    });
  });

  describe('messages', () => {
    it('delivers parsed messages', () => {
      const client = makeClient();
      const seen: ServerMessage[] = [];
      client.onMessage((message) => seen.push(message));

      client.connect();
      FakeSocket.latest().open();
      FakeSocket.latest().emit({ type: 'pong' });

      expect(seen).toEqual([{ type: 'pong' }]);
    });

    it('ignores unparseable frames instead of throwing', () => {
      const client = makeClient();
      const seen: ServerMessage[] = [];
      client.onMessage((message) => seen.push(message));

      client.connect();
      FakeSocket.latest().open();
      expect(() => FakeSocket.latest().emitRaw('{oops')).not.toThrow();
      expect(seen).toHaveLength(0);
    });

    it('stops delivering after unsubscribing a handler', () => {
      const client = makeClient();
      const seen: ServerMessage[] = [];
      const off = client.onMessage((message) => seen.push(message));

      client.connect();
      FakeSocket.latest().open();
      off();
      FakeSocket.latest().emit({ type: 'pong' });

      expect(seen).toHaveLength(0);
    });
  });

  describe('subscribing', () => {
    it('sends a subscribe command', () => {
      const client = makeClient();
      client.connect();
      FakeSocket.latest().open();
      client.subscribe('aapl', '5m');

      expect(FakeSocket.latest().commands).toContainEqual({
        action: 'subscribe',
        symbol: 'AAPL',
        timeframe: '5m',
        extra_timeframes: [],
      });
    });

    it('ignores an empty symbol', () => {
      const client = makeClient();
      client.connect();
      FakeSocket.latest().open();
      client.subscribe('   ', '1m');
      expect(FakeSocket.latest().commands).toHaveLength(0);
    });

    it('queues nothing while disconnected', () => {
      const client = makeClient();
      client.connect();
      client.subscribe('AAPL', '1m');
      expect(FakeSocket.latest().sent).toHaveLength(0);
    });

    it('replays the subscription when the socket opens', () => {
      const client = makeClient();
      client.connect();
      client.subscribe('AAPL', '1m');
      FakeSocket.latest().open();

      expect(FakeSocket.latest().commands).toContainEqual({
        action: 'subscribe',
        symbol: 'AAPL',
        timeframe: '1m',
        extra_timeframes: [],
      });
    });
  });

  describe('reconnecting', () => {
    it('reopens after an unexpected close', () => {
      const client = makeClient({ initialBackoffMs: 100 });
      client.connect();
      FakeSocket.latest().open();
      FakeSocket.latest().close();

      vi.advanceTimersByTime(100);
      expect(FakeSocket.instances).toHaveLength(2);
    });

    it('backs off further on each failure', () => {
      const client = makeClient({ initialBackoffMs: 100 });
      client.connect();
      FakeSocket.latest().open();

      FakeSocket.latest().close();
      vi.advanceTimersByTime(100);
      expect(FakeSocket.instances).toHaveLength(2);

      // Second failure waits twice as long, so the first tick is too early.
      FakeSocket.latest().close();
      vi.advanceTimersByTime(100);
      expect(FakeSocket.instances).toHaveLength(2);

      vi.advanceTimersByTime(100);
      expect(FakeSocket.instances).toHaveLength(3);
    });

    it('caps the backoff', () => {
      const client = makeClient({ initialBackoffMs: 1000, maxBackoffMs: 2000 });
      client.connect();
      FakeSocket.latest().open();

      for (let attempt = 0; attempt < 6; attempt += 1) {
        FakeSocket.latest().close();
        vi.advanceTimersByTime(2000);
      }
      expect(FakeSocket.instances.length).toBeGreaterThan(5);
    });

    it('restores the chart subscription after a reconnect', () => {
      const client = makeClient({ initialBackoffMs: 100 });
      client.connect();
      FakeSocket.latest().open();
      client.subscribe('TSLA', '15m');

      FakeSocket.latest().close();
      vi.advanceTimersByTime(100);
      FakeSocket.latest().open();

      expect(FakeSocket.latest().commands).toContainEqual({
        action: 'subscribe',
        symbol: 'TSLA',
        timeframe: '15m',
        extra_timeframes: [],
      });
    });

    it('restores the mini charts too', () => {
      // Replaying only the primary would leave the 1m and 5m charts frozen on
      // whatever they held before the drop, with no sign anything was wrong.
      const client = makeClient({ initialBackoffMs: 100 });
      client.connect();
      FakeSocket.latest().open();
      client.subscribe('TSLA', '10s', ['1m', '5m']);

      FakeSocket.latest().close();
      vi.advanceTimersByTime(100);
      FakeSocket.latest().open();

      expect(FakeSocket.latest().commands).toContainEqual({
        action: 'subscribe',
        symbol: 'TSLA',
        timeframe: '10s',
        extra_timeframes: ['1m', '5m'],
      });
    });

    it('does not reconnect after an intentional close', () => {
      const client = makeClient({ initialBackoffMs: 100 });
      client.connect();
      FakeSocket.latest().open();
      client.close();

      vi.advanceTimersByTime(5000);
      expect(FakeSocket.instances).toHaveLength(1);
    });
  });

  describe('heartbeat', () => {
    it('pings while idle', () => {
      const client = makeClient({ heartbeatMs: 1000 });
      client.connect();
      FakeSocket.latest().open();

      vi.advanceTimersByTime(1000);
      expect(FakeSocket.latest().commands).toContainEqual({ action: 'ping' });
    });

    it('closes a link that stops answering', () => {
      // A TCP connection can stay "open" long after it stops carrying data;
      // silence past the deadline is the only way to notice.
      const client = makeClient({ heartbeatMs: 1000, heartbeatTimeoutMs: 500 });
      client.connect();
      FakeSocket.latest().open();

      vi.advanceTimersByTime(1000);
      vi.advanceTimersByTime(500);

      expect(FakeSocket.latest().readyState).toBe(WebSocket.CLOSED);
    });

    it('keeps the link when any frame arrives', () => {
      const client = makeClient({ heartbeatMs: 1000, heartbeatTimeoutMs: 500 });
      client.connect();
      FakeSocket.latest().open();

      vi.advanceTimersByTime(1000);
      FakeSocket.latest().emit({ type: 'pong' });
      vi.advanceTimersByTime(500);

      expect(FakeSocket.latest().readyState).toBe(WebSocket.OPEN);
    });

    it('stops pinging once closed', () => {
      const client = makeClient({ heartbeatMs: 1000 });
      client.connect();
      FakeSocket.latest().open();
      const socket = FakeSocket.latest();
      client.close();

      const before = socket.sent.length;
      vi.advanceTimersByTime(5000);
      expect(socket.sent).toHaveLength(before);
    });
  });

  describe('scanner commands', () => {
    it('sends filters', () => {
      const client = makeClient();
      client.connect();
      FakeSocket.latest().open();
      client.configureScanner({ scan_code: 'MOST_ACTIVE', above_price: 2 });

      expect(FakeSocket.latest().commands).toContainEqual({
        action: 'scanner.configure',
        scan_code: 'MOST_ACTIVE',
        above_price: 2,
      });
    });

    it('sends a stop', () => {
      const client = makeClient();
      client.connect();
      FakeSocket.latest().open();
      client.stopScanner();
      expect(FakeSocket.latest().commands).toContainEqual({ action: 'scanner.stop' });
    });
  });
});
