import type { LogicalRange } from 'lightweight-charts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ZoomMemory } from './zoomMemory';

function range(from: number, to: number): () => LogicalRange {
  return () => ({ from, to }) as LogicalRange;
}

describe('ZoomMemory', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('writes once the gesture settles, as a count of bars', () => {
    const memory = new ZoomMemory('main');

    memory.remember('1m', range(50, 149));
    memory.remember('1m', range(10, 109));
    expect(memory.saved('1m')).toBeUndefined();

    vi.advanceTimersByTime(400);
    expect(memory.saved('1m')).toBe(100);
  });

  it('keeps nothing for a view that reaches the first bar', () => {
    const memory = new ZoomMemory('main');
    memory.remember('1m', range(0, 99));
    vi.advanceTimersByTime(400);
    expect(memory.saved('1m')).toBeUndefined();
  });

  it('keeps each timeframe apart', () => {
    const memory = new ZoomMemory('main');
    memory.remember('1m', range(10, 109));
    vi.advanceTimersByTime(400);
    memory.remember('5m', range(10, 59));
    vi.advanceTimersByTime(400);

    expect(memory.saved('1m')).toBe(100);
    expect(memory.saved('5m')).toBe(50);
  });

  it('keeps nothing without a slot', () => {
    const memory = new ZoomMemory(undefined);
    memory.remember('1m', range(10, 109));
    vi.advanceTimersByTime(400);
    expect(memory.saved('1m')).toBeUndefined();
  });

  it('drops a pending write when disposed', () => {
    const memory = new ZoomMemory('main');
    memory.remember('1m', range(10, 109));
    memory.dispose();
    vi.advanceTimersByTime(400);
    expect(memory.saved('1m')).toBeUndefined();
  });
});
