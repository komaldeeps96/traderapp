import type { ReactNode } from 'react';

/**
 * Shared chrome for the dock's data tabs.
 *
 * Fundamentals, news and filings are the same shape — a scrolling body of
 * labelled rows — and every one of them can be empty for the same two
 * reasons: no symbol loaded, or the source had nothing to say. Saying that in
 * one place stops three tabs drifting into three different ways of saying
 * "nothing yet".
 *
 * Kept out of `Dock.tsx` so the tabs can import this without importing the
 * dock that renders them.
 */
export function DockBody({ children, testId }: { children: ReactNode; testId: string }) {
  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto pb-3" data-testid={testId}>
      {children}
    </div>
  );
}

export function DockEmpty({ message }: { message: string }) {
  return <p className="px-3 py-6 text-center text-[11px] leading-relaxed text-ink-3">{message}</p>;
}

/** A heading rule, matching the group labels in the key-levels panel. */
export function DockGroup({ label, hint }: { label: string; hint?: string }) {
  return (
    <h3
      className="mt-3 mb-1 flex items-baseline justify-between gap-2 border-b border-line px-2 pb-1 text-[9px] font-bold uppercase tracking-[0.13em] text-ink-3 first:mt-1"
      title={hint}
    >
      <span>{label}</span>
      {hint && <span className="font-medium normal-case tracking-normal">{hint}</span>}
    </h3>
  );
}

/**
 * One labelled row.
 *
 * `as_of` is not decoration: every EDGAR figure is quarterly and can be many
 * months old, so the date it was reported for rides beside the number rather
 * than being available on request. `tone` colours the value only — the label
 * stays quiet so a column of rows still scans as a column.
 */
export function DockRow({
  label,
  value,
  asOf,
  tone,
  title,
  testId,
}: {
  label: string;
  value: ReactNode;
  asOf?: string | null;
  tone?: 'bad' | 'warn' | 'good';
  title?: string;
  testId?: string;
}) {
  const toneClass =
    tone === 'bad'
      ? 'text-down font-semibold'
      : tone === 'warn'
        ? 'text-warn'
        : tone === 'good'
          ? 'text-up'
          : 'text-ink-2';

  return (
    <div
      className="flex items-baseline justify-between gap-3 px-2 py-[2px] text-[11px]"
      title={title}
      data-testid={testId}
    >
      <span className="shrink-0 text-ink-3">{label}</span>
      <span className={`tnum truncate text-right ${toneClass}`}>
        {value}
        {asOf && <span className="ml-1 text-[10px] font-normal text-ink-3">· {asOf}</span>}
      </span>
    </div>
  );
}
