interface EyeToggleProps {
  visible: boolean;
  label: string;
  onToggle: () => void;
}

/** Show/hide control for a single chart series. */
export function EyeToggle({ visible, label, onToggle }: EyeToggleProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={visible}
      aria-label={`${visible ? 'Hide' : 'Show'} ${label}`}
      data-visible={visible ? 'true' : 'false'}
      className={`flex h-4 w-4 items-center justify-center rounded transition-colors ${
        visible ? 'text-ink-2 hover:text-ink' : 'text-ink-3/40 hover:text-ink-3'
      }`}
    >
      <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" aria-hidden>
        {visible ? (
          <>
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"
            />
            <circle cx="12" cy="12" r="2.75" strokeWidth={2} />
          </>
        ) : (
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M3 3l18 18M10.6 10.7a2.75 2.75 0 003.9 3.9M6.9 6.98C4.6 8.4 2.5 12 2.5 12s3.5 6.5 9.5 6.5c1.4 0 2.6-.3 3.7-.8M17.5 15.3c2-1.4 4-3.3 4-3.3S18 5.5 12 5.5c-.7 0-1.4.1-2 .2"
          />
        )}
      </svg>
    </button>
  );
}
