import type { IChartApi, ISeriesApi } from 'lightweight-charts';
import { describe, expect, it, vi } from 'vitest';

import type { WireBar } from '@/types/protocol';

import type { MeasureTool } from './measure';
import { MeasureGesture } from './measureGesture';

const BARS: WireBar[] = Array.from({ length: 20 }, (_, i) => ({
  t: 1_709_649_000 + i * 60,
  o: 10,
  h: 10.5,
  l: 9.5,
  c: 10 + i * 0.1,
  v: 100,
  n: 1,
}));

function setup() {
  const container = document.createElement('div');
  const chart = {
    applyOptions: vi.fn(),
    // Ten pixels a bar, so the pointer's x picks the bar directly.
    timeScale: () => ({ coordinateToLogical: (x: number) => x / 10 }),
  };
  const candles = { coordinateToPrice: (y: number) => 100 - y };
  const tool = { clear: vi.fn(), setSelection: vi.fn() };
  const gesture = new MeasureGesture({
    container,
    chart: chart as unknown as IChartApi,
    candles: candles as unknown as ISeriesApi<'Candlestick'>,
    tool: tool as unknown as MeasureTool,
    bars: () => BARS,
    timeframe: () => '1m',
  });
  const pointer = (type: string, x: number, y = 0) =>
    container.dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y }));
  return { container, chart, tool, gesture, pointer };
}

describe('MeasureGesture', () => {
  it('borrows the drag from the chart while on, and gives it back', () => {
    const { container, chart, gesture } = setup();

    gesture.set(true);
    expect(gesture.active).toBe(true);
    expect(chart.applyOptions).toHaveBeenLastCalledWith({ handleScroll: false, handleScale: false });
    expect(container.style.cursor).toBe('crosshair');

    gesture.set(false);
    expect(chart.applyOptions).toHaveBeenLastCalledWith({ handleScroll: true, handleScale: true });
    expect(container.style.cursor).toBe('');
  });

  it('selects between the bars under the press and the pointer', () => {
    const { tool, gesture, pointer } = setup();
    gesture.set(true);

    pointer('pointerdown', 20, 10);
    pointer('pointermove', 80, 5);

    const [anchor, point] = tool.setSelection.mock.calls.at(-1)!;
    expect(anchor).toEqual({ index: 2, time: BARS[2]!.t, price: 90 });
    expect(point).toEqual({ index: 8, time: BARS[8]!.t, price: 95 });
  });

  it('snaps a pointer past the last bar onto it', () => {
    const { tool, gesture, pointer } = setup();
    gesture.set(true);

    pointer('pointerdown', 20);
    pointer('pointermove', 900);

    expect(tool.setSelection.mock.calls.at(-1)![1].index).toBe(BARS.length - 1);
  });

  it('stops listening once off, and clears what it drew', () => {
    const { tool, gesture, pointer } = setup();
    gesture.set(true);
    gesture.set(false);

    pointer('pointerdown', 20);
    pointer('pointermove', 80);

    expect(tool.setSelection).not.toHaveBeenCalled();
    expect(tool.clear).toHaveBeenCalled();
  });
});
