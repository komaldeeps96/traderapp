import { useEffect } from 'react';

import { TIMEFRAMES, type Timeframe } from '@/types/protocol';

/**
 * Keys that work anywhere outside a text field: a letter starts typing a
 * ticker, a digit picks the timeframe in toolbar order. No order hotkeys —
 * a stray key must never spend money.
 */
export function useHotkeys(onTimeframe: (timeframe: Timeframe) => void): void {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (isEditable(event.target)) return;
      if (/^[a-z]$/i.test(event.key)) {
        // Focus inside keydown: the browser then delivers the character to the
        // input, whose focus handler has selected the old ticker to replace.
        document.getElementById('symbol-input')?.focus();
        return;
      }
      const timeframe = /^[1-9]$/.test(event.key) ? TIMEFRAMES[Number(event.key) - 1] : undefined;
      if (timeframe) {
        event.preventDefault();
        onTimeframe(timeframe);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onTimeframe]);
}

function isEditable(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
  );
}
