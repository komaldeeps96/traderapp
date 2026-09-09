/**
 * The main area: the chart, and what else can occupy the same space.
 *
 * The chart is the first tab. The others are the desk work around a position —
 * what the company earns, owns and owes — kept here rather than in the dock
 * because a statement needs the width and the dock is a rail.
 *
 * The chart is hidden with `visibility`, never unmounted. `display:none` would
 * collapse it to zero height and lightweight-charts cannot size a pane inside
 * such a container; unmounting would lose the viewport, and coming back must
 * return the same bars at the same zoom.
 */

export const MAIN_TAB_IDS = [
  'chart',
  'financials',
  'metrics',
  'ownership',
  'peers',
] as const;

export type MainTabId = (typeof MAIN_TAB_IDS)[number];

export const MAIN_TAB_LABELS: Record<MainTabId, string> = {
  chart: 'Chart',
  financials: 'Financials',
  metrics: 'Metrics',
  ownership: 'Insiders',
  peers: 'Peers',
};

/** Spelled out for screen readers and hover. */
export const MAIN_TAB_TITLES: Record<MainTabId, string> = {
  chart: 'Price chart',
  financials: 'Income statement, balance sheet and cash flow',
  metrics: 'Ratios, growth and valuation multiples',
  ownership: 'What insiders have bought and sold',
  peers: 'The same numbers, beside the industry',
};

export const MAIN_DEFAULT_TAB: MainTabId = 'chart';

export function isMainTabId(value: unknown): value is MainTabId {
  return typeof value === 'string' && (MAIN_TAB_IDS as readonly string[]).includes(value);
}
