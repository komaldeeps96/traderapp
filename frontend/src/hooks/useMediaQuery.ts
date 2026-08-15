import { useEffect, useState } from 'react';

/**
 * Track a media query.
 *
 * Used to *not render* something rather than to hide it: a chart engine built
 * inside a `display: none` container has no height to give its panes, so the
 * mini column is kept out of the tree entirely below its breakpoint instead of
 * being styled away.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => read(query));

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const list = window.matchMedia(query);
    // The query can have changed between the initial state and this effect.
    setMatches(list.matches);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    list.addEventListener('change', onChange);
    return () => list.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}

function read(query: string): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia(query).matches;
}
