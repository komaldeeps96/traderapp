/** Which indicators go where: the price pane, the level ladder, a sub-pane. */

import type { IndicatorSpec } from '@/types/protocol';

import { isKeyLevel } from './levels';

/** Indicators drawn on the price pane that are not key levels. */
export function overlayIndicators(
  specs: IndicatorSpec[],
  timeframe: string,
): IndicatorSpec[] {
  return specs.filter(
    (spec) =>
      spec.pane === 'price' &&
      !spec.readout_only &&
      !isKeyLevel(spec) &&
      spec.timeframes[timeframe] !== undefined,
  );
}

export function levelIndicators(specs: IndicatorSpec[], timeframe: string): IndicatorSpec[] {
  return specs.filter((spec) => isKeyLevel(spec) && spec.timeframes[timeframe] !== undefined);
}

export function paneIndicators(specs: IndicatorSpec[], timeframe: string): IndicatorSpec[] {
  return specs.filter(
    (spec) =>
      spec.pane !== 'price' && !spec.readout_only && spec.timeframes[timeframe] !== undefined,
  );
}
