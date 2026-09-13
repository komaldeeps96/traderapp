/** What a panel shows while its code arrives, the first time it is opened. */
export function PanelFallback() {
  return (
    <div
      className="flex min-h-0 flex-1 items-center justify-center font-mono text-[11px] text-ink-3"
      data-testid="panel-loading"
      aria-busy="true"
    >
      Loading…
    </div>
  );
}
