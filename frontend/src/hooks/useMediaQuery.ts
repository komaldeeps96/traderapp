import { useCallback, useSyncExternalStore } from 'react';

/**
 * Track a media query.
 *
 * Used to *not render* something rather than to hide it: a chart engine built
 * inside a `display: none` container has no height to give its panes, so the
 * mini column is kept out of the tree entirely below its breakpoint instead of
 * being styled away.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window === 'undefined' || !window.matchMedia) return () => {};
      const list = window.matchMedia(query);
      list.addEventListener('change', onChange);
      return () => list.removeEventListener('change', onChange);
    },
    [query],
  );
  return useSyncExternalStore(subscribe, () => read(query), () => false);
}

function read(query: string): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia(query).matches;
}
