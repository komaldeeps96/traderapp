import { useKeyedState } from '@/hooks/useKeyedState';
import { useSymbolResource } from '@/hooks/useSymbolResource';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { FilingKind, FilingRow } from '@/types/protocol';

import { DockBody, DockEmpty } from './DockPanel';

/**
 * The SEC filing trail, read for what each form means to a trade.
 *
 * A small cap's filings *are* its dilution history: S-1 and S-3 register
 * shares, EFFECT makes the shelf live, 424B5 is the takedown, 8-K item 3.02
 * sells stock with no registration. Those lead; periodic and ownership rows are
 * kept but folded away.
 *
 * Filing links open a new browser tab, the one place in this terminal where
 * that is right: a full S-1 is not a job for a 400px rail.
 */
const KIND_CLASS: Record<FilingKind, string> = {
  dilution: 'text-down font-semibold',
  distress: 'text-down',
  periodic: 'text-ink-2',
  ownership: 'text-ink-3',
  routine: 'text-ink-3',
};

/** The kinds that lead. Everything else sits behind the fold. */
const LEADING: FilingKind[] = ['dilution', 'distress'];

/**
 * How many leading rows open on screen. A serial diluter's trail can run to
 * over a hundred filings, and rendering all of it opens the panel years back.
 * The recent ones are the trade; the rest are a pattern the button already
 * states as a count.
 */
const LEADING_SHOWN = 18;

export function FilingsTab() {
  const symbol = useTerminalStore((state) => state.symbol);
  const live = useTerminalStore((state) => state.liveFilings);
  const { data, error, loading } = useSymbolResource(symbol, (signal) =>
    api.filings(symbol, signal),
  );
  const [showAll, setShowAll] = useKeyedState(symbol, false);
  const [showOlder, setShowOlder] = useKeyedState(symbol, false);

  if (!symbol) return empty('Load a symbol to see its SEC filings.');
  if (error) return empty(`Could not load ${symbol}'s filings — ${error}.`);
  if (loading || !data) return empty(`Loading ${symbol} filings…`);
  if (!data.available) {
    return empty('SEC filings are switched off. Set edgar.enabled in settings.yaml.');
  }

  // A filing pushed mid-session may not be in the fetched trail yet; merging
  // by accession keeps it from appearing twice once the trail catches up.
  const seen = new Set(data.filings.map((row) => row.accession));
  const rows = [...live.filter((row) => !seen.has(row.accession)), ...data.filings];

  if (rows.length === 0) return empty(data.note ?? `${symbol} has no filings on EDGAR.`);

  const leading = rows.filter((row) => LEADING.includes(row.kind));
  const rest = rows.filter((row) => !LEADING.includes(row.kind));
  const liveAccessions = new Set(live.map((row) => row.accession));

  const shownLeading = showOlder ? leading : leading.slice(0, LEADING_SHOWN);
  const hiddenLeading = leading.length - shownLeading.length;

  return (
    <DockBody testId="dock-filings">
      {leading.length > 0 && (
        <Section label="Dilution and distress" rows={shownLeading} live={liveAccessions} />
      )}
      {hiddenLeading > 0 && (
        <button
          type="button"
          onClick={() => setShowOlder(true)}
          data-testid="filings-older"
          className="w-full border-b border-line px-2 py-1 text-left text-[10px] text-ink-3 hover:text-ink-2 focus-visible:text-ink-2"
        >
          ▸ {hiddenLeading} older offering and distress filings
        </button>
      )}
      {leading.length === 0 && (
        <p className="px-2 py-3 text-[11px] text-ink-3">
          No offering or distress filings in the trail.
        </p>
      )}

      {rest.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setShowAll((open) => !open)}
            data-testid="filings-toggle"
            aria-expanded={showAll}
            className="mt-2 w-full border-y border-line px-2 py-1 text-left text-[9px] font-bold uppercase tracking-[0.13em] text-ink-3 hover:text-ink-2 focus-visible:text-ink-2"
          >
            {showAll ? '▾' : '▸'} Everything else ({rest.length})
          </button>
          {showAll && <Section rows={rest} live={liveAccessions} />}
        </>
      )}
    </DockBody>
  );
}

function empty(message: string) {
  return (
    <DockBody testId="dock-filings">
      <DockEmpty message={message} />
    </DockBody>
  );
}

function Section({
  label,
  rows,
  live,
}: {
  label?: string;
  rows: FilingRow[];
  live: Set<string>;
}) {
  return (
    <>
      {label && (
        <h3 className="mt-1 mb-1 border-b border-line px-2 pb-1 text-[9px] font-bold uppercase tracking-[0.13em] text-ink-3">
          {label}
        </h3>
      )}
      {rows.map((row) => (
        <Row key={row.accession} row={row} isLive={live.has(row.accession)} />
      ))}
    </>
  );
}

function Row({ row, isLive }: { row: FilingRow; isLive: boolean }) {
  return (
    <a
      href={row.url}
      target="_blank"
      rel="noreferrer noopener"
      data-testid="filing-row"
      data-kind={row.kind}
      data-form={row.form}
      title={`${row.note || row.form} — opens on sec.gov`}
      className="grid grid-cols-[62px_60px_1fr] items-baseline gap-2 border-b border-line px-2 py-1 hover:bg-elevated focus-visible:bg-elevated"
    >
      <span className="tnum text-[10px] text-ink-3">{row.filed}</span>
      <span className={`truncate text-[10px] ${KIND_CLASS[row.kind]}`}>{row.form}</span>
      <span className="truncate text-[10.5px] text-ink-3" title={row.note}>
        {isLive && (
          <span className="mr-1 rounded-sm bg-down/20 px-1 text-[9px] font-bold text-down">
            NEW
          </span>
        )}
        {row.note}
      </span>
    </a>
  );
}
