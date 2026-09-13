import { sessionVolumes } from '@/lib/session';
import type { SeriesPoint, WireBar } from '@/types/protocol';

/**
 * The bars and indicator values a chart holds, indexed by bar time for the
 * crosshair readouts. No canvas: every lookup here is testable without one.
 */
export class BarData {
  private list: WireBar[] = [];
  private index = new Map<number, number>();
  private values = new Map<string, Map<number, number>>();
  /** Session-cumulative volume per bar; built when first asked for. */
  private sessionVolume: number[] | null = null;

  get bars(): readonly WireBar[] {
    return this.list;
  }

  get count(): number {
    return this.list.length;
  }

  load(bars: WireBar[]): void {
    this.list = bars;
    this.index = new Map(bars.map((bar, position) => [bar.t, position]));
    this.sessionVolume = null;
  }

  /** A new period is appended; a period already held is revised in place. */
  upsert(bar: WireBar): void {
    const position = this.index.get(bar.t);
    if (position === undefined) {
      this.list.push(bar);
      this.index.set(bar.t, this.list.length - 1);
    } else {
      this.list[position] = bar;
    }
    this.sessionVolume = null;
  }

  clear(): void {
    this.list = [];
    this.index.clear();
    this.values.clear();
    this.sessionVolume = null;
  }

  indexOf(time: number): number | undefined {
    return this.index.get(time);
  }

  at(time: number): WireBar | null {
    const position = this.index.get(time);
    return position === undefined ? null : (this.list[position] ?? null);
  }

  last(): WireBar | null {
    return this.list.at(-1) ?? null;
  }

  /** The close of the bar before `time`, for the change readout. */
  previousClose(time: number): number | null {
    const position = this.index.get(time);
    if (position === undefined || position <= 0) return null;
    return this.list[position - 1]?.c ?? null;
  }

  /** The session's cumulative volume as of the bar at `time`. */
  sessionVolumeAt(time: number): number | null {
    const position = this.index.get(time);
    if (position === undefined) return null;
    this.sessionVolume ??= sessionVolumes(this.list);
    return this.sessionVolume[position] ?? null;
  }

  setSeries(id: string, points: readonly SeriesPoint[]): void {
    this.values.set(id, new Map(points));
  }

  dropSeries(id: string): void {
    this.values.delete(id);
  }

  clearSeries(): void {
    this.values.clear();
  }

  remember(id: string, time: number, value: number): void {
    let lookup = this.values.get(id);
    if (!lookup) {
      lookup = new Map();
      this.values.set(id, lookup);
    }
    lookup.set(time, value);
  }

  /**
   * Indicator values at a timestamp.
   *
   * Key-level series are stored compressed (two points per constant run), so an
   * exact hit is rare and the value in effect is the newest point at or before
   * the time asked for.
   */
  valuesAt(time: number): Record<string, number> {
    const values: Record<string, number> = {};
    for (const [id, lookup] of this.values) {
      const exact = lookup.get(time);
      if (exact !== undefined) {
        values[id] = exact;
        continue;
      }
      let bestTime = -Infinity;
      let bestValue: number | undefined;
      for (const [pointTime, value] of lookup) {
        if (pointTime <= time && pointTime > bestTime) {
          bestTime = pointTime;
          bestValue = value;
        }
      }
      if (bestValue !== undefined) values[id] = bestValue;
    }
    return values;
  }

  /**
   * The newest value of one series.
   *
   * Points are not in time order — a live update appends to whatever the
   * snapshot left — so this scans rather than peeking at the end.
   */
  latestValue(id: string): number | undefined {
    const lookup = this.values.get(id);
    if (!lookup) return undefined;
    let bestTime = -Infinity;
    let bestValue: number | undefined;
    for (const [pointTime, value] of lookup) {
      if (pointTime > bestTime) {
        bestTime = pointTime;
        bestValue = value;
      }
    }
    return bestValue;
  }

  latestValues(): Record<string, number> {
    const values: Record<string, number> = {};
    for (const id of this.values.keys()) {
      const value = this.latestValue(id);
      if (value !== undefined) values[id] = value;
    }
    return values;
  }

  pointCounts(): Record<string, number> {
    return Object.fromEntries([...this.values].map(([id, lookup]) => [id, lookup.size]));
  }
}
