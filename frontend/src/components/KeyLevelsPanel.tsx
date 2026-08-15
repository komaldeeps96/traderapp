import { useLayoutEffect, useRef } from 'react';

import { formatPercent, formatPrice } from '@/lib/format';
import { centredScrollTop } from '@/lib/scroll';
import { useKeyLevels } from '@/hooks/useKeyLevels';
import type { LevelCluster } from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';

import { EyeToggle } from './EyeToggle';

interface KeyLevelsPanelProps {
  onToggle: (id: string) => void;
  onToggleGroup: (ids: string[], visible: boolean) => void;
}

/**
 * Key levels, grouped into confluence bands and sorted by price.
 *
 * This is the momentum workflow. The list runs high to low with the last trade
 * slotted into its true position, so the band directly above the marker is the
 * next thing in the way and the one below is the first thing that would catch
 * a pullback — those two are coloured, everything else stays quiet.
 *
 * Levels sitting at effectively the same price collapse into one band with a
 * strength count, because five levels on one shelf is a far stronger read than
 * five separate lines, and drawn separately they were unreadable on a
 * sub-dollar ticker.
 */
export function KeyLevelsPanel({ onToggle, onToggleGroup }: KeyLevelsPanelProps) {
  const { clusters, price, count } = useKeyLevels();
  const symbol = useTerminalStore((state) => state.symbol);

  const above = clusters.filter((cluster) => cluster.side === 'above');
  const below = clusters.filter((cluster) => cluster.side !== 'above');

  // The marker's place in the list is decided by how many bands sit above it,
  // so that count is exactly when the scroll needs redoing.
  const { scrollRef, markerRef } = useCentreOnLast(`${symbol}:${above.length}:${clusters.length}`);

  return (
    <section className="flex min-h-0 flex-1 flex-col" data-testid="key-levels">
      <div className="flex items-center justify-between px-2.5 pb-1.5 pt-2.5">
        <h2 className="text-[10px] font-bold uppercase tracking-wider text-ink-3">Key levels</h2>
        <span className="text-[9px] font-semibold text-ink-3" data-testid="key-levels-count">
          {count} in {clusters.length} band{clusters.length === 1 ? '' : 's'}
        </span>
      </div>

      {clusters.length === 0 ? (
        <p className="px-2.5 py-4 text-[11px] text-ink-3">
          Levels appear once daily history has loaded.
        </p>
      ) : (
        <div ref={scrollRef} className="scroll-thin min-h-0 flex-1 overflow-y-auto">
          {/* Fixed layout: a band's member list is long, and in an auto table
              it grows the label column until price and distance are squeezed
              to nothing. */}
          <table className="w-full table-fixed border-collapse text-left">
            <caption className="sr-only">
              Key price levels grouped into bands, sorted from highest to lowest, with distance
              from the last price
            </caption>
            <colgroup>
              <col className="w-6" />
              <col />
              <col className="w-[74px]" />
              <col className="w-[54px]" />
            </colgroup>
            <thead className="sticky top-0 z-10 bg-panel">
              <tr className="text-[9px] font-bold uppercase tracking-wider text-ink-3">
                <th scope="col" className="pb-1" />
                <th scope="col" className="pb-1 pl-1">
                  Level
                </th>
                <th scope="col" className="pb-1 pr-2 text-right">
                  Price
                </th>
                <th scope="col" className="pb-1 pr-2 text-right">
                  Dist
                </th>
              </tr>
            </thead>
            <tbody>
              {above.map((cluster) => (
                <BandRow
                  key={cluster.key}
                  cluster={cluster}
                  onToggle={onToggle}
                  onToggleGroup={onToggleGroup}
                />
              ))}

              {price != null && (
                <tr ref={markerRef} data-testid="price-marker" className="bg-accent/10">
                  <td />
                  <td className="py-1 pl-1 text-[10px] font-bold uppercase tracking-wide text-ink">
                    Last
                  </td>
                  <td className="tnum py-1 pr-2 text-right font-mono text-[11px] font-bold text-ink">
                    {formatPrice(price)}
                  </td>
                  <td />
                </tr>
              )}

              {below.map((cluster) => (
                <BandRow
                  key={cluster.key}
                  cluster={cluster}
                  onToggle={onToggle}
                  onToggleGroup={onToggleGroup}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * Keep the last-price row in the middle of the panel.
 *
 * On a gapper with two dozen levels overhead — a whole quarter's and year's
 * highs stacked above a sub-dollar price — the marker lands so far down the
 * list that the panel opens on levels nobody is trading against, and the price
 * has to be scrolled to. Centring it puts the next resistance and the first
 * support either side of the marker, which is the read the panel exists for.
 *
 * The clamp is what handles an unbalanced book. With nothing above, there is
 * no scroll to give and the marker simply sits at the top; with nothing below,
 * at the bottom. So "centred" quietly becomes "as centred as the levels allow"
 * rather than padding the list out with empty space.
 *
 * It re-centres only when the marker actually changes place in the list — when
 * price crosses a level, or the symbol changes — not on every tick. Scrolling
 * up to check the 52-week high would otherwise be yanked back a second later.
 */
function useCentreOnLast(anchor: string) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const markerRef = useRef<HTMLTableRowElement>(null);

  useLayoutEffect(() => {
    const container = scrollRef.current;
    const marker = markerRef.current;
    if (!container || !marker) return;

    // Measured rather than read off offsetTop: a row's offsetParent inside a
    // table is not the scroll container, so offsetTop is not its distance.
    const containerBox = container.getBoundingClientRect();
    const markerBox = marker.getBoundingClientRect();

    container.scrollTop = centredScrollTop({
      rowOffset: markerBox.top - containerBox.top + container.scrollTop,
      rowHeight: markerBox.height,
      viewportHeight: container.clientHeight,
      contentHeight: container.scrollHeight,
    });
  }, [anchor]);

  return { scrollRef, markerRef };
}

const EMPHASIS_TEXT = {
  resistance: 'text-down',
  support: 'text-up',
  normal: 'text-ink-3',
} as const;

const EMPHASIS_BAR = {
  resistance: 'bg-down',
  support: 'bg-up',
  normal: 'bg-ink-3/40',
} as const;

function BandRow({
  cluster,
  onToggle,
  onToggleGroup,
}: {
  cluster: LevelCluster;
  onToggle: (id: string) => void;
  onToggleGroup: (ids: string[], visible: boolean) => void;
}) {
  const stacked = cluster.strength > 1;
  const anyVisible = cluster.members.some((member) => member.visible);
  const ids = cluster.members.map((member) => member.id);
  const lead = cluster.members[0]!;

  return (
    <tr
      className={`border-t border-line/60 hover:bg-elevated ${
        cluster.emphasis === 'normal' ? '' : 'bg-elevated'
      }`}
      data-testid={`level-row-${cluster.key}`}
      data-strength={cluster.strength}
      data-emphasis={cluster.emphasis}
      data-side={cluster.side}
      data-value={cluster.value}
    >
      <td className="py-1 pl-1.5 align-top">
        <EyeToggle
          visible={anyVisible}
          label={stacked ? `${cluster.strength} levels at ${formatPrice(cluster.value)}` : lead.label}
          onToggle={() =>
            stacked ? onToggleGroup(ids, !anyVisible) : onToggle(lead.id)
          }
        />
      </td>

      <td className="min-w-0 py-1 pl-1 text-[10px] font-medium text-ink-2">
        <span className="flex items-center gap-1.5">
          {/* Weight mirrors the chart: a thicker bar means more levels agree. */}
          <span
            className={`shrink-0 rounded-full ${EMPHASIS_BAR[cluster.emphasis]}`}
            style={{ width: 10, height: Math.min(4, cluster.strength) }}
            aria-hidden
          />
          <span className="truncate">{stacked ? `${cluster.strength} levels` : lead.label}</span>
          {stacked && (
            <span
              className="shrink-0 rounded bg-ink-3/15 px-1 text-[9px] font-bold text-ink-2"
              data-testid={`band-strength-${cluster.key}`}
            >
              ×{cluster.strength}
            </span>
          )}
        </span>
        {stacked && (
          <span
            className="mt-0.5 block overflow-hidden text-ellipsis whitespace-nowrap text-[9px] text-ink-3"
            title={cluster.members.map((member) => member.label).join(', ')}
          >
            {cluster.members.map((member) => member.label).join(' · ')}
          </span>
        )}
      </td>

      <td className="tnum py-1 pr-2 text-right align-top font-mono text-[11px] font-semibold text-ink">
        {formatPrice(cluster.value)}
        {stacked && cluster.high !== cluster.low && (
          <span className="block text-[9px] font-normal text-ink-3">
            {formatPrice(cluster.low)}–{formatPrice(cluster.high)}
          </span>
        )}
      </td>

      <td
        className={`tnum py-1 pr-2 text-right align-top font-mono text-[10px] font-semibold ${
          EMPHASIS_TEXT[cluster.emphasis]
        }`}
      >
        {formatPercent(cluster.distancePercent)}
      </td>
    </tr>
  );
}
