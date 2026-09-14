import { MAIN_TAB_IDS, MAIN_TAB_LABELS, MAIN_TAB_TITLES } from '@/lib/mainTabs';
import { onTabListKey, tabClass } from '@/lib/tabs';
import { useTerminalStore } from '@/store/useTerminalStore';

/**
 * What the middle of the terminal is showing.
 *
 * Sits under the symbol strip rather than above it: the strip describes the
 * instrument and applies to every tab, so it stays put while the space below
 * it changes.
 */
export function MainTabs() {
  const tab = useTerminalStore((state) => state.mainTab);
  const setTab = useTerminalStore((state) => state.setMainTab);

  return (
    <div
      role="tablist"
      aria-label="Main view"
      data-testid="main-tabs"
      className="flex shrink-0 items-center gap-0.5 border-b border-line bg-panel px-2"
      onKeyDown={(event) => onTabListKey(event, MAIN_TAB_IDS, tab, setTab)}
    >
      {MAIN_TAB_IDS.map((id) => (
        <button
          key={id}
          type="button"
          role="tab"
          id={`main-tab-${id}`}
          tabIndex={tab === id ? 0 : -1}
          aria-selected={tab === id}
          // Only the open panel is in the document to point at.
          aria-controls={tab === id ? `main-panel-${id}` : undefined}
          title={MAIN_TAB_TITLES[id]}
          data-testid={`main-tab-${id}`}
          onClick={() => setTab(id)}
          className={`py-1 ${tabClass(tab === id)}`}
        >
          {MAIN_TAB_LABELS[id]}
        </button>
      ))}
    </div>
  );
}
