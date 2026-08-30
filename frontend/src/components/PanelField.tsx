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
      {label}{' '}
      <span
        className={`font-semibold ${highlight ? 'text-accent-text' : (tone ?? 'text-ink')}`}
        data-testid={testId}
      >
        {value}
      </span>
    </span>
  );
}
