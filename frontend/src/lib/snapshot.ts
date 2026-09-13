import type { BarMessage, SeriesMap, SeriesPoint, SnapshotMessage } from '@/types/protocol';

/**
 * A snapshot brought up to date with one live bar, as a new object.
 *
 * A new object rather than an edit: a chart built from the snapshot holds its
 * arrays, and appending to them underneath it would draw the bar twice.
 */
export function withBar(snapshot: SnapshotMessage, message: BarMessage): SnapshotMessage {
  const bars = replaceOrAppend(snapshot.bars, message.bar, (bar) => bar.t);
  const series: SeriesMap = { ...snapshot.series };
  for (const [id, value] of Object.entries(message.series)) {
    const point: SeriesPoint = [message.bar.t, value];
    series[id] = replaceOrAppend(series[id] ?? [], point, (entry) => entry[0]);
  }
  return { ...snapshot, bars, series };
}

function replaceOrAppend<T>(items: T[], item: T, time: (entry: T) => number): T[] {
  const last = items.at(-1);
  if (last === undefined || time(item) > time(last)) return [...items, item];
  if (time(item) === time(last)) return [...items.slice(0, -1), item];
  // Older than the tail: the snapshot already carries that period.
  return items;
}
