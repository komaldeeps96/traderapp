import { MAIN_TAB_IDS, MAIN_TAB_LABELS, MAIN_TAB_TITLES } from '@/lib/mainTabs';
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
    >
      {MAIN_TAB_IDS.map((id) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={tab === id}
          aria-controls={`main-panel-${id}`}
          title={MAIN_TAB_TITLES[id]}
          data-testid={`main-tab-${id}`}
          onClick={() => setTab(id)}
          className={`border-b-2 px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-wide transition-colors ${
            tab === id
              ? 'border-accent text-accent-text'
              : 'border-transparent text-ink-3 hover:text-ink-2'
          }`}
        >
          {MAIN_TAB_LABELS[id]}
        </button>
      ))}
    </div>
  );
}
