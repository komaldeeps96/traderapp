/**
 * The key levels, grouped into confluence bands.
 *
 * Shared by the chart and the sidebar so both describe the same bands — a
 * level shown as part of a five-deep shelf in the table is drawn as part of
 * that shelf on the chart.
 */

import { memoizeLast } from '@/lib/memo';
import type { Theme } from '@/lib/storage';
import {
  athLevel,
  buildKeyLevels,
  clusterLevels,
  headroom,
  type HeadroomView,
  type KeyLevel,
  type LevelCluster,
} from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { IndicatorSpec, InfoMessage } from '@/types/protocol';

export interface KeyLevelsView {
  clusters: LevelCluster[];
  /** The flat ladder behind the clusters, sorted high to low. */
  levels: KeyLevel[];
  /** Price the distances are measured from: the hovered bar, else the live one. */
  price: number | null;
  count: number;
  /** The nearest level overhead — what decides how far this can run. */
  headroom: HeadroomView | null;
}

// Module-level rather than per hook: the chart, the sidebar and the top panel
// all read the levels on every bar, and they share one computation.
const computeLevels = memoizeLast(
  (
    specs: IndicatorSpec[],
    values: Record<string, number> | undefined,
    visibility: Record<string, boolean>,
    theme: Theme,
    price: number | null,
    info: InfoMessage | null,
  ): KeyLevelsView => {
    const levels = buildKeyLevels(specs, values ?? {}, visibility, theme, price);
    // The all-time high rides the info stream rather than the bar stream, so
    // it is joined here rather than streamed as a series; from this point on
    // it is a level like any other — sorted, clustered and toggled the same.
    const ath = athLevel(info, visibility, price);
    if (ath) levels.push(ath);
    levels.sort((a, b) => b.value - a.value);
    return {
      clusters: clusterLevels(levels, price),
      levels,
      price,
      count: levels.length,
      headroom: headroom(levels, price),
    };
  },
);

export function useKeyLevels(): KeyLevelsView {
  const specs = useTerminalStore((state) => state.specs);
  const visibility = useTerminalStore((state) => state.visibility);
  const theme = useTerminalStore((state) => state.theme);
  const hovered = useTerminalStore((state) => state.hovered);
  const live = useTerminalStore((state) => state.live);
  const info = useTerminalStore((state) => state.info);

  const readout = hovered ?? live;
  return computeLevels(specs, readout?.values, visibility, theme, readout?.bar.c ?? null, info);
}
