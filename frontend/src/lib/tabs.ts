import type { KeyboardEvent } from 'react';

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
