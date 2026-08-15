/**
 * Handles on the live chart engines.
 *
 * Each component that owns a chart's DOM node creates its engine and registers
 * it here; the WebSocket wiring and the toolbar both need to reach them.
 * Module-scoped refs are simpler than threading context through every layer,
 * and they keep bars out of React entirely.
 *
 * `getEngine` is the main chart — the one the toolbar drives, the crosshair
 * reads and the store describes. The minis are addressed by timeframe.
 */

import type { ChartEngine } from './ChartEngine';
import type { MiniTimeframe } from './mini';

export const engineRef: { current: ChartEngine | null } = { current: null };

const miniEngines = new Map<MiniTimeframe, ChartEngine>();

export function setEngine(engine: ChartEngine | null): void {
  engineRef.current = engine;
}

export function getEngine(): ChartEngine | null {
  return engineRef.current;
}

export function setMiniEngine(timeframe: MiniTimeframe, engine: ChartEngine | null): void {
  if (engine) miniEngines.set(timeframe, engine);
  else miniEngines.delete(timeframe);
}

export function getMiniEngine(timeframe: MiniTimeframe): ChartEngine | null {
  return miniEngines.get(timeframe) ?? null;
}

export function miniEngineEntries(): Array<[MiniTimeframe, ChartEngine]> {
  return [...miniEngines];
}
