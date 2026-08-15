import { Chart } from '@/components/Chart';
import { ChartControls } from '@/components/ChartControls';
import { IndicatorPanel } from '@/components/IndicatorPanel';
import { KeyLevelsPanel } from '@/components/KeyLevelsPanel';
import { MiniCharts } from '@/components/MiniCharts';
import { ScannerPanel } from '@/components/ScannerPanel';
import { Toolbar } from '@/components/Toolbar';
import { TopPanel } from '@/components/TopPanel';
import { useTerminal } from '@/hooks/useTerminal';
import { useTerminalStore } from '@/store/useTerminalStore';

/**
 * The terminal layout.
 *
 * One dense column of market discovery on the left — the IBKR trade-rate
 * scanner, then the key levels for whatever is loaded — the chart column in
 * the middle with the symbol strip above it, and the 1m/5m context charts
 * down the right (above 1280px; below that the main chart takes the width).
 *
 * The TradingView screener used to sit above the scanner and was removed
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
        <div className="flex max-h-[52%] min-h-0 flex-col">
          <ScannerPanel
            onSelect={(symbol) => subscribe(symbol, timeframe)}
            onConfigure={configureScanner}
          />
        </div>
        <KeyLevelsPanel onToggle={toggleIndicator} onToggleGroup={setIndicatorGroup} />
        <IndicatorPanel onToggle={toggleIndicator} />
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
          {/* The floating controls and the loading badge are positioned
              against the main chart, so they live inside its wrapper — spread
              across the mini column too, the controls would centre themselves
              on the seam between the two. */}
          <div className="relative min-h-0 min-w-0 flex-1">
            <Chart />
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

          <MiniCharts />
        </div>
      </main>
    </div>
  );
}
