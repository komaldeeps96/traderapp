import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useKeyedState } from './useKeyedState';

describe('useKeyedState', () => {
  it('holds what is set while the key stays put', () => {
    const { result } = renderHook(({ key }) => useKeyedState(key, false), {
      initialProps: { key: 'AAPL' },
    });

    act(() => result.current[1](true));

    expect(result.current[0]).toBe(true);
  });

  it('reads the initial value on the very render the key changes', () => {
    const { result, rerender } = renderHook(({ key }) => useKeyedState(key, false), {
      initialProps: { key: 'AAPL' },
    });
    act(() => result.current[1](true));

    rerender({ key: 'TSLA' });

    expect(result.current[0]).toBe(false);
  });

  it('bases an updater on the value for the current key', () => {
    const { result, rerender } = renderHook(({ key }) => useKeyedState(key, 0), {
      initialProps: { key: 'AAPL' },
    });
    act(() => result.current[1](5));
    rerender({ key: 'TSLA' });

    act(() => result.current[1]((count) => count + 1));

    expect(result.current[0]).toBe(1);
  });

  it('follows a key that is also the initial value', () => {
    const { result, rerender } = renderHook(({ symbol }) => useKeyedState(symbol, symbol), {
      initialProps: { symbol: 'AAPL' },
    });
    act(() => result.current[1]('TS'));
    expect(result.current[0]).toBe('TS');

    rerender({ symbol: 'NVDA' });

    expect(result.current[0]).toBe('NVDA');
  });
});
