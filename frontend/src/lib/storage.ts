/**
 * Local preferences.
 *
 * Every read is defensive: a user with storage disabled, or a stale value from
 * an older build, must not stop the terminal from starting.
 */

import {
  DEFAULT_MINI_TIMEFRAMES,
  MINI_SLOT_COUNT,
  MINI_TIMEFRAME_CHOICES,
} from '@/chart/mini';
import type { IndicatorSpec, Timeframe } from '@/types/protocol';

const THEME_KEY = 'traderapp.theme';
const VISIBILITY_KEY = 'traderapp.indicators';
const ZOOM_KEY = 'traderapp.zoom';
const MINI_TF_KEY = 'traderapp.miniTimeframes';

// A saved zoom outside these bounds is a corrupt value, not a preference.
const ZOOM_MIN_BARS = 10;
const ZOOM_MAX_BARS = 5000;

export type Theme = 'light' | 'dark';

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === 'object' ? (parsed as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Private browsing or a full quota: preferences simply do not persist.
  }
}

export function loadTheme(): Theme {
  // A terminal defaults to dark; light stays one click away.
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
    return 'dark';
  } catch {
    return 'dark';
  }
}

export function saveTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* ignore */
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

type VisibilityStore = Record<string, Record<string, boolean>>;

/**
 * Indicator visibility is remembered per timeframe: the levels you want on a
 * 1-minute chart are rarely the ones you want on a daily.
 */
export function loadVisibility(
  specs: IndicatorSpec[],
  timeframe: Timeframe,
): Record<string, boolean> {
  const defaults = defaultVisibility(specs, timeframe);
  const saved = readJson<VisibilityStore>(VISIBILITY_KEY, {})[timeframe] ?? {};

  const result: Record<string, boolean> = { ...defaults };
  for (const [id, visible] of Object.entries(saved)) {
    // Only honour saved entries for indicators that still exist on this
    // timeframe, so removing one from the YAML cannot resurrect it.
    if (id in defaults && typeof visible === 'boolean') result[id] = visible;
  }
  return result;
}

export function saveVisibility(timeframe: Timeframe, visibility: Record<string, boolean>): void {
  const store = readJson<VisibilityStore>(VISIBILITY_KEY, {});
  store[timeframe] = visibility;
  writeJson(VISIBILITY_KEY, store);
}

/**
 * Which timeframe each mini-chart slot shows. Validated per slot, so a stale
 * or hand-edited entry costs that one slot its saved choice, not both.
 */
export function loadMiniTimeframes(): Timeframe[] {
  const saved = readJson<unknown[]>(MINI_TF_KEY, []);
  return Array.from({ length: MINI_SLOT_COUNT }, (_, slot) => {
    const value = Array.isArray(saved) ? saved[slot] : undefined;
    if (typeof value === 'string' && (MINI_TIMEFRAME_CHOICES as readonly string[]).includes(value)) {
      return value as Timeframe;
    }
    return DEFAULT_MINI_TIMEFRAMES[slot] ?? '1m';
  });
}

export function saveMiniTimeframes(timeframes: readonly Timeframe[]): void {
  writeJson(MINI_TF_KEY, [...timeframes]);
}

type ZoomStore = Record<string, number>;

/**
 * Chart zoom is remembered per slot and timeframe (`main:10s`, `mini:1m`):
 * the width you read a 10-second tape at is never the width you want on the
 * daily, and the minis are deliberately tighter than the main chart.
 */
export function loadZoom(key: string): number | null {
  const saved = readJson<ZoomStore>(ZOOM_KEY, {})[key];
  if (typeof saved !== 'number' || !Number.isFinite(saved)) return null;
  if (saved < ZOOM_MIN_BARS || saved > ZOOM_MAX_BARS) return null;
  return Math.round(saved);
}

export function saveZoom(key: string, visibleBars: number): void {
  if (!Number.isFinite(visibleBars)) return;
  const width = Math.round(visibleBars);
  if (width < ZOOM_MIN_BARS || width > ZOOM_MAX_BARS) return;
  const store = readJson<ZoomStore>(ZOOM_KEY, {});
  store[key] = width;
  writeJson(ZOOM_KEY, store);
}

export function defaultVisibility(
  specs: IndicatorSpec[],
  timeframe: Timeframe,
): Record<string, boolean> {
  const defaults: Record<string, boolean> = {};
  for (const spec of specs) {
    const option = spec.timeframes[timeframe];
    if (option) defaults[spec.id] = option.enabled;
  }
  return defaults;
}
