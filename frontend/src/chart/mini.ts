/**
 * The context charts beside the main one.
 *
 * Each follows the main chart's symbol on a timeframe of its owner's choosing
 * (1m over 5m by default, remembered across restarts), so the immediate trend
 * and the day's structure stay visible while the main chart is down on the
 * 10-second tape.
 *
 * Context, not workspaces: candles, EMA 9, EMA 20 and volume, and nothing
 * else. At this size key levels, VWAP, MACD and dollar gridlines stop being
 * information, so the sidebar's indicator toggles do not reach them.
 *
 * Every number worth adjusting lives here.
 */

import { TIMEFRAMES, type Timeframe } from '@/types/protocol';

/** How many mini charts the column holds. */
export const MINI_SLOT_COUNT = 2;

/** What each slot shows until its owner picks something else. */
export const DEFAULT_MINI_TIMEFRAMES: readonly Timeframe[] = ['1m', '5m'];

/** Every timeframe a mini may be set to — the full supported list. */
export const MINI_TIMEFRAME_CHOICES: readonly Timeframe[] = TIMEFRAMES;

/** The only indicators a mini chart draws. */
export const MINI_INCLUDE = ['ema9', 'ema20', 'volume'] as const;

export interface MiniConfig {
  /** Indicator ids to draw. Everything else the timeframe enables is skipped. */
  include: readonly string[];
  /** Bars in view when the chart is framed. */
  visibleBars: number;
  /** Height of the volume pane, px. */
  volumePaneHeight: number;
}

/** Bars in view when a mini is framed — an hour on the 1m, a session on 5m. */
export const MINI_VISIBLE_BARS = 60;

/** One shape for every timeframe: the zoom is remembered per timeframe
 *  anyway, so the framing default only has to be sane, not tailored. */
export function miniConfig(_timeframe: Timeframe): MiniConfig {
  return { include: MINI_INCLUDE, visibleBars: MINI_VISIBLE_BARS, volumePaneHeight: 52 };
}

/** Width of the column, px — the budget the main chart gives up. Wide enough
 *  that a session of 5-minute bars is read rather than squinted at. */
export const MINI_COLUMN_WIDTH = 420;

/**
 * Below this the column is not rendered at all — not merely CSS-hidden. A
 * display:none container is zero-height, and lightweight-charts cannot size a
 * pane inside a chart that has none.
 */
export const MINI_COLUMN_QUERY = '(min-width: 1280px)';
