/**
 * The key levels, grouped into confluence bands.
 *
 * Shared by the chart and the sidebar so both describe the same bands — a
 * level shown as part of a five-deep shelf in the table is drawn as part of
 * that shelf on the chart.
 */

import { useMemo } from 'react';

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

export function useKeyLevels(): KeyLevelsView {
  const specs = useTerminalStore((state) => state.specs);
  const visibility = useTerminalStore((state) => state.visibility);
  const theme = useTerminalStore((state) => state.theme);
  const hovered = useTerminalStore((state) => state.hovered);
  const live = useTerminalStore((state) => state.live);
  const info = useTerminalStore((state) => state.info);

  const readout = hovered ?? live;
  const price = readout?.bar.c ?? null;
  const values = readout?.values;

  return useMemo(() => {
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
  }, [specs, values, visibility, theme, price, info]);
}
