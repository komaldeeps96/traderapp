import type { ReactNode } from 'react';

/**
 * A chart control button.
 *
 * Shared by the main chart's floating cluster and the mini charts' header
 * strip so the two cannot drift apart in style — but not in size. The main
 * chart has room and these get pressed repeatedly while reading a move, so
 * they are a comfortable target there. In the mini column every pixel is
 * chart, so the same controls shrink to glyph size and the word "Reset"
 * becomes an icon.
 */
export function ChartButton({
  onClick,
  label,
  testId,
  children,
  wide = false,
  size = 'md',
  pressed,
}: {
  onClick: () => void;
  label: string;
  testId?: string;
  children: ReactNode;
  /** Let the button size to its text — for word labels like "Reset". */
  wide?: boolean;
  size?: 'md' | 'sm';
  /** Toggle buttons only: renders the active state and aria-pressed. */
  pressed?: boolean;
}) {
  const box = size === 'sm' ? 'h-[18px]' : 'h-8';
  const square = size === 'sm' ? 'w-[18px] text-[11px]' : 'w-8 text-[15px]';
  const text = size === 'sm' ? 'w-auto px-1 text-[9px] font-semibold' : 'w-auto px-2.5 text-[11px] font-semibold';

  return (
    <button
      type="button"
      className={
        `flex ${box} items-center justify-center rounded-sm border shadow-sm transition-colors ` +
        (pressed
          ? 'border-accent bg-accent/15 text-accent '
          : 'border-line-strong bg-elevated text-ink-2 hover:border-accent hover:text-ink ') +
        (wide ? text : `${square} leading-none`)
      }
      onClick={onClick}
      aria-label={label}
      {...(pressed !== undefined ? { 'aria-pressed': pressed } : {})}
      {...(testId ? { 'data-testid': testId } : {})}
    >
      <span aria-hidden>{children}</span>
    </button>
  );
}
