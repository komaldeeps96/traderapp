/**
 * The bar-before-snapshot race.
 *
 * Between a symbol switch and its snapshot the chart is cleared. The
 * broadcaster ticks once a second, so a live bar can land in that window;
 * applying it would update() empty series and corrupt the pane's paint
 * state — the "blank chart, populated volume pane" bug. Bars must only
 * flow once the snapshot has made the chart ready.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ChartEngine } from '@/chart/ChartEngine';
import { setEngine, setMiniEngine } from '@/chart/engineRef';
import { useTerminalStore } from '@/store/useTerminalStore';

import { handleMessage } from './useTerminal';

function fakeEngine(barCount = 1) {
  return {
    applyBar: vi.fn(),
    applySnapshot: vi.fn(),
    lastBar: vi.fn(() => ({ t: 100, o: 1, h: 1, l: 1, c: 1, v: 1, n: 1, x: 0 })),
    barCount: vi.fn(() => barCount),
    previousClose: vi.fn(() => null),
    latestValues: vi.fn(() => ({})),
    sessionVolumeAt: vi.fn(() => null),
  };
}

const BAR = {
  type: 'bar',
  symbol: 'BANL',
  timeframe: '10s',
  bar: { t: 100, o: 1, h: 1, l: 1, c: 1, v: 1, n: 1, x: 0 },
  series: { ema9: 1 },
} as const;

describe('handleMessage bar gating', () => {
  let engine: ReturnType<typeof fakeEngine>;

  beforeEach(() => {
    engine = fakeEngine();
    setEngine(engine as unknown as ChartEngine);
    useTerminalStore.getState().requestChart('BANL', '10s');
  });

  it('drops a live bar that races ahead of the snapshot', () => {
    expect(useTerminalStore.getState().status).toBe('loading');

    handleMessage(BAR);

    expect(engine.applyBar).not.toHaveBeenCalled();
  });

  it('applies live bars once the snapshot has landed', () => {
    useTerminalStore
      .getState()
      .chartReady({ symbol: 'BANL', timeframe: '10s', barCount: 1, live: null });

    handleMessage(BAR);

    expect(engine.applyBar).toHaveBeenCalledOnce();
  });

  it('still ignores bars for a chart the user has left', () => {
    useTerminalStore
      .getState()
      .chartReady({ symbol: 'BANL', timeframe: '10s', barCount: 1, live: null });
    useTerminalStore.getState().requestChart('NVDA', '10s');
    useTerminalStore
      .getState()
      .chartReady({ symbol: 'NVDA', timeframe: '10s', barCount: 1, live: null });

    handleMessage(BAR);

    expect(engine.applyBar).not.toHaveBeenCalled();
  });
});

/**
 * The mini charts are fed by timeframe, not by which subscription asked for
 * the data. That is what lets one 1-minute snapshot serve both the mini and a
 * main chart that happens to be on 1m, and what keeps a 1-minute frame off the
 * main chart when it is on the 10-second tape.
 */
describe('handleMessage scanner rows', () => {
  const row = (symbol: string, over: Partial<import('@/types/protocol').ScannerRow> = {}) => ({
    rank: 0,
    symbol,
    exchange: 'NASDAQ',
    price: 2.34,
    pct_change: 34,
    volume: 1e6,
    trades_1m: 100,
    trades_5m: 400,
    dollar_vol_1m: 1e5,
    dollar_vol_5m: 4e5,
    trades_day: null,
    dollar_vol_day: null,
    rank_delta: null,
    entered: false,
    float_shares: null,
    market_cap: null,
    ...over,
  });

  const config = {
    scan_code: 'TOP_TRADE_RATE',
    above_price: null,
    below_price: null,
    above_trade_rate: 500,
    market_cap_above: null,
    market_cap_below: null,
    change_perc_above: null,
    number_of_rows: 15,
  };

  it('keeps one row per symbol, first occurrence winning', () => {
    // The table keys rows by symbol; a duplicate key makes React leave
    // orphaned DOM rows behind, so uniqueness is enforced at the store.
    handleMessage({
      type: 'scanner',
      scanner_id: 'small_cap',
      label: 'Small Cap',
      rows: [row('YJ', { rank: 0 }), row('TNON'), row('YJ', { rank: 2, exchange: 'NYSE' })],
      config,
      running: true,
    });

    const rows = useTerminalStore.getState().scanners.small_cap.rows;
    expect(rows.map((r) => r.symbol)).toEqual(['YJ', 'TNON']);
    expect(rows[0]?.exchange).toBe('NASDAQ');
  });
});

describe('handleMessage mini routing', () => {
  let main: ReturnType<typeof fakeEngine>;
  let minute: ReturnType<typeof fakeEngine>;

  const snapshot = (symbol: string, timeframe: string) =>
    ({
      type: 'snapshot',
      symbol,
      timeframe,
      bars: [{ t: 100, o: 1, h: 1, l: 1, c: 1, v: 1, n: 1 }],
      series: { ema9: [[100, 1]] },
      source: 'ibkr',
      delayed: false,
      generated_at: 100,
    }) as const;

  beforeEach(() => {
    main = fakeEngine();
    minute = fakeEngine(0);
    setEngine(main as unknown as ChartEngine);
    // One slot, showing 1m — the shipped default since the second slot became
    // the time-and-sales window.
    useTerminalStore.getState().setMiniTimeframe(0, '1m');
    setMiniEngine(0, minute as unknown as ChartEngine);
    useTerminalStore.getState().requestChart('BANL', '10s');
    useTerminalStore
      .getState()
      .chartReady({ symbol: 'BANL', timeframe: '10s', barCount: 1, live: null });
  });

  it('draws a 1m snapshot on the mini and not on the main chart', () => {
    handleMessage(snapshot('BANL', '1m') as never);

    expect(minute.applySnapshot).toHaveBeenCalledOnce();
    expect(main.applySnapshot).not.toHaveBeenCalled();
  });

  it('leaves the main chart holding the timeframe it is on', () => {
    useTerminalStore.getState().setMiniTimeframe(0, '5m');

    handleMessage(snapshot('BANL', '5m') as never);

    expect(useTerminalStore.getState().timeframe).toBe('10s');
    expect(minute.applySnapshot).toHaveBeenCalledOnce();
  });

  it('feeds both when the main chart is on the mini timeframe', () => {
    useTerminalStore.getState().requestChart('BANL', '1m');

    handleMessage(snapshot('BANL', '1m') as never);

    expect(main.applySnapshot).toHaveBeenCalledOnce();
    expect(minute.applySnapshot).toHaveBeenCalledOnce();
  });

  it('a retimed slot receives its new timeframe and not its old one', () => {
    useTerminalStore.getState().setMiniTimeframe(0, '15m');

    handleMessage(snapshot('BANL', '1m') as never);
    expect(minute.applySnapshot).not.toHaveBeenCalled();

    handleMessage(snapshot('BANL', '15m') as never);
    expect(minute.applySnapshot).toHaveBeenCalledOnce();
  });

  it('ignores a symbol the user has navigated away from', () => {
    handleMessage(snapshot('NVDA', '1m') as never);

    expect(minute.applySnapshot).not.toHaveBeenCalled();
  });

  it('frames an empty mini on its first real snapshot, then leaves it alone', () => {
    // A 10-second load has no minute base yet, so the mini's opening snapshot
    // carries no bars and the real one arrives with the backfill. Framing on
    // bar count rather than arrival order is what makes both land right.
    handleMessage(snapshot('BANL', '1m') as never);
    expect(minute.applySnapshot.mock.calls[0]![0].resetView).toBe(true);

    minute.barCount.mockReturnValue(240);
    handleMessage(snapshot('BANL', '1m') as never);
    expect(minute.applySnapshot.mock.calls[1]![0].resetView).toBe(false);
  });

  it('does not let the sidebar toggles reach a mini', () => {
    handleMessage(snapshot('BANL', '1m') as never);

    expect(minute.applySnapshot.mock.calls[0]![0].visibility).toEqual({});
  });

  it('routes live bars the same way', () => {
    handleMessage({
      type: 'bar',
      symbol: 'BANL',
      timeframe: '1m',
      bar: { t: 100, o: 1, h: 1, l: 1, c: 1, v: 1, n: 1 },
      series: { ema9: 1 },
    } as never);

    expect(minute.applyBar).toHaveBeenCalledOnce();
    expect(main.applyBar).not.toHaveBeenCalled();
  });
});

/**
 * Time and sales rides the same symbol filter as everything else, and its
 * batches deliberately overlap — the broadcaster's cursor is shared by every
 * client, so a late joiner is sent rows its opening backlog already carried.
 */
describe('handleMessage tape', () => {
  const print = (q: number, over: Partial<import('@/types/protocol').TapePrint> = {}) => ({
    q,
    t: 1_700_000_000_000 + q,
    p: 2.5,
    s: 100,
    a: 'ask' as const,
    ...over,
  });

  const tape = (symbol: string, prints: unknown[], reset = false) =>
    ({ type: 'tape', symbol, reset, prints }) as never;

  beforeEach(() => {
    // The store is a module singleton shared by every spec in this file, and
    // `requestChart` only clears the tape when the *symbol* changes — so a
    // re-request of the same name would leave the previous test's prints in
    // place and quietly satisfy the assertions below.
    useTerminalStore.setState({ tape: [] });
    useTerminalStore.getState().requestChart('BANL', '10s');
  });

  it('holds the newest print first', () => {
    handleMessage(tape('BANL', [print(1), print(2), print(3)], true));

    expect(useTerminalStore.getState().tape.map((row) => row.q)).toEqual([3, 2, 1]);
  });

  it('appends a later batch onto what it holds', () => {
    handleMessage(tape('BANL', [print(1), print(2)], true));
    handleMessage(tape('BANL', [print(3)]));

    expect(useTerminalStore.getState().tape.map((row) => row.q)).toEqual([3, 2, 1]);
  });

  it('drops the overlap between the backlog and the first live batch', () => {
    handleMessage(tape('BANL', [print(1), print(2), print(3)], true));
    handleMessage(tape('BANL', [print(2), print(3), print(4)]));

    expect(useTerminalStore.getState().tape.map((row) => row.q)).toEqual([4, 3, 2, 1]);
  });

  it('a reset replaces rather than appends', () => {
    handleMessage(tape('BANL', [print(1), print(2)], true));
    handleMessage(tape('BANL', [print(1)], true));

    expect(useTerminalStore.getState().tape.map((row) => row.q)).toEqual([1]);
  });

  it('ignores prints for a symbol the user has navigated away from', () => {
    handleMessage(tape('NVDA', [print(1)], true));

    expect(useTerminalStore.getState().tape).toEqual([]);
  });

  it('a symbol switch clears the window before the new tape lands', () => {
    handleMessage(tape('BANL', [print(1)], true));
    useTerminalStore.getState().requestChart('NVDA', '10s');

    expect(useTerminalStore.getState().tape).toEqual([]);
  });
});
