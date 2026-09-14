import type { ReactNode } from 'react';

/**
 * The two primitives the symbol panel's rows are built from.
 *
 * They live apart from the rows themselves so the tape, session and bar rows
 * can share them without importing each other.
 */

/** Group separator — cheaper than a wide gap, and it survives a wrap. */
export function Divider() {
  return <span aria-hidden className="h-2.5 w-px shrink-0 self-center bg-line-strong" />;
}

/**
 * A labelled number.
 *
 * `whitespace-nowrap` is load-bearing: a field is the unit that wraps, so a
 * long value takes its own label with it rather than breaking in half.
 *
 * A field carrying an explanation says so with a standing dotted underline, not
 * one on hover — a native tooltip advertises itself not at all, so a label like
 * ROT reads as jargon until something says it will answer. Kept to the label,
 * in the faintest line that survives both themes.
 */
export function Field({
  label,
  value,
  testId,
  tone,
  highlight,
  title,
}: {
  label: string;
  value: string;
  testId: string;
  tone?: string;
  highlight?: boolean;
  title?: string;
}) {
  return (
    <span className="whitespace-nowrap text-[11px] text-ink-3" title={title}>
      <span
        className={
          title
            ? 'cursor-help underline decoration-line-strong decoration-dotted underline-offset-2 hover:text-ink-2'
            : undefined
        }
        data-explained={title ? '' : undefined}
      >
        {label}
      </span>{' '}
      <span
        className={`font-semibold ${highlight ? 'text-accent-text' : (tone ?? 'text-ink')}`}
        data-testid={testId}
      >
        {value}
      </span>
    </span>
  );
}

/**
 * One line of the panel. Wrapping is allowed but nothing inside is
 * right-aligned, so an overlong value pushes the tail of its own row down
 * rather than rearranging the panel.
 */
export function Row({
  children,
  className = '',
  testId,
  hovering,
}: {
  children: ReactNode;
  className?: string;
  testId?: string;
  hovering?: boolean;
}) {
  return (
    <div
      className={`tnum flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 font-mono ${className}`}
      data-testid={testId}
      data-hovering={hovering === undefined ? undefined : hovering ? 'true' : 'false'}
    >
      {children}
    </div>
  );
}
