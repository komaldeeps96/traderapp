/**
 * The context chart beside the main one.
 *
 * One chart following whatever symbol the main chart is on, on a timeframe of
 * its owner's choosing (1m by default, remembered across restarts). It exists
 * so the immediate trend stays visible while the main chart is down on the
 * 10-second tape.
 *
 * There were two of these. The second slot is now the time-and-sales window
 * (`components/TapePanel.tsx`), which answers a question no chart does: a
 * 5-minute candle is a summary of what the tape already said, and on a
 * small-cap runner the tape says it first. The timeframe picker survives, so
 * the one chart can be put on 5m by anyone who would rather have it.
 *
 * It is context, not a workspace: candles, EMA 9, EMA 20 and volume, and
 * nothing else. No key levels, no VWAP, no MACD, no dollar gridlines — at this
 * size those stop being information and become texture. The sidebar's
 * indicator toggles deliberately do not reach it.
 *
 * Every number worth adjusting lives here.
 */

import { TIMEFRAMES, type Timeframe } from '@/types/protocol';

/** How many mini charts the column holds. */
export const MINI_SLOT_COUNT = 1;

/** What each slot shows until its owner picks something else. */
export const DEFAULT_MINI_TIMEFRAMES: readonly Timeframe[] = ['1m'];

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
 *  that a session of 5-minute bars is read rather than squinted at, and that
 *  the tape below it fits time, price, size and venue without wrapping. */
export const MINI_COLUMN_WIDTH = 420;

/**
 * The chart's share of the charts tab, as a flex weight against the tape's.
 *
 * The tape gets the larger half. A chart at this width is read for its shape,
 * which survives being short; a tape is read for how many rows are on screen,
 * and twenty is where it stops being a trickle.
 */
export const MINI_CHART_FLEX = 4;
export const TAPE_FLEX = 6;

/**
 * Below this the column is not rendered at all.
 *
 * Not a CSS `hidden`: a display:none container is zero-height, and building a
 * chart engine on one means asking lightweight-charts to give a pane a height
 * inside a chart that has none. Cheaper and safer not to build it.
 */
export const MINI_COLUMN_QUERY = '(min-width: 1280px)';
