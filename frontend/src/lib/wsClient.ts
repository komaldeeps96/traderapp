/**
 * The WebSocket transport.
 *
 * Built to survive a laptop sleeping, a backend restart, and a network that
 * drops silently. Three things do that work:
 *
 *  - exponential backoff with jitter, so a restarting server is not stampeded
 *  - a heartbeat that treats a missing pong as a dead link and forces a
 *    reconnect, because a TCP connection can stay "open" long after it stopped
 *    carrying data
 *  - replaying the last subscription on every open, so a reconnect restores
 *    the chart without the UI having to notice
 *
 * The socket constructor is injectable so all of this is unit-testable without
 * a server.
 */

import type { ClientCommand, ScannerTierId, ServerMessage, Timeframe } from '@/types/protocol';

export type MessageHandler = (message: ServerMessage) => void;
export type StatusHandler = (connected: boolean) => void;

export interface WsClientOptions {
  url: string;
  createSocket?: (url: string) => WebSocket;
  /** How often to ping while idle. */
  heartbeatMs?: number;
  /** How long to wait for a pong before declaring the link dead. */
  heartbeatTimeoutMs?: number;
  initialBackoffMs?: number;
  maxBackoffMs?: number;
  random?: () => number;
}

const DEFAULTS = {
  heartbeatMs: 15_000,
  heartbeatTimeoutMs: 10_000,
  initialBackoffMs: 500,
  maxBackoffMs: 15_000,
};

export class WsClient {
  private socket: WebSocket | null = null;
  private readonly options: Required<WsClientOptions>;
  private messageHandlers = new Set<MessageHandler>();
  private statusHandlers = new Set<StatusHandler>();

  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;

  private visibility = new Map<Timeframe, Record<string, boolean>>();

  private desired: {
    symbol: string;
    timeframe: Timeframe;
    extra_timeframes: Timeframe[];
  } | null = null;
  private closedByUs = false;

  constructor(options: WsClientOptions) {
    this.options = {
      createSocket: (url: string) => new WebSocket(url),
      random: Math.random,
      ...DEFAULTS,
      ...options,
    };
  }

  get connected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  connect(): void {
    this.closedByUs = false;
    this.clearReconnect();

    if (this.socket) {
      const state = this.socket.readyState;
      if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) return;
    }

    const socket = this.options.createSocket(this.options.url);
    this.socket = socket;

    socket.onopen = () => {
      this.reconnectAttempts = 0;
      this.emitStatus(true);
      this.startHeartbeat();
      // Restore whatever the user was looking at before the drop.
      if (this.desired) this.send({ action: 'subscribe', ...this.desired });
      for (const [timeframe, visible] of this.visibility) {
        this.send({ action: 'indicators.visibility', timeframe, visible });
      }
    };

    socket.onmessage = (event: MessageEvent) => {
      let parsed: ServerMessage;
      try {
        parsed = JSON.parse(event.data as string) as ServerMessage;
      } catch {
        return;
      }
      // Any frame proves the link is alive, not just a pong.
      this.clearPongTimer();
      this.messageHandlers.forEach((handler) => handler(parsed));
    };

    socket.onclose = () => {
      this.stopHeartbeat();
      this.emitStatus(false);
      if (!this.closedByUs) this.scheduleReconnect();
    };

    socket.onerror = () => {
      // `onclose` always follows, and it owns reconnection.
    };
  }

  close(): void {
    this.closedByUs = true;
    this.desired = null;
    this.visibility.clear();
    this.clearReconnect();
    this.stopHeartbeat();
    this.socket?.close();
    this.socket = null;
  }

  /**
   * Watch a chart, optionally alongside extra timeframes on the same symbol.
   *
   * The extras are stored with the primary so the replay on reconnect restores
   * every chart the page is showing, not just the main one.
   */
  subscribe(
    symbol: string,
    timeframe: Timeframe,
    extraTimeframes: readonly Timeframe[] = [],
  ): void {
    const next = {
      symbol: symbol.trim().toUpperCase(),
      timeframe,
      extra_timeframes: [...extraTimeframes],
    };
    if (!next.symbol) return;
    this.desired = next;
    this.send({ action: 'subscribe', ...next });
  }

  unsubscribe(): void {
    this.desired = null;
    this.send({ action: 'unsubscribe' });
  }

  configureScanner(
    scannerId: ScannerTierId,
    params: Omit<Extract<ClientCommand, { action: 'scanner.configure' }>, 'action' | 'scanner_id'>,
  ): void {
    this.send({ action: 'scanner.configure', scanner_id: scannerId, ...params });
  }

  /**
   * Which indicators are on for one timeframe.
   *
   * Remembered and replayed on reconnect for the same reason the
   * subscription is — and because it is sent during startup, where it may
   * well be called before the socket has finished opening.
   */
  setIndicatorVisibility(timeframe: Timeframe, visible: Record<string, boolean>): void {
    this.visibility.set(timeframe, visible);
    this.send({ action: 'indicators.visibility', timeframe, visible });
  }

  stopScanner(scannerId: ScannerTierId): void {
    this.send({ action: 'scanner.stop', scanner_id: scannerId });
  }

  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  onStatusChange(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  send(command: ClientCommand): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify(command));
  }

  // ── internals ────────────────────────────────────────────────────────

  private emitStatus(connected: boolean): void {
    this.statusHandlers.forEach((handler) => handler(connected));
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    const { initialBackoffMs, maxBackoffMs, random } = this.options;
    const backoff = Math.min(initialBackoffMs * 2 ** this.reconnectAttempts, maxBackoffMs);
    // Jitter keeps several tabs from reconnecting in lockstep.
    const delay = backoff * (0.5 + random() * 0.5);
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private clearReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (!this.connected) return;
      this.send({ action: 'ping' });
      if (this.pongTimer) return;
      this.pongTimer = setTimeout(() => {
        this.pongTimer = null;
        // Silence past the deadline means the link is dead even though the
        // socket still claims to be open. Force it closed so onclose can
        // schedule a reconnect.
        this.socket?.close();
      }, this.options.heartbeatTimeoutMs);
    }, this.options.heartbeatMs);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    this.clearPongTimer();
  }

  private clearPongTimer(): void {
    if (this.pongTimer) {
      clearTimeout(this.pongTimer);
      this.pongTimer = null;
    }
  }
}

const API_PORT = '8000';

function defaultUrl(): string {
  const override = import.meta.env?.VITE_WS_URL;
  if (override) return override;
  if (typeof window === 'undefined') return `ws://localhost:${API_PORT}/ws`;

  // Same-origin when the API serves the built UI; otherwise Vite is on its own
  // port and the API is still on 8000.
  const { protocol, hostname, port, host } = window.location;
  const scheme = protocol === 'https:' ? 'wss:' : 'ws:';
  const target = port && port !== API_PORT ? `${hostname}:${API_PORT}` : host;
  return `${scheme}//${target}/ws`;
}

export function createWsClient(): WsClient {
  return new WsClient({ url: defaultUrl() });
}
