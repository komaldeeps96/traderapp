/**
 * Handles on the live chart engines.
 *
 * Each component that owns a chart's DOM node creates its engine and registers
 * it here; the WebSocket wiring and the toolbar both need to reach them.
 * Module-scoped refs are simpler than threading context through every layer,
 * and they keep bars out of React entirely.
 *
 * `getEngine` is the main chart — the one the toolbar drives, the crosshair
 * reads and the store describes. The minis are addressed by slot, because a
 * slot's timeframe is the user's to change; what a message's timeframe maps
 * to lives in the store, not here.
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
