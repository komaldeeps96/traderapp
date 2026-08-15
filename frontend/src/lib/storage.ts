/**
 * Local preferences.
 *
 * Every read is defensive: a user with storage disabled, or a stale value from
 * an older build, must not stop the terminal from starting.
 */

import type { IndicatorSpec, Timeframe } from '@/types/protocol';

const THEME_KEY = 'traderapp.theme';
const VISIBILITY_KEY = 'traderapp.indicators';

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

export function clearPreferences(): void {
  try {
    localStorage.removeItem(VISIBILITY_KEY);
    localStorage.removeItem(THEME_KEY);
  } catch {
    /* ignore */
  }
}
