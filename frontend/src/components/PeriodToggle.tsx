import type { FinancialPeriodKind } from "@/types/protocol";

const PERIODS: Array<{ id: FinancialPeriodKind; label: string }> = [
  { id: "annual", label: "ANNUAL" },
  { id: "quarterly", label: "QUARTERLY" },
];

/** Annual or quarterly, for the two tabs built on the statements. */
export function PeriodToggle({
  value,
  onChange,
  testIdPrefix,
}: {
  value: FinancialPeriodKind;
  onChange: (period: FinancialPeriodKind) => void;
  testIdPrefix: string;
}) {
  return (
    <div className="flex gap-1" role="group" aria-label="Reporting period">
      {PERIODS.map((choice) => (
        <button
          key={choice.id}
          type="button"
          onClick={() => onChange(choice.id)}
          aria-pressed={value === choice.id}
          data-testid={`${testIdPrefix}-period-${choice.id}`}
          className={`rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-bold leading-4 ${
            value === choice.id
              ? "bg-accent/20 text-accent-text"
              : "text-ink-3 hover:text-ink-2"
          }`}
        >
          {choice.label}
        </button>
      ))}
    </div>
  );
}

/** Why a tab has nothing to show, when the reason is the request itself. */
export function LoadError({ what, error, testId }: { what: string; error: string; testId: string }) {
  return (
    <p role="alert" className="p-4 font-mono text-[11px] text-down" data-testid={testId}>
      Could not load {what} — {error}.
    </p>
  );
}
