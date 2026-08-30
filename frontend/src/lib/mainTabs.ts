/**
 * The main area: the chart, and what else can occupy the same space.
 *
 * The chart is the first tab and stays the reason the terminal exists. The
 * others are the desk work around a position — what the company earns, owns
 * and owes — kept here rather than in the right-hand dock because a
 * statement needs the width and the dock is a rail.
 *
 * The chart is never unmounted when another tab is open, only hidden with
 * `visibility`. `display:none` would collapse it to zero height, and
 * lightweight-charts cannot size a pane inside a container that has none —
 * the dock hit exactly that and unmounts its charts instead. Unmounting is
 * not an option here: coming back to the chart must return it to the same
 * bars, at the same zoom, not reset to the right edge.
 */

export const MAIN_TAB_IDS = ['chart', 'financials', 'metrics', 'ownership'] as const;

export type MainTabId = (typeof MAIN_TAB_IDS)[number];

export const MAIN_TAB_LABELS: Record<MainTabId, string> = {
  chart: 'Chart',
  financials: 'Financials',
  metrics: 'Metrics',
  ownership: 'Insiders',
};

/** Spelled out for screen readers and hover. */
export const MAIN_TAB_TITLES: Record<MainTabId, string> = {
  chart: 'Price chart',
  financials: 'Income statement, balance sheet and cash flow',
  metrics: 'Ratios, growth and valuation multiples',
  ownership: 'What insiders have bought and sold',
};

export const MAIN_DEFAULT_TAB: MainTabId = 'chart';

export function isMainTabId(value: unknown): value is MainTabId {
  return typeof value === 'string' && (MAIN_TAB_IDS as readonly string[]).includes(value);
}
