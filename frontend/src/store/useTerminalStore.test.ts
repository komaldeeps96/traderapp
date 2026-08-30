/**
 * Indicator visibility, now that the server owns it.
 *
 * The store keeps the whole picture for the chart to draw, and a copy of the
 * deltas so a timeframe switch and back is instant rather than a round trip.
 * What goes out over the socket is the whole picture; the server reduces it.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import { setCommandSink } from '@/lib/commands';
import { defaultVisibility } from '@/lib/storage';
import type { ClientCommand, IndicatorSpec } from '@/types/protocol';

import { useTerminalStore } from './useTerminalStore';

function spec(id: string, timeframes: Record<string, { enabled: boolean }>): IndicatorSpec {
  return {
    id,
    type: 'ema',
    label: id,
    color: '#2a78d6',
    color_dark: '#3987e5',
    pane: 'price',
    readout_only: false,
    line_width: 1,
    line_style: 'solid',
    price_line: false,
    last_value: true,
    group: 'moving_averages',
    timeframes,
  };
}

const SPECS = [
  spec('ema9', { '1m': { enabled: true }, '1d': { enabled: true } }),
  spec('pm_high', { '1m': { enabled: true } }),
  spec('high_52w', { '1m': { enabled: false }, '1d': { enabled: false } }),
];

let sent: ClientCommand[] = [];

beforeEach(() => {
  sent = [];
  setCommandSink((command) => sent.push(command));
  useTerminalStore.setState({
    specs: [],
    visibility: {},
    indicatorOverrides: {},
    timeframe: '1m',
  });
});

describe('indicator visibility', () => {
  it('opens on the configured defaults', () => {
    useTerminalStore.getState().setSpecs(SPECS);
    expect(useTerminalStore.getState().visibility).toEqual(defaultVisibility(SPECS, '1m'));
  });

  it('applies the overrides the server sent', () => {
    useTerminalStore.getState().setIndicatorOverrides({ '1m': { ema9: false } });
    useTerminalStore.getState().setSpecs(SPECS);
    expect(useTerminalStore.getState().visibility.ema9).toBe(false);
  });

  it('sends the whole picture when one indicator is toggled', () => {
    useTerminalStore.getState().setSpecs(SPECS);
    useTerminalStore.getState().toggleIndicator('ema9');

    expect(sent).toEqual([
      {
        action: 'indicators.visibility',
        timeframe: '1m',
        visible: { ...defaultVisibility(SPECS, '1m'), ema9: false },
      },
    ]);
  });

  it('remembers the change as a delta', () => {
    useTerminalStore.getState().setSpecs(SPECS);
    useTerminalStore.getState().toggleIndicator('ema9');
    expect(useTerminalStore.getState().indicatorOverrides).toEqual({ '1m': { ema9: false } });
  });

  it('drops the delta when the indicator is toggled back', () => {
    useTerminalStore.getState().setSpecs(SPECS);
    useTerminalStore.getState().toggleIndicator('ema9');
    useTerminalStore.getState().toggleIndicator('ema9');
    expect(useTerminalStore.getState().indicatorOverrides).toEqual({ '1m': {} });
  });

  it('keeps each timeframe separate', () => {
    useTerminalStore.getState().setSpecs(SPECS);
    useTerminalStore.getState().toggleIndicator('ema9');
    useTerminalStore.getState().requestChart('AAPL', '1d');

    // 1d was never touched, so it opens on its own defaults.
    expect(useTerminalStore.getState().visibility.ema9).toBe(true);
    expect(useTerminalStore.getState().indicatorOverrides).toEqual({ '1m': { ema9: false } });
  });

  it('restores a timeframe’s toggles on the way back', () => {
    useTerminalStore.getState().setSpecs(SPECS);
    useTerminalStore.getState().toggleIndicator('ema9');
    useTerminalStore.getState().requestChart('AAPL', '1d');
    useTerminalStore.getState().requestChart('AAPL', '1m');
    expect(useTerminalStore.getState().visibility.ema9).toBe(false);
  });

  it('sets a whole group at once', () => {
    useTerminalStore.getState().setSpecs(SPECS);
    useTerminalStore.getState().setAllIndicators(['ema9', 'pm_high'], false);
    expect(useTerminalStore.getState().indicatorOverrides).toEqual({
      '1m': { ema9: false, pm_high: false },
    });
  });

  it('does not throw with no socket attached', () => {
    // Commands are dropped before the terminal mounts; the client replays
    // what matters on connect.
    setCommandSink(null);
    useTerminalStore.getState().setSpecs(SPECS);
    expect(() => useTerminalStore.getState().toggleIndicator('ema9')).not.toThrow();
  });
});
