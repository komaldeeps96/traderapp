/**
 * The right-hand dock: the rail beside the chart, and what it can show.
 *
 * The context charts are the first tab and the default. The other three are
 * the pre-trade check — what the company is, what it has said, what it has
 * filed — in the order they are reached for.
 *
 * The width is the budget the main chart gives up, so it is the user's to set:
 * dragged from the rail's left edge and remembered.
 *
 * Every number worth adjusting lives here.
 */

import { MINI_COLUMN_WIDTH } from '@/chart/mini';

export const DOCK_TAB_IDS = ['charts', 'fundamentals', 'news', 'filings'] as const;

export type DockTabId = (typeof DOCK_TAB_IDS)[number];

export const DOCK_TAB_LABELS: Record<DockTabId, string> = {
  charts: 'Charts',
  fundamentals: 'Fund',
  news: 'News',
  filings: 'Filings',
};

/** Spelled out for screen readers, where the abbreviations do not help. */
export const DOCK_TAB_TITLES: Record<DockTabId, string> = {
  charts: 'Context charts',
  fundamentals: 'Fundamentals and dilution',
  news: 'News',
  filings: 'SEC filings',
};

export const DOCK_DEFAULT_TAB: DockTabId = 'charts';

/** The width the mini charts were tuned to; the dock inherits it. */
export const DOCK_DEFAULT_WIDTH = MINI_COLUMN_WIDTH;

/** Narrower than this and a filing row wraps to three lines; wider and the
 *  main chart stops being the main chart. */
export const DOCK_MIN_WIDTH = 300;
export const DOCK_MAX_WIDTH = 760;

export function isDockTabId(value: unknown): value is DockTabId {
  return typeof value === 'string' && (DOCK_TAB_IDS as readonly string[]).includes(value);
}

export function clampDockWidth(width: number): number {
  if (!Number.isFinite(width)) return DOCK_DEFAULT_WIDTH;
  return Math.min(DOCK_MAX_WIDTH, Math.max(DOCK_MIN_WIDTH, Math.round(width)));
}
