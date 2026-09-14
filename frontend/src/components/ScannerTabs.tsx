import {
  SCANNER_TAB_IDS,
  SCANNER_TAB_LABELS,
  SCANNER_TAB_TITLES,
} from '@/lib/scannerTabs';
import { onTabListKey, tabClass } from '@/lib/tabs';
import { useTerminalStore } from '@/store/useTerminalStore';

/** Switches the left column between the day scanners and the watchlist. */
export function ScannerTabs() {
  const tab = useTerminalStore((state) => state.scannerTab);
  const setTab = useTerminalStore((state) => state.setScannerTab);

  return (
    <div
      role="tablist"
      aria-label="Scanner mode"
      data-testid="scanner-tabs"
      className="flex shrink-0 items-center gap-0.5 border-b border-line bg-panel px-2"
      onKeyDown={(event) => onTabListKey(event, SCANNER_TAB_IDS, tab, setTab)}
    >
      {SCANNER_TAB_IDS.map((id) => (
        <button
          key={id}
          type="button"
          role="tab"
          tabIndex={tab === id ? 0 : -1}
          aria-selected={tab === id}
          title={SCANNER_TAB_TITLES[id]}
          data-testid={`scanner-tab-${id}`}
          onClick={() => setTab(id)}
          className={`py-1 ${tabClass(tab === id)}`}
        >
          {SCANNER_TAB_LABELS[id]}
        </button>
      ))}
    </div>
  );
}
