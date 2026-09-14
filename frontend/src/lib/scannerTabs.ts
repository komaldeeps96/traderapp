/**
 * The left column: what the market is doing, and what the person here chose.
 *
 * The four market-cap panels rank by trade rate and rotation — a question
 * about the tape, so they need IBKR and are dark without TWS. The watchlist
 * holds names nothing chose but the person here.
 *
 * They share the column because only one is acted on at a time, and the key
 * levels below need the height.
 */

export const SCANNER_TAB_IDS = ['day', 'watch'] as const;

export type ScannerTabId = (typeof SCANNER_TAB_IDS)[number];

export const SCANNER_TAB_LABELS: Record<ScannerTabId, string> = {
  day: 'Day',
  watch: 'Watch',
};

export const SCANNER_TAB_TITLES: Record<ScannerTabId, string> = {
  day: 'Live movers by market-cap tier, from IBKR',
  watch: 'Symbols you added, in the order you added them',
};

export const SCANNER_DEFAULT_TAB: ScannerTabId = 'day';

export function isScannerTabId(value: unknown): value is ScannerTabId {
  return typeof value === 'string' && (SCANNER_TAB_IDS as readonly string[]).includes(value);
}
