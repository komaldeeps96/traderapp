/**
 * The left column: what the market is doing, and two ways of asking.
 *
 * The four market-cap panels rank by trade rate and rotation and answer "what
 * is moving *now*" — a question about the tape, so they need IBKR and are dark
 * without TWS.
 *
 * A swing setup asks of daily structure instead: what has been working, and is
 * it at a place worth buying. It answers from TradingView, so that tab fills
 * with nothing else connected.
 *
 * The watchlist is neither — nothing chose those names but the person here.
 *
 * They share the column rather than the screen because only one is ever being
 * acted on, and the key levels below need the height.
 */

export const SCANNER_TAB_IDS = ['day', 'swing', 'watch'] as const;

export type ScannerTabId = (typeof SCANNER_TAB_IDS)[number];

export const SCANNER_TAB_LABELS: Record<ScannerTabId, string> = {
  day: 'Day',
  swing: 'Swing',
  watch: 'Watch',
};

export const SCANNER_TAB_TITLES: Record<ScannerTabId, string> = {
  day: 'Live movers by market-cap tier, from IBKR',
  swing: 'Multi-day setups from daily structure, from TradingView',
  watch: 'Symbols you added, in the order you added them',
};

export const SCANNER_DEFAULT_TAB: ScannerTabId = 'day';

export function isScannerTabId(value: unknown): value is ScannerTabId {
  return typeof value === 'string' && (SCANNER_TAB_IDS as readonly string[]).includes(value);
}
