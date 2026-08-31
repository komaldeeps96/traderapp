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
 * long value takes its own label with it instead of breaking in half.
 *
 * A field carrying an explanation says so. Every one of these has had a
 * ``title`` since the panel was built, and it went unfound — a native tooltip
 * needs about a second of hover and advertises itself not at all, so a label
 * like ROT or WRVOL just reads as jargon.
 *
 * The dotted underline is standing rather than on hover, which is the point:
 * hover-only would still require already suspecting there was something to
 * find. This way the panel says at a glance which of its terms will answer a
 * question. Kept to the label and to the faintest line that survives both
 * themes — the values are what the panel is read for, and eighteen underlined
 * numbers would be a different and much worse panel.
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
