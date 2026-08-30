import { Chart } from '@/components/Chart';
import { ChartControls } from '@/components/ChartControls';
import { ChartLegend } from '@/components/ChartLegend';
import { Dock } from '@/components/Dock';
import { KeyLevelsPanel } from '@/components/KeyLevelsPanel';
import { ScannerPanel } from '@/components/ScannerPanel';
import { Toolbar } from '@/components/Toolbar';
import { TopPanel } from '@/components/TopPanel';
import { useTerminal } from '@/hooks/useTerminal';
import { useTerminalStore } from '@/store/useTerminalStore';
import { SCANNER_TIER_IDS } from '@/types/protocol';

/**
 * The terminal layout.
 *
 * One dense column of market discovery on the left — four IBKR trade-rate
 * scanners, one per market-cap tier, stacked and always visible together —
 * then the key levels for whatever is loaded — the chart column in the
 * middle with the symbol strip above it, and the dock down the right (above
 * 1280px; below that the main chart takes the width). The dock opens on the
 * 1m/5m context charts and carries the pre-trade check — fundamentals, news
 * and SEC filings — behind its other tabs.
 *
 * The TradingView screener used to sit above the scanners and was removed
 * from the UI: that job is done on a second monitor by a standard screener.
 * TradingView is still the backend's source for float, market cap and the
 * regime counts, so the service stays — only the panel is gone.
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
  const status = useTerminalStore((state) => state.status);

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
        <div className="scroll-thin flex max-h-[68%] min-h-0 flex-col overflow-y-auto">
          {SCANNER_TIER_IDS.map((scannerId) => (
            <ScannerPanel
              key={scannerId}
              scannerId={scannerId}
              onSelect={(symbol) => subscribe(symbol, timeframe)}
              onConfigure={(overrides) => configureScanner(scannerId, overrides)}
            />
          ))}
        </div>
        <KeyLevelsPanel onToggle={toggleIndicator} onToggleGroup={setIndicatorGroup} />
      </aside>

      <main className="flex h-full min-w-0 flex-1 flex-col">
        <Toolbar onSubscribe={subscribe} onTimeframe={setTimeframe} onToggleTheme={toggleTheme} />
        <TopPanel />

        {error && status === 'error' && (
          <div
            role="alert"
            data-testid="error-banner"
            className="shrink-0 border-b border-down/30 bg-down/10 px-3 py-1.5 text-[11px] text-down"
          >
            {error}
          </div>
        )}

        <div className="flex min-h-0 min-w-0 flex-1">
          {/* The legend, the floating controls and the loading badge are all
              positioned against the main chart, so they live inside its
              wrapper — spread across the mini column too, the controls would
              centre themselves on the seam between the two. */}
          <div className="relative min-h-0 min-w-0 flex-1">
            <Chart />
            <ChartLegend onToggle={toggleIndicator} />
            <ChartControls />
            {status === 'loading' && (
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

          <Dock onMiniTimeframeChange={setMiniTimeframe} />
        </div>
      </main>
    </div>
  );
}
