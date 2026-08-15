/**
 * The key levels, grouped into confluence bands.
 *
 * Shared by the chart and the sidebar so both describe the same bands — a
 * level shown as part of a five-deep shelf in the table is drawn as part of
 * that shelf on the chart.
 */

import { useMemo } from 'react';

import { buildKeyLevels, clusterLevels, type LevelCluster } from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';

export interface KeyLevelsView {
  clusters: LevelCluster[];
  /** Price the distances are measured from: the hovered bar, else the live one. */
  price: number | null;
  count: number;
}

export function useKeyLevels(): KeyLevelsView {
  const specs = useTerminalStore((state) => state.specs);
  const visibility = useTerminalStore((state) => state.visibility);
  const theme = useTerminalStore((state) => state.theme);
  const hovered = useTerminalStore((state) => state.hovered);
  const live = useTerminalStore((state) => state.live);

  const readout = hovered ?? live;
  const price = readout?.bar.c ?? null;
  const values = readout?.values;

  return useMemo(() => {
    const levels = buildKeyLevels(specs, values ?? {}, visibility, theme, price);
    return { clusters: clusterLevels(levels, price), price, count: levels.length };
  }, [specs, values, visibility, theme, price]);
}
