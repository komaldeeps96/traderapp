import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { IndicatorSpec } from '@/types/protocol';

import {
  defaultVisibility,
  loadDockTab,
  loadDockWidth,
  loadNewsAi,
  loadTheme,
  loadVisibility,
  loadZoom,
  saveDockTab,
  saveDockWidth,
  saveNewsAi,
  saveTheme,
  takeLegacyVisibility,
  visibilityOverrides,
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

describe('visibility', () => {
  beforeEach(() => localStorage.clear());

  it('starts from the defaults', () => {
    expect(loadVisibility(SPECS, '1m')).toEqual(defaultVisibility(SPECS, '1m'));
  });

  it('applies a server override', () => {
    expect(loadVisibility(SPECS, '1m', { ema9: false }).ema9).toBe(false);
  });

  it('leaves untouched indicators following the config', () => {
    // The point of storing deltas: changing a default in indicators.yaml has
    // to reach a chart the user never touched.
    expect(loadVisibility(SPECS, '1m', { ema9: false }).pm_high).toBe(
      defaultVisibility(SPECS, '1m').pm_high,
    );
  });

  it('ignores overrides for indicators that no longer exist', () => {
    expect(loadVisibility(SPECS, '1m', { removed_indicator: true })).not.toHaveProperty(
      'removed_indicator',
    );
  });

  it('ignores an indicator overridden on the wrong timeframe', () => {
    expect(loadVisibility(SPECS, '1d', { pm_high: true })).not.toHaveProperty('pm_high');
  });
});

describe('visibilityOverrides', () => {
  it('keeps only what differs from the defaults', () => {
    const visibility = { ...defaultVisibility(SPECS, '1m'), ema9: false };
    expect(visibilityOverrides(SPECS, '1m', visibility)).toEqual({ ema9: false });
  });

  it('is empty when nothing was changed', () => {
    expect(visibilityOverrides(SPECS, '1m', defaultVisibility(SPECS, '1m'))).toEqual({});
  });

  it('drops ids the timeframe does not have', () => {
    expect(visibilityOverrides(SPECS, '1d', { pm_high: false, ema9: false })).toEqual({
      ema9: false,
    });
  });

  it('round-trips through loadVisibility', () => {
    const wanted = { ...defaultVisibility(SPECS, '1m'), ema9: false, pm_high: false };
    expect(loadVisibility(SPECS, '1m', visibilityOverrides(SPECS, '1m', wanted))).toEqual(wanted);
  });
});

describe('takeLegacyVisibility', () => {
  beforeEach(() => localStorage.clear());

  it('reads what the browser used to hold', () => {
    localStorage.setItem('traderapp.indicators', JSON.stringify({ '1m': { ema9: false } }));
    expect(takeLegacyVisibility()).toEqual({ '1m': { ema9: false } });
  });

  it('consumes it, so the migration happens once', () => {
    localStorage.setItem('traderapp.indicators', JSON.stringify({ '1m': { ema9: false } }));
    takeLegacyVisibility();
    expect(takeLegacyVisibility()).toEqual({});
  });

  it('is empty when there was nothing saved', () => {
    expect(takeLegacyVisibility()).toEqual({});
  });

  it('survives junk in storage', () => {
    localStorage.setItem('traderapp.indicators', 'not json');
    expect(takeLegacyVisibility()).toEqual({});
  });

  it('drops non-boolean entries rather than migrating them', () => {
    localStorage.setItem(
      'traderapp.indicators',
      JSON.stringify({ '1m': { ema9: 'yes' }, '1d': { ema9: false } }),
    );
    expect(takeLegacyVisibility()).toEqual({ '1d': { ema9: false } });
  });

  it('survives storage being unavailable', () => {
    // Private browsing and a full quota both surface as a throwing call;
    // losing a preference must never take the terminal down with it.
    const spy = vi.spyOn(globalThis.localStorage, 'removeItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    expect(() => takeLegacyVisibility()).not.toThrow();
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

describe('the AI news summary switch', () => {
  it('defaults on — it is the point of the panel', () => {
    expect(loadNewsAi()).toBe(true);
  });

  it('round-trips off', () => {
    saveNewsAi(false);
    expect(loadNewsAi()).toBe(false);
    saveNewsAi(true);
    expect(loadNewsAi()).toBe(true);
  });

  it('treats a corrupt value as on rather than silently disabling the panel', () => {
    localStorage.setItem('traderapp.newsAi', 'maybe');
    expect(loadNewsAi()).toBe(true);
  });

  it('survives storage being unavailable', () => {
    const spy = vi.spyOn(globalThis.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(loadNewsAi()).toBe(true);
    spy.mockRestore();
  });
});
