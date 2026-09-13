/**
 * The panel fetches the list once on mount, for a reload that lands before the
 * socket is up — and must not let that answer undo a push that beat it back.
 */

import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { WatchlistResponse, WatchlistRow } from '@/types/protocol';

import { WatchlistPanel } from './WatchlistPanel';

const INITIAL = useTerminalStore.getState();

function row(symbol: string): WatchlistRow {
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
  };
}

function list(...symbols: string[]): WatchlistResponse {
  return { symbols, rows: symbols.map(row), note: null };
}

afterEach(() => {
  useTerminalStore.setState(INITIAL, true);
});

describe('WatchlistPanel', () => {
  it('fills the list when the fetch answers before the socket', async () => {
    vi.spyOn(api, 'watchlist').mockResolvedValue(list('AAPL'));

    render(<WatchlistPanel onSelect={() => {}} />);

    expect(await screen.findByTestId('watchlist-row-AAPL')).toBeInTheDocument();
  });

  it('keeps a list the socket pushed while the fetch was still out', async () => {
    let answer: (response: WatchlistResponse) => void = () => {};
    vi.spyOn(api, 'watchlist').mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    render(<WatchlistPanel onSelect={() => {}} />);

    act(() => {
      useTerminalStore.getState().setWatchlist(list('AAPL', 'ZZZZ'));
    });
    answer(list('AAPL'));
    await act(() => Promise.resolve());

    expect(screen.getByTestId('watchlist-row-ZZZZ')).toBeInTheDocument();
  });
});
