import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useNow } from './useNow';

describe('useNow', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-14T13:30:20Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('reads the clock floored to the step', () => {
    const { result } = renderHook(() => useNow(60_000));
    expect(result.current).toBe(Date.UTC(2026, 8, 14, 13, 30) / 1000);
  });

  it('moves on when the step turns over', () => {
    const { result } = renderHook(() => useNow(60_000));

    act(() => {
      vi.advanceTimersByTime(60_000);
    });

    expect(result.current).toBe(Date.UTC(2026, 8, 14, 13, 31) / 1000);
  });
});
