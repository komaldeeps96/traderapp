import {
  SCANNER_TAB_IDS,
  SCANNER_TAB_LABELS,
  SCANNER_TAB_TITLES,
} from '@/lib/scannerTabs';
import { useTerminalStore } from '@/store/useTerminalStore';

/** Day movers or swing setups — the two questions the left column answers. */
export function ScannerTabs() {
  const tab = useTerminalStore((state) => state.scannerTab);
  const setTab = useTerminalStore((state) => state.setScannerTab);

  return (
    <div
      role="tablist"
      aria-label="Scanner mode"
      data-testid="scanner-tabs"
      className="flex shrink-0 items-center gap-0.5 border-b border-line bg-panel px-2"
    >
      {SCANNER_TAB_IDS.map((id) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={tab === id}
          title={SCANNER_TAB_TITLES[id]}
          data-testid={`scanner-tab-${id}`}
          onClick={() => setTab(id)}
          className={`border-b-2 px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-wide transition-colors ${
            tab === id
              ? 'border-accent text-accent-text'
              : 'border-transparent text-ink-3 hover:text-ink-2'
          }`}
        >
          {SCANNER_TAB_LABELS[id]}
        </button>
      ))}
    </div>
  );
}
