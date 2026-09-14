import { Chart } from "@/components/Chart";
import { ChartControls } from "@/components/ChartControls";
import { ChartLegend } from "@/components/ChartLegend";
import { Dock } from "@/components/Dock";
import { KeyLevelsPanel } from "@/components/KeyLevelsPanel";
import { OrderPanel } from "@/components/OrderPanel";
import { ScannerPanel } from "@/components/ScannerPanel";
import { ScannerTabs } from "@/components/ScannerTabs";
import { WatchlistPanel } from "@/components/WatchlistPanel";
import { Toolbar } from "@/components/Toolbar";
import { TopPanel } from "@/components/TopPanel";
import { useHotkeys } from "@/hooks/useHotkeys";
import { useTerminal } from "@/hooks/useTerminal";
import { useTerminalStore } from "@/store/useTerminalStore";
import { SCANNER_TIER_IDS } from "@/types/protocol";

/**
 * The terminal layout.
 *
 * Left: market discovery — four IBKR trade-rate scanners, one per market-cap
 * tier, stacked and always visible, with the key levels beneath. Middle: the
 * chart column, symbol strip above it. Right: the dock, above 1280px only —
 * below that the main chart takes the width. The dock opens on the context
 * chart and tape, with fundamentals, news and SEC filings behind its tabs.
 */
export default function App() {
  const {
    subscribe,
    setTimeframe,
    toggleIndicator,
    setIndicatorGroup,
    configureScanner,
    toggleTheme,
    setMiniTimeframe,
  } = useTerminal();
  const symbol = useTerminalStore((state) => state.symbol);
  const timeframe = useTerminalStore((state) => state.timeframe);
  const error = useTerminalStore((state) => state.error);
  const notice = useTerminalStore((state) => state.notice);
  const setNotice = useTerminalStore((state) => state.setNotice);
  const status = useTerminalStore((state) => state.status);
  const scannerTab = useTerminalStore((state) => state.scannerTab);
  const halted = useTerminalStore((state) => state.info?.halted === true);
  useHotkeys(setTimeframe);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-surface">
      <aside
        className="flex h-full w-[320px] shrink-0 flex-col overflow-hidden border-r border-line bg-panel"
        aria-label="Market tools"
      >
        {/* The cap is what stops the scanners from crowding out the key
            levels, and it is a *max* — an empty stack takes no room at all.
            Sized so the four panels at full depth (small cap is ten rows
            deep, the rest five) clear it on a laptop without scrolling; a
            shorter window scrolls the column rather than shaving every
            panel down to the same half-visible height. */}
        <ScannerTabs />
        <div className="scroll-thin flex max-h-[68%] min-h-0 flex-col overflow-y-auto">
          {scannerTab === "day" &&
            SCANNER_TIER_IDS.map((scannerId) => (
              <ScannerPanel
                key={scannerId}
                scannerId={scannerId}
                onSelect={(symbol) => subscribe(symbol, timeframe)}
                onConfigure={(overrides) =>
                  configureScanner(scannerId, overrides)
                }
              />
            ))}
          {scannerTab === "watch" && (
            <WatchlistPanel
              onSelect={(symbol) => subscribe(symbol, timeframe)}
            />
          )}
        </div>
        <KeyLevelsPanel
          onToggle={toggleIndicator}
          onToggleGroup={setIndicatorGroup}
        />
      </aside>

      <main className="flex h-full min-w-0 flex-1 flex-col">
        <Toolbar
          onSubscribe={subscribe}
          onTimeframe={setTimeframe}
          onToggleTheme={toggleTheme}
        />
        <TopPanel />

        {error && status === "error" && (
          <div
            role="alert"
            data-testid="error-banner"
            className="shrink-0 border-b border-down/30 bg-down/10 px-3 py-1.5 text-[11px] text-down"
          >
            {error}
          </div>
        )}

        {notice && (
          <div
            role="status"
            data-testid="notice-banner"
            className="flex shrink-0 items-center gap-2 border-b border-warn/30 bg-warn/10 px-3 py-1.5 text-[11px] text-warn"
          >
            <span className="min-w-0 flex-1 truncate">{notice}</span>
            <button
              type="button"
              onClick={() => setNotice(null)}
              aria-label="Dismiss notice"
              className="shrink-0 rounded-sm px-1 font-bold hover:bg-warn/20"
            >
              ×
            </button>
          </div>
        )}

        <div className="flex min-h-0 min-w-0 flex-1">
          {/* The legend, the floating controls and the loading badge are all
              positioned against the main chart, so they live inside its
              wrapper — spread across the mini column too, the controls would
              centre themselves on the seam between the two. */}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="relative min-h-0 min-w-0 flex-1">
              {halted && (
                <div
                  className="pointer-events-none absolute inset-0 z-30 ring-2 ring-inset ring-down"
                  data-testid="halt-frame"
                >
                  <span className="absolute left-1/2 top-2 -translate-x-1/2 rounded-sm bg-down px-3 py-0.5 text-[13px] font-bold tracking-widest text-panel">
                    HALTED
                  </span>
                </div>
              )}
              <div className="group absolute inset-0">
                <Chart />
                <ChartLegend onToggle={toggleIndicator} />
                <ChartControls />
              </div>
              {status === "loading" && (
                <div
                  className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center"
                  data-testid="chart-loading"
                  aria-live="polite"
                >
                  <span className="tnum rounded-sm border border-line bg-panel/90 px-3 py-1.5 font-mono text-[12px] font-semibold text-ink-2">
                    Loading {symbol} · {timeframe.toUpperCase()}…
                  </span>
                </div>
              )}
            </div>
            <OrderPanel onSelect={(symbol) => subscribe(symbol, timeframe)} />
          </div>

          <Dock onMiniTimeframeChange={setMiniTimeframe} />
        </div>
      </main>
    </div>
  );
}
