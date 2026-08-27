/**
 * Wires the WebSocket to the chart engine and the store.
 *
 * Incoming market data is filtered against the subscription the user actually
 * has: a snapshot for a symbol they already navigated away from is dropped
 * rather than drawn, which is what stops a slow load from overwriting a fast
 * one.
 */

import { useCallback, useEffect, useRef } from 'react';

import type { ChartEngine } from '@/chart/ChartEngine';
import { getEngine, getMiniEngine, miniEngineEntries } from '@/chart/engineRef';
import { api } from '@/lib/http';
import { applyTheme, loadTheme, saveTheme, type Theme } from '@/lib/storage';
import { createWsClient, type WsClient } from '@/lib/wsClient';
import { useTerminalStore } from '@/store/useTerminalStore';
import type {
  BarMessage,
  ClientCommand,
  ScannerTierId,
  ServerMessage,
  SnapshotMessage,
  Timeframe,
} from '@/types/protocol';

type ScannerOverrides = Omit<
  Extract<ClientCommand, { action: 'scanner.configure' }>,
  'action' | 'scanner_id'
>;

export function useTerminal() {
  const clientRef = useRef<WsClient | null>(null);

  const subscribe = useCallback((symbol: string, timeframe: Timeframe) => {
    const normalised = symbol.trim().toUpperCase();
    if (!normalised) return;
    // A new symbol blanks the canvas at once: the old instrument's candles
    // must not masquerade as the new one while its history loads. A
    // timeframe-only switch keeps the chart — same instrument, near-instant
    // swap from memory. The minis follow the symbol, so they clear with it and
    // survive a timeframe switch untouched.
    if (normalised !== useTerminalStore.getState().symbol) {
      getEngine()?.clear();
      for (const [, engine] of miniEngineEntries()) engine.clear();
    }
    useTerminalStore.getState().requestChart(normalised, timeframe);
    clientRef.current?.subscribe(normalised, timeframe, miniExtras());
  }, []);

  const setMiniTimeframe = useCallback((slot: number, timeframe: Timeframe) => {
    useTerminalStore.getState().setMiniTimeframe(slot, timeframe);
    // The slot's engine is rebuilt by React off the store change; the wire
    // has to follow, or the fresh chart would wait forever for a timeframe
    // nobody subscribed to.
    const { symbol, timeframe: main } = useTerminalStore.getState();
    if (symbol) clientRef.current?.subscribe(symbol, main, miniExtras());
  }, []);

  const setTimeframe = useCallback(
    (timeframe: Timeframe) => {
      const { symbol } = useTerminalStore.getState();
      if (symbol) subscribe(symbol, timeframe);
    },
    [subscribe],
  );

  const toggleIndicator = useCallback((id: string) => {
    useTerminalStore.getState().toggleIndicator(id);
    const visible = useTerminalStore.getState().visibility[id] ?? false;
    getEngine()?.setIndicatorVisible(id, visible);
  }, []);

  const setIndicatorGroup = useCallback((ids: string[], visible: boolean) => {
    useTerminalStore.getState().setAllIndicators(ids, visible);
    const engine = getEngine();
    for (const id of ids) engine?.setIndicatorVisible(id, visible);
  }, []);

  const configureScanner = useCallback((scannerId: ScannerTierId, overrides: ScannerOverrides) => {
    clientRef.current?.configureScanner(scannerId, overrides);
  }, []);

  // The charts are not repainted here. Each one subscribes to the store's
  // theme and repaints itself, which is the only route the minis have — doing
  // it here as well would leave the main chart's palette wired in two places
  // and the others in one.
  const toggleTheme = useCallback(() => {
    const next: Theme = useTerminalStore.getState().theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    saveTheme(next);
    useTerminalStore.getState().setTheme(next);
  }, []);

  useEffect(() => {
    const theme = loadTheme();
    applyTheme(theme);
    useTerminalStore.getState().setTheme(theme);

    const controller = new AbortController();

    // Configuration first: without the indicator specs the chart cannot build
    // its series, so the opening subscribe waits for them.
    void (async () => {
      try {
        const [specs, scanner] = await Promise.all([
          api.indicators(controller.signal),
          api.scannerTiers(controller.signal),
        ]);
        useTerminalStore.getState().setSpecs(specs);
        useTerminalStore.getState().setScannerTiers({
          note: scanner.note,
          scanCodes: scanner.scan_codes,
        });

        const session = await api.session(controller.signal);
        subscribe(session.symbol, session.timeframe);
      } catch {
        if (!controller.signal.aborted) {
          useTerminalStore
            .getState()
            .setError('Could not reach the backend. Is it running on port 8000?');
        }
      }
    })();

    const client = createWsClient();
    clientRef.current = client;

    const offMessage = client.onMessage(handleMessage);
    const offStatus = client.onStatusChange((connected) => {
      useTerminalStore.getState().setConnected(connected);
    });
    client.connect();

    return () => {
      controller.abort();
      offMessage();
      offStatus();
      client.close();
      clientRef.current = null;
    };
  }, [subscribe]);

  return {
    subscribe,
    setTimeframe,
    setMiniTimeframe,
    toggleIndicator,
    setIndicatorGroup,
    configureScanner,
    toggleTheme,
  };
}

// ── message handling ───────────────────────────────────────────────────

export function handleMessage(message: ServerMessage): void {
  const store = useTerminalStore.getState();

  switch (message.type) {
    case 'status':
      store.setSourceStatus({
        source: message.source,
        delayed: message.delayed,
        ibkrConnected: message.ibkr_connected,
        alpacaAvailable: message.alpaca_available,
        note: message.message,
      });
      break;

    case 'snapshot': {
      // The minis are fed first and independently: the same 1-minute snapshot
      // legitimately belongs to both when the main chart is also on 1m.
      applyMiniSnapshot(message);
      if (!isCurrent(message.symbol, message.timeframe)) return;
      const engine = getEngine();
      if (!engine) return;

      engine.applySnapshot({
        bars: message.bars,
        series: message.series,
        specs: store.specs,
        timeframe: message.timeframe,
        visibility: store.visibility,
        // The first snapshot for a request frames the view; a repeat on the
        // same chart is a background backfill and must not move the viewport
        // under the user.
        resetView: store.status !== 'ready',
      });

      const last = engine.lastBar();
      store.chartReady({
        symbol: message.symbol,
        timeframe: message.timeframe,
        barCount: engine.barCount(),
        live: last
          ? {
              bar: last,
              previousClose: engine.previousClose(last.t),
              values: engine.latestValues(),
              sessionVolume: engine.sessionVolumeAt(last.t),
            }
          : null,
      });
      break;
    }

    case 'bar': {
      applyMiniBar(message);
      if (!isCurrent(message.symbol, message.timeframe)) return;
      // Between a symbol switch and its snapshot the chart is cleared; a
      // live bar racing ahead of the snapshot would update() empty series,
      // which corrupts the pane's paint state and blanks the chart until
      // the next clear. The snapshot carries this bar anyway.
      if (store.status !== 'ready') return;
      const engine = getEngine();
      if (!engine) return;

      engine.applyBar(message.bar, message.series);
      store.setLive(
        {
          bar: message.bar,
          previousClose: engine.previousClose(message.bar.t),
          values: message.series,
          sessionVolume: engine.sessionVolumeAt(message.bar.t),
        },
        engine.barCount(),
      );
      break;
    }

    case 'quote':
      // Quotes are per-symbol; one for a chart the user has left is stale.
      if (message.symbol === store.symbol) store.setQuote(message);
      break;

    case 'info':
      if (message.symbol === store.symbol) {
        store.setInfo(message);
        getEngine()?.setAllTimeHigh(message.all_time_high);
      }
      break;

    case 'api':
      store.setApiUsage(message);
      break;

    case 'scanner':
      store.setScanner(message.scanner_id, {
        label: message.label,
        rows: message.rows,
        config: message.config,
        running: message.running,
      });
      break;

    case 'regime':
      store.setRegime({
        regime: message.regime,
        running: message.running,
        error: message.error,
      });
      break;

    case 'error':
      store.setError(message.message);
      break;

    case 'pong':
      break;
  }
}

function isCurrent(symbol: string, timeframe: string): boolean {
  const state = useTerminalStore.getState();
  return state.symbol === symbol && state.timeframe === timeframe;
}

/** The extra timeframes a subscribe carries: one per mini slot, deduped —
 *  two slots on the same timeframe are one subscription on the wire. */
function miniExtras(): Timeframe[] {
  return [...new Set(useTerminalStore.getState().miniTimeframes)];
}

/**
 * The mini charts a message feeds, possibly none.
 *
 * They follow the main chart's symbol and nothing else, so a message for a
 * symbol the user has navigated away from is dropped exactly as it is for the
 * main chart. Slots are matched by their chosen timeframe; two slots on the
 * same timeframe both draw the one message.
 */
function minisFor(symbol: string, timeframe: string): ChartEngine[] {
  const state = useTerminalStore.getState();
  if (symbol !== state.symbol) return [];
  const engines: ChartEngine[] = [];
  state.miniTimeframes.forEach((choice, slot) => {
    if (choice !== timeframe) return;
    const engine = getMiniEngine(slot);
    if (engine) engines.push(engine);
  });
  return engines;
}

function applyMiniSnapshot(message: SnapshotMessage): void {
  for (const engine of minisFor(message.symbol, message.timeframe)) applyToMini(engine, message);
}

function applyToMini(engine: ChartEngine, message: SnapshotMessage): void {
  engine.applySnapshot({
    bars: message.bars,
    series: message.series,
    specs: useTerminalStore.getState().specs,
    timeframe: message.timeframe,
    // Not the store's visibility map: the sidebar toggles belong to the main
    // chart, and a mini already draws only what its allow-list permits. An
    // empty map means "everything the engine built", which is those three.
    visibility: {},
    // The first snapshot for a symbol frames the view. A 10-second load has no
    // minute base yet, so that first snapshot is often empty and the real one
    // arrives with the backfill — framing on bars, not on arrival order, is
    // what makes both cases land right.
    resetView: engine.barCount() === 0,
  });
}

function applyMiniBar(message: BarMessage): void {
  for (const engine of minisFor(message.symbol, message.timeframe)) {
    engine.applyBar(message.bar, message.series);
  }
}
