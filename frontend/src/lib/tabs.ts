import type { KeyboardEvent } from 'react';

/** One look for every tab strip, so the three cannot drift apart. */
export function tabClass(active: boolean): string {
  return `border-b-2 px-2.5 font-mono text-[10px] font-bold uppercase tracking-wide transition-colors ${
    active ? 'border-accent text-accent-text' : 'border-transparent text-ink-3 hover:text-ink-2'
  }`;
}

/**
 * Arrow-key movement along a tab strip, as the ARIA tabs pattern has it: the
 * arrows step and wrap, Home and End jump, and focus follows the selection so
 * the strip is one Tab stop rather than one per tab.
 */
export function onTabListKey<T extends string>(
  event: KeyboardEvent<HTMLElement>,
  ids: readonly T[],
  current: T,
  select: (id: T) => void,
): void {
  const index = ids.indexOf(current);
  const step: Record<string, number> = {
    ArrowRight: index + 1,
    ArrowLeft: index - 1,
    Home: 0,
    End: ids.length - 1,
  };
  const next = step[event.key];
  if (next === undefined || ids.length === 0) return;
  event.preventDefault();
  const target = (next + ids.length) % ids.length;
  const id = ids[target];
  if (id === undefined) return;
  select(id);
  event.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]')[target]?.focus();
}
