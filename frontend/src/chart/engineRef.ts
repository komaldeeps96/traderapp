/**
 * Handles on the live chart engines.
 *
 * Each component owning a chart's DOM node registers its engine here, for the
 * WebSocket wiring and the toolbar to reach. Module-scoped refs keep bars out
 * of React entirely.
 *
 * `getEngine` is the main chart. The minis are addressed by slot, since a
 * slot's timeframe is the user's to change; the mapping lives in the store.
 */

import type { ChartEngine } from './ChartEngine';

export const engineRef: { current: ChartEngine | null } = { current: null };

const miniEngines = new Map<number, ChartEngine>();

export function setEngine(engine: ChartEngine | null): void {
  engineRef.current = engine;
}

export function getEngine(): ChartEngine | null {
  return engineRef.current;
}

export function setMiniEngine(slot: number, engine: ChartEngine | null): void {
  if (engine) miniEngines.set(slot, engine);
  else miniEngines.delete(slot);
}

export function getMiniEngine(slot: number): ChartEngine | null {
  return miniEngines.get(slot) ?? null;
}

export function miniEngineEntries(): Array<[number, ChartEngine]> {
  return [...miniEngines];
}
