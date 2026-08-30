import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { IndicatorSpec } from '@/types/protocol';

import {
  defaultVisibility,
  loadDockTab,
  loadDockWidth,
  loadTheme,
  loadVisibility,
  loadZoom,
  saveDockTab,
  saveDockWidth,
  saveTheme,
  saveVisibility,
  saveZoom,
} from './storage';
import { DOCK_DEFAULT_WIDTH, DOCK_MAX_WIDTH, DOCK_MIN_WIDTH } from './dock';

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
  spec('high_52w', { '1m': { enabled: false } }),
];

describe('zoom persistence', () => {
  beforeEach(() => localStorage.clear());

  it('is empty before anything was saved', () => {
    expect(loadZoom('main:10s')).toBeNull();
  });

  it('round-trips a width per slot and timeframe', () => {
    saveZoom('main:10s', 120);
    saveZoom('mini:1m', 60);
    expect(loadZoom('main:10s')).toBe(120);
    expect(loadZoom('mini:1m')).toBe(60);
    expect(loadZoom('main:1m')).toBeNull();
  });

  it('rounds fractional logical widths', () => {
    saveZoom('main:10s', 119.6);
    expect(loadZoom('main:10s')).toBe(120);
  });

  it('refuses to save or load an absurd width', () => {
    saveZoom('main:10s', 2);
    expect(loadZoom('main:10s')).toBeNull();
    saveZoom('main:10s', 1_000_000);
    expect(loadZoom('main:10s')).toBeNull();
    localStorage.setItem('traderapp.zoom', JSON.stringify({ 'main:10s': 'wide' }));
    expect(loadZoom('main:10s')).toBeNull();
  });

  it('falls back when storage holds junk', () => {
    localStorage.setItem('traderapp.zoom', 'not json');
    expect(loadZoom('main:10s')).toBeNull();
  });
});

describe('defaultVisibility', () => {
  beforeEach(() => localStorage.clear());

  it('follows the configured defaults', () => {
    expect(defaultVisibility(SPECS, '1m')).toEqual({
      ema9: true,
      pm_high: true,
      high_52w: false,
    });
  });

  it('omits indicators not on the timeframe', () => {
    expect(defaultVisibility(SPECS, '1d')).toEqual({ ema9: true });
  });
});

describe('visibility persistence', () => {
  beforeEach(() => localStorage.clear());

  it('starts from the defaults', () => {
    expect(loadVisibility(SPECS, '1m')).toEqual(defaultVisibility(SPECS, '1m'));
  });

  it('remembers a change', () => {
    saveVisibility('1m', { ema9: false, pm_high: true, high_52w: false });
    expect(loadVisibility(SPECS, '1m').ema9).toBe(false);
  });

  it('keeps timeframes separate', () => {
    // The levels wanted on a 1-minute chart are rarely the ones wanted daily.
    saveVisibility('1m', { ema9: false });
    expect(loadVisibility(SPECS, '1d').ema9).toBe(true);
  });

  it('ignores saved entries for indicators that no longer exist', () => {
    saveVisibility('1m', { removed_indicator: true, ema9: true });
    expect(loadVisibility(SPECS, '1m')).not.toHaveProperty('removed_indicator');
  });

  it('ignores an indicator saved under the wrong timeframe', () => {
    saveVisibility('1d', { pm_high: true });
    expect(loadVisibility(SPECS, '1d')).not.toHaveProperty('pm_high');
  });

  it('falls back to defaults when storage holds junk', () => {
    localStorage.setItem('traderapp.indicators', 'not json');
    expect(loadVisibility(SPECS, '1m')).toEqual(defaultVisibility(SPECS, '1m'));
  });

  it('survives storage being unavailable', () => {
    // Private browsing and a full quota both surface as a throwing setItem;
    // losing a preference must never take the terminal down with it.
    const spy = vi.spyOn(globalThis.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    expect(() => saveVisibility('1m', { ema9: false })).not.toThrow();
    spy.mockRestore();
  });
});

describe('theme persistence', () => {
  beforeEach(() => localStorage.clear());

  it('round-trips a saved theme', () => {
    saveTheme('dark');
    expect(loadTheme()).toBe('dark');
  });

  it('defaults to dark — this is a terminal', () => {
    expect(loadTheme()).toBe('dark');
  });

  it('honours an explicit light preference', () => {
    saveTheme('light');
    expect(loadTheme()).toBe('light');
  });

  it('ignores an unrecognised stored value', () => {
    localStorage.setItem('traderapp.theme', 'neon');
    expect(loadTheme()).toBe('dark');
  });
});

describe('dock persistence', () => {
  beforeEach(() => localStorage.clear());

  it('opens on the context charts until told otherwise', () => {
    expect(loadDockTab()).toBe('charts');
  });

  it('round-trips a chosen tab', () => {
    saveDockTab('fundamentals');
    expect(loadDockTab()).toBe('fundamentals');
  });

  it('falls back to the charts when a saved tab no longer exists', () => {
    localStorage.setItem('traderapp.dockTab', 'options');
    expect(loadDockTab()).toBe('charts');
  });

  it('starts at the width the mini charts were tuned to', () => {
    expect(loadDockWidth()).toBe(DOCK_DEFAULT_WIDTH);
  });

  it('round-trips a dragged width', () => {
    saveDockWidth(500);
    expect(loadDockWidth()).toBe(500);
  });

  it('clamps a width from a build with different bounds rather than discarding it', () => {
    // The intent was "as wide as possible"; the nearest legal wide is closer
    // to that than the default would be.
    localStorage.setItem('traderapp.dockWidth', '4000');
    expect(loadDockWidth()).toBe(DOCK_MAX_WIDTH);
    localStorage.setItem('traderapp.dockWidth', '20');
    expect(loadDockWidth()).toBe(DOCK_MIN_WIDTH);
  });

  it('ignores a corrupt width', () => {
    localStorage.setItem('traderapp.dockWidth', 'wide');
    expect(loadDockWidth()).toBe(DOCK_DEFAULT_WIDTH);
  });

  it('survives storage being unavailable', () => {
    const spy = vi.spyOn(globalThis.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    expect(() => saveDockWidth(400)).not.toThrow();
    expect(() => saveDockTab('news')).not.toThrow();
    spy.mockRestore();
  });
});
