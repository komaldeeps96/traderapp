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
import {
  MAIN_DEFAULT_TAB,
  isMainTabId,
  type MainTabId,
} from '@/lib/mainTabs';
import {
  clampDockWidth,
  isDockTabId,
  DOCK_DEFAULT_TAB,
  DOCK_DEFAULT_WIDTH,
  type DockTabId,
} from '@/lib/dock';
import type { IndicatorSpec, Timeframe } from '@/types/protocol';

const THEME_KEY = 'traderapp.theme';
const VISIBILITY_KEY = 'traderapp.indicators';
const ZOOM_KEY = 'traderapp.zoom';
const MINI_TF_KEY = 'traderapp.miniTimeframes';
const DOCK_TAB_KEY = 'traderapp.dockTab';
const MAIN_TAB_KEY = 'traderapp.mainTab';
const DOCK_WIDTH_KEY = 'traderapp.dockWidth';

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
 *
 * The saved half now lives on the server, in `state.yaml`, and arrives as
 * *overrides* — only what the user changed. Applying them over the config's
 * own defaults is what lets a changed default in `indicators.yaml` reach a
 * chart the user never touched, instead of being masked forever by a saved
 * copy of the old value.
 */
export function loadVisibility(
  specs: IndicatorSpec[],
  timeframe: Timeframe,
  overrides: Record<string, boolean> = {},
): Record<string, boolean> {
  const defaults = defaultVisibility(specs, timeframe);

  const result: Record<string, boolean> = { ...defaults };
  for (const [id, visible] of Object.entries(overrides)) {
    // Only honour entries for indicators that still exist on this timeframe,
    // so removing one from the YAML cannot resurrect it.
    if (id in defaults && typeof visible === 'boolean') result[id] = visible;
  }
  return result;
}

/**
 * What the user had toggled back when this was a browser preference.
 *
 * Read once and deleted, so the upgrade keeps the toggles someone had built
 * up rather than silently resetting their charts to the defaults. Anything
 * the server already knows about wins — it is the newer of the two.
 */
export function takeLegacyVisibility(): VisibilityStore {
  const saved = readJson<VisibilityStore>(VISIBILITY_KEY, {});
  try {
    localStorage.removeItem(VISIBILITY_KEY);
  } catch {
    // Storage disabled: there was nothing to migrate anyway.
  }
  const result: VisibilityStore = {};
  for (const [timeframe, entries] of Object.entries(saved)) {
    if (!entries || typeof entries !== 'object') continue;
    const clean: Record<string, boolean> = {};
    for (const [id, visible] of Object.entries(entries)) {
      if (typeof visible === 'boolean') clean[id] = visible;
    }
    if (Object.keys(clean).length) result[timeframe] = clean;
  }
  return result;
}

/** What differs from the configured defaults — the only part worth storing. */
export function visibilityOverrides(
  specs: IndicatorSpec[],
  timeframe: Timeframe,
  visibility: Record<string, boolean>,
): Record<string, boolean> {
  const defaults = defaultVisibility(specs, timeframe);
  const overrides: Record<string, boolean> = {};
  for (const [id, visible] of Object.entries(visibility)) {
    if (id in defaults && defaults[id] !== visible) overrides[id] = visible;
  }
  return overrides;
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

/**
 * Which dock tab was last open, and how wide the rail was dragged.
 *
 * A tab removed from a later build falls back to the charts rather than
 * leaving the dock showing nothing, and a width from a build with different
 * bounds is clamped into the current ones instead of being discarded — the
 * user's intent was "wide", and the nearest legal wide is closer to it than
 * the default.
 */
export function loadDockTab(): DockTabId {
  try {
    const saved = localStorage.getItem(DOCK_TAB_KEY);
    return isDockTabId(saved) ? saved : DOCK_DEFAULT_TAB;
  } catch {
    return DOCK_DEFAULT_TAB;
  }
}

export function saveDockTab(tab: DockTabId): void {
  try {
    localStorage.setItem(DOCK_TAB_KEY, tab);
  } catch {
    /* ignore */
  }
}

export function loadDockWidth(): number {
  try {
    const saved = Number(localStorage.getItem(DOCK_WIDTH_KEY));
    return saved > 0 ? clampDockWidth(saved) : DOCK_DEFAULT_WIDTH;
  } catch {
    return DOCK_DEFAULT_WIDTH;
  }
}

export function saveDockWidth(width: number): void {
  try {
    localStorage.setItem(DOCK_WIDTH_KEY, String(clampDockWidth(width)));
  } catch {
    /* ignore */
  }
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

/**
 * Which main-area tab was last open.
 *
 * A tab removed by a later build falls back to the chart rather than leaving
 * the middle of the terminal blank.
 */
export function loadMainTab(): MainTabId {
  try {
    const saved = localStorage.getItem(MAIN_TAB_KEY);
    return isMainTabId(saved) ? saved : MAIN_DEFAULT_TAB;
  } catch {
    return MAIN_DEFAULT_TAB;
  }
}

export function saveMainTab(tab: MainTabId): void {
  try {
    localStorage.setItem(MAIN_TAB_KEY, tab);
  } catch {
    // Private browsing or a full quota: the tab simply does not persist.
  }
}
