import { lazy, Suspense, useCallback, useEffect, useRef } from 'react';

import { MINI_COLUMN_QUERY } from '@/chart/mini';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { useNewsFeed } from '@/hooks/useNewsFeed';
import { DOCK_TAB_IDS, DOCK_TAB_LABELS, DOCK_TAB_TITLES, clampDockWidth } from '@/lib/dock';
import { onTabListKey, tabClass } from '@/lib/tabs';
import type { Timeframe } from '@/types/protocol';
import { useTerminalStore } from '@/store/useTerminalStore';

import { MiniCharts } from './MiniCharts';
import { PanelFallback } from './PanelFallback';

// Fetched the first time their tab opens, so the first paint downloads none of them.
const FilingsTab = lazy(() => import('./FilingsTab').then((module) => ({ default: module.FilingsTab })));
const FundamentalsTab = lazy(() =>
  import('./FundamentalsTab').then((module) => ({ default: module.FundamentalsTab })),
);
const NewsTab = lazy(() => import('./NewsTab').then((module) => ({ default: module.NewsTab })));

/**
 * The rail to the right of the chart.
 *
 * Four tabs: the context charts, then the pre-trade check — what the company
 * is, what it has said, what it has filed.
 *
 * Three things keep it from destabilising a dense layout:
 *
 * The width never changes by itself — one number, dragged from the left edge
 * and remembered, shared by every tab, so switching tabs cannot move the chart
 * out from under the cursor.
 *
 * The charts tab is unmounted rather than hidden when another tab is open: a
 * `display:none` container is zero-height and lightweight-charts cannot size a
 * pane inside one. Same reason the rail is not rendered below the breakpoint.
 *
 * The tabs read from caches warmed at subscribe time, so switching costs no
 * data request; only a tab's first opening fetches its code.
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
        onKeyDown={(event) => onTabListKey(event, DOCK_TAB_IDS, tab, setTab)}
      >
        {DOCK_TAB_IDS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`dock-tab-${id}`}
            tabIndex={tab === id ? 0 : -1}
            aria-selected={tab === id}
            // Only the open panel is mounted, so only it can be pointed at.
            aria-controls={tab === id ? `dock-panel-${id}` : undefined}
            title={DOCK_TAB_TITLES[id]}
            data-testid={`dock-tab-${id}`}
            onClick={() => setTab(id)}
            className={tabClass(tab === id)}
          >
            {DOCK_TAB_LABELS[id]}
            {/* Only live pushes raise one — a 424B5 landing on a chart you
                are holding, or a headline arriving while you read the
                filings. It clears when the tab is opened. */}
            {(alerts[id] ?? 0) > 0 && (
              <span
                data-testid={`dock-alert-${id}`}
                className="ml-1 rounded-full bg-down px-1 text-[9px] font-bold text-panel"
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
        <Suspense fallback={<PanelFallback />}>
          {tab === 'fundamentals' && <FundamentalsTab />}
          {tab === 'news' && <NewsTab />}
          {tab === 'filings' && <FilingsTab />}
        </Suspense>
      </div>
    </aside>
  );
}

/**
 * The drag strip on the rail's left edge. Pointer capture rather than window
 * listeners: dragging faster than the rail can follow is normal, and without
 * capture the drag stops when the cursor leaves the strip.
 */
function ResizeHandle() {
  const width = useTerminalStore((state) => state.dockWidth);
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
      aria-valuenow={width}
      tabIndex={0}
      data-testid="dock-resize"
      // The rail is on the right, so the left arrow widens it.
      onKeyDown={(event) => {
        const step = event.shiftKey ? 64 : 16;
        if (event.key === 'ArrowLeft') setWidth(width + step);
        else if (event.key === 'ArrowRight') setWidth(width - step);
        else return;
        event.preventDefault();
      }}
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
