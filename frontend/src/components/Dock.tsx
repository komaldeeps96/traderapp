import { useCallback, useEffect, useRef } from 'react';

import { MINI_COLUMN_QUERY } from '@/chart/mini';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { DOCK_TAB_IDS, DOCK_TAB_LABELS, DOCK_TAB_TITLES, clampDockWidth } from '@/lib/dock';
import type { Timeframe } from '@/types/protocol';
import { useTerminalStore } from '@/store/useTerminalStore';

import { FilingsTab } from './FilingsTab';
import { FundamentalsTab } from './FundamentalsTab';
import { MiniCharts } from './MiniCharts';
import { NewsTab, useNewsFeed } from './NewsTab';

/**
 * The rail to the right of the chart.
 *
 * It used to be the mini-chart column and nothing else. The context charts
 * are still its first tab and still what it opens on, because that is what is
 * wanted by default; the other three are the pre-trade check — what the
 * company is, what it has said, and what it has filed.
 *
 * Three things keep this from destabilising a dense layout.
 *
 * The width never changes by itself. A rail that resized when you switched
 * tabs would move the chart out from under the cursor, so it is one number,
 * dragged from the left edge and remembered, shared by every tab.
 *
 * The charts tab is unmounted rather than hidden when another tab is open. A
 * `display:none` container is zero-height, and lightweight-charts cannot size
 * a pane inside a chart that has none — the same reason the rail is not
 * rendered at all below the breakpoint.
 *
 * The tabs read from caches warmed at subscribe time, so switching to one
 * costs no request and shows no spinner.
 */
export function Dock({
  onMiniTimeframeChange,
}: {
  onMiniTimeframeChange: (slot: number, timeframe: Timeframe) => void;
}) {
  const wideEnough = useMediaQuery(MINI_COLUMN_QUERY);
  const tab = useTerminalStore((state) => state.dockTab);
  const width = useTerminalStore((state) => state.dockWidth);
  const setTab = useTerminalStore((state) => state.setDockTab);
  const setWidth = useTerminalStore((state) => state.setDockWidth);
  const symbol = useTerminalStore((state) => state.symbol);
  const alerts = useTerminalStore((state) => state.dockAlerts);

  // Loaded whichever tab is open: a live headline pushed over the WebSocket
  // has to merge into a list that already exists, and the feed must be warm
  // the moment the tab is clicked.
  useNewsFeed(symbol);

  // A rail dragged wide on an external monitor must not take half a laptop
  // screen when the window shrinks. Declared before the early return: hooks
  // cannot be conditional.
  useEffect(() => {
    const onResize = () => {
      const ceiling = Math.round(window.innerWidth * 0.5);
      if (width > ceiling) setWidth(clampDockWidth(ceiling));
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [width, setWidth]);

  // Below the breakpoint the main chart takes the width, exactly as the mini
  // column behaved before the dock existed.
  if (!wideEnough) return null;

  return (
    <aside
      className="relative flex h-full shrink-0 flex-col border-l border-line bg-surface"
      style={{ width }}
      aria-label="Symbol dock"
      data-testid="dock"
    >
      <ResizeHandle />
      <div
        role="tablist"
        aria-label="Dock panels"
        className="flex h-[26px] shrink-0 items-stretch border-b border-line bg-panel"
      >
        {DOCK_TAB_IDS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`dock-tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`dock-panel-${id}`}
            title={DOCK_TAB_TITLES[id]}
            data-testid={`dock-tab-${id}`}
            onClick={() => setTab(id)}
            className={`border-b-2 px-2.5 text-[10px] font-bold uppercase tracking-wider outline-none transition-colors focus-visible:bg-accent/15 ${
              tab === id
                ? 'border-accent text-ink'
                : 'border-transparent text-ink-3 hover:text-ink-2'
            }`}
          >
            {DOCK_TAB_LABELS[id]}
            {/* Only live pushes raise one — a 424B5 landing on a chart you
                are holding, or a headline arriving while you read the
                filings. It clears when the tab is opened. */}
            {(alerts[id] ?? 0) > 0 && (
              <span
                data-testid={`dock-alert-${id}`}
                className="ml-1 rounded-full bg-down px-1 text-[9px] font-bold text-white"
              >
                {alerts[id]}
              </span>
            )}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id={`dock-panel-${tab}`}
        aria-labelledby={`dock-tab-${tab}`}
        className="flex min-h-0 flex-1 flex-col"
      >
        {tab === 'charts' && <MiniCharts onTimeframeChange={onMiniTimeframeChange} />}
        {tab === 'fundamentals' && <FundamentalsTab />}
        {tab === 'news' && <NewsTab />}
        {tab === 'filings' && <FilingsTab />}
      </div>
    </aside>
  );
}

/**
 * The drag strip on the rail's left edge.
 *
 * Pointer capture rather than window listeners: dragging faster than the rail
 * can follow is normal on a wide monitor, and without capture the drag stops
 * the moment the cursor leaves the strip.
 */
function ResizeHandle() {
  const setWidth = useTerminalStore((state) => state.setDockWidth);
  const dragging = useRef(false);

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging.current) return;
      // The rail is flush to the viewport's right edge, so its width is the
      // distance from the pointer to that edge.
      setWidth(window.innerWidth - event.clientX);
    },
    [setWidth],
  );

  const stop = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  }, []);

  return (
    <div
      role="separator"
      aria-label="Resize dock"
      aria-orientation="vertical"
      data-testid="dock-resize"
      onPointerDown={(event) => {
        dragging.current = true;
        event.currentTarget.setPointerCapture?.(event.pointerId);
      }}
      onPointerMove={onPointerMove}
      onPointerUp={stop}
      onPointerCancel={stop}
      className="absolute -left-[3px] top-0 z-10 h-full w-[6px] cursor-col-resize hover:bg-accent/30"
    />
  );
}
