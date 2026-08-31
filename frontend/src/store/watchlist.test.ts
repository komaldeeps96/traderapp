/**
 * The watchlist, as the store sees it.
 *
 * The list lives on the server, so the two edit actions send and do not
 * apply. Everything a window renders arrives on the broadcast that comes
 * back, which is what keeps two open terminals from disagreeing about what
 * is on the list.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import { setCommandSink } from '@/lib/commands';
import type { ClientCommand, WatchlistRow } from '@/types/protocol';

import { useTerminalStore } from './useTerminalStore';

let sent: ClientCommand[] = [];

function row(symbol: string, overrides: Partial<WatchlistRow> = {}): WatchlistRow {
  return {
    symbol,
    name: `${symbol} Inc.`,
    close: 10,
    change: 1.5,
    volume: 1_000_000,
    rvol: 1.2,
    market_cap: 4e8,
    premarket_change: 0,
    next_earnings: null,
    ...overrides,
  };
}

beforeEach(() => {
  sent = [];
  setCommandSink((command) => sent.push(command));
  useTerminalStore.setState({ watchlist: [], watchlistRows: [], watchlistNote: null });
});

describe('watchlist', () => {
  it('sends an add rather than applying it', () => {
    useTerminalStore.getState().addToWatchlist('AAPL');
    expect(sent).toEqual([{ action: 'watchlist.add', symbol: 'AAPL' }]);
    // Nothing shown yet: the server has not said it took.
    expect(useTerminalStore.getState().watchlist).toEqual([]);
  });

  it('upper-cases and trims what it sends', () => {
    useTerminalStore.getState().addToWatchlist('  tsla ');
    expect(sent).toEqual([{ action: 'watchlist.add', symbol: 'TSLA' }]);
  });

  it('does not send a blank symbol', () => {
    useTerminalStore.getState().addToWatchlist('   ');
    expect(sent).toEqual([]);
  });

  it('sends a remove', () => {
    useTerminalStore.getState().removeFromWatchlist('aapl');
    expect(sent).toEqual([{ action: 'watchlist.remove', symbol: 'AAPL' }]);
  });

  it('renders whatever the server broadcasts, in the order given', () => {
    useTerminalStore.getState().setWatchlist({
      symbols: ['ZM', 'AAPL'],
      rows: [row('ZM'), row('AAPL')],
      note: null,
    });
    expect(useTerminalStore.getState().watchlist).toEqual(['ZM', 'AAPL']);
    expect(useTerminalStore.getState().watchlistRows.map((entry) => entry.symbol)).toEqual([
      'ZM',
      'AAPL',
    ]);
  });

  it('replaces the list rather than merging it', () => {
    const store = useTerminalStore.getState();
    store.setWatchlist({ symbols: ['ZM'], rows: [row('ZM')], note: null });
    store.setWatchlist({ symbols: ['AAPL'], rows: [row('AAPL')], note: null });
    expect(useTerminalStore.getState().watchlist).toEqual(['AAPL']);
  });

  it('carries a note when the quotes could not be fetched', () => {
    useTerminalStore.getState().setWatchlist({
      symbols: ['AAPL'],
      rows: [row('AAPL', { close: null })],
      note: 'TradingView did not answer; prices are stale.',
    });
    expect(useTerminalStore.getState().watchlistNote).toContain('stale');
  });

  it('does not throw before the socket is attached', () => {
    setCommandSink(null);
    expect(() => useTerminalStore.getState().addToWatchlist('AAPL')).not.toThrow();
  });
});
