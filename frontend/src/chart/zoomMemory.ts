import type { LogicalRange } from 'lightweight-charts';

import { loadZoom, saveZoom } from '@/lib/storage';

// How long a zoom gesture has to settle before its width is persisted.
const ZOOM_SAVE_DELAY_MS = 400;

/**
 * The visible bar count, kept under `{slot}:{timeframe}` so a restart keeps
 * the zoom that was dialled in. With no slot nothing is kept.
 */
export class ZoomMemory {
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly slot: string | undefined) {}

  /** The saved width for a timeframe, if any. */
  saved(timeframe: string): number | undefined {
    return this.slot ? (loadZoom(this.key(timeframe)) ?? undefined) : undefined;
  }

  /**
   * Write the width back, debounced: the range changes on every wheel notch
   * and drag frame, and localStorage writes are synchronous.
   */
  remember(timeframe: string, range: () => LogicalRange | null): void {
    if (!this.slot) return;
    const key = this.key(timeframe);
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      const current = range();
      // A view reaching the first bar was sized by the data, not the user: a
      // twenty-bar listing would otherwise become every weekly chart's width.
      if (!current || current.from <= 0) return;
      // A bar count, as resetView takes it: logical a to b shows b - a + 1.
      saveZoom(key, current.to - current.from + 1);
    }, ZOOM_SAVE_DELAY_MS);
  }

  dispose(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private key(timeframe: string): string {
    return `${this.slot}:${timeframe}`;
  }
}
