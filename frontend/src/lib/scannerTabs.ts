/**
 * The left column: what the market is doing, and two ways of asking.
 *
 * The four market-cap panels are a day-trading instrument. They rank by trade
 * rate and rotation and answer "what is moving *now*", which is a question
 * about the tape — so they need IBKR, and they are dark whenever TWS is not
 * running.
 *
 * A swing setup is a different question, asked of daily structure rather than
 * of the tape: what has been working, and is it at a place worth buying. It
 * answers from TradingView, so that tab still fills with nothing else
 * connected.
 *
 * The watchlist is neither: nothing chose those names but the person sitting
 * here. It shares the column because it answers the same question the two
 * screens do — what to look at next — and because a name is usually put on it
 * *from* one of them.
 *
 * They share the column rather than the screen because only one of them is
 * ever being acted on, and the key levels below need the height.
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
