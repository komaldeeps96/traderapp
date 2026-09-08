import { useCallback, useEffect, useRef, useState } from 'react';

import { formatAge, formatPrice } from '@/lib/format';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { Pillar, PillarState, SetupGrade, SetupJudgement } from '@/types/protocol';

import { DockBody, DockEmpty } from './DockPanel';

/**
 * The setup, judged.
 *
 * Every other panel on this screen reports. The strip above the chart has the
 * float, the rotation, the relative volume and the spread; the sidebar has
 * the level ladder; the news tab has the catalyst scored. All of it is true
 * and none of it answers the question the trader is actually asking, which is
 * what the *combination* is.
 *
 * That is the one thing a scoring function cannot do here, and it is the
 * whole reason for this tab. Ross Cameron's own thesis is that the five
 * pillars are weighed jointly and never counted: a stock at $19 with a 19M
 * float up exactly 10% on RVOL 5.1 clears all five, marginally, and is a
 * worse trade than one exceptional on three that openly fails a fourth. No
 * filter expresses that. A reader can.
 *
 * Three things about the design follow from what it is.
 *
 * **It is asked for, never automatic.** A judgement costs a cent and a minute
 * or two, and a chart left open would otherwise spend both every tick saying
 * much the same thing. Opening the tab asks once; the button asks again.
 *
 * **It carries the price it was taken at**, and says so the moment the tape
 * moves two percent or five minutes past it. A judgement that quietly ages
 * into wrongness is worse than one that admits it is old — and on the names
 * this terminal is for, two percent is under a minute.
 *
 * **A refusal names its gate.** The book's finding on catastrophic losses is
 * that they are never "the setup looked bad" — they are one specific rule
 * overridden. So the vetoes are their own block in the colour every other
 * disqualifier on this screen uses, above the prose rather than inside it.
 */
const GRADE_CLASS: Record<SetupGrade, string> = {
  A: 'bg-up/20 text-up',
  B: 'text-up',
  C: 'text-warn',
  F: 'bg-down/20 text-down',
};

const GRADE_TITLE: Record<SetupGrade, string> = {
  A: 'All five pillars — measured at 75-90% in a hot tape, 68-75% in a cold one',
  B: 'Four of five, and the miss is almost always the catalyst — 65-80%',
  C: 'Three of five — tradeable in a hot tape, loses money in a cold one',
  F: 'A hard gate fired. That is a different statement from a weak setup',
};

/** The order the row is always read in — the framework's own. */
const PILLAR_ORDER: Pillar['name'][] = ['price', 'change', 'rvol', 'float', 'catalyst'];

const PILLAR_LABEL: Record<Pillar['name'], string> = {
  price: 'PRICE',
  change: 'CHG',
  rvol: 'RVOL',
  float: 'FLOAT',
  catalyst: 'NEWS',
};

const PILLAR_CLASS: Record<PillarState, string> = {
  strong: 'bg-up/15 text-up',
  ok: 'text-ink-2',
  weak: 'text-warn',
  fail: 'bg-down/20 text-down',
  unknown: 'text-ink-3',
};

export function AiTab() {
  const symbol = useTerminalStore((state) => state.symbol);
  const { judgement, note, loading, refresh } = useJudgement(symbol);

  if (!symbol) {
    return (
      <DockBody testId="dock-ai">
        <DockEmpty message="Load a symbol to judge its setup." />
      </DockBody>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="dock-ai">
      <Header
        symbol={symbol}
        judgement={judgement}
        loading={loading}
        onRefresh={refresh}
      />
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {loading && (
          <p className="text-[11px] text-ink-3" data-testid="ai-loading">
            Reading {symbol}&rsquo;s setup… this takes a minute or two.
          </p>
        )}
        {!loading && !judgement && (
          <p className="text-[11px] leading-relaxed text-ink-3" data-testid="ai-note">
            {note ?? 'No judgement yet.'}
          </p>
        )}
        {!loading && judgement && <Body judgement={judgement} />}
      </div>
    </div>
  );
}

function Header({
  symbol,
  judgement,
  loading,
  onRefresh,
}: {
  symbol: string;
  judgement: SetupJudgement | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  const now = Math.floor(Date.now() / 1000);
  return (
    <header className="flex shrink-0 items-center gap-1.5 border-b border-line px-2 py-0.5">
      <span className="text-[9px] font-bold uppercase tracking-wider text-ink-3">
        Setup · {symbol}
      </span>
      {judgement && (
        <span className="truncate text-[9px] uppercase tracking-wide text-ink-3">
          read at {formatPrice(judgement.price)} · {formatAge(now - judgement.generated_at)} ago
        </span>
      )}
      {/* The tape has moved out from under this reading. Said rather than
          silently tolerated: a judgement that ages into wrongness without
          admitting it is worse than none. */}
      {judgement?.stale && (
        <span
          className="rounded-sm bg-down/20 px-1 text-[9px] font-semibold uppercase tracking-wide text-down"
          data-testid="ai-stale"
          title="The price has moved 2% or five minutes have passed since this was read — re-read before acting on it"
        >
          stale
        </span>
      )}
      <button
        type="button"
        onClick={onRefresh}
        disabled={loading}
        aria-label="Judge the setup again"
        title="Read the setup again against the tape right now"
        data-testid="ai-refresh"
        className="ml-auto shrink-0 rounded-sm px-1 text-[11px] leading-none text-ink-3 outline-none hover:text-ink disabled:opacity-40 focus-visible:text-ink"
      >
        ⟳
      </button>
    </header>
  );
}

function Body({ judgement }: { judgement: SetupJudgement }) {
  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <span
          className={`tnum flex h-[38px] w-[38px] shrink-0 flex-col items-center justify-center rounded-sm text-[16px] font-bold leading-none ${GRADE_CLASS[judgement.grade]}`}
          data-testid="ai-score"
          data-grade={judgement.grade}
          data-score={judgement.score}
          title={`${judgement.score}/10 — grade ${judgement.grade}. ${GRADE_TITLE[judgement.grade]}. Judged jointly, not counted: a setup marginal on all five pillars is worse than one exceptional on three.`}
        >
          {judgement.score}
          <span className="mt-0.5 text-[8px] font-semibold uppercase tracking-wide opacity-80">
            {judgement.grade}
          </span>
        </span>
        <p
          className="min-w-0 flex-1 text-[12px] font-semibold leading-snug text-ink"
          data-testid="ai-headline"
        >
          {judgement.headline}
        </p>
      </div>

      {/* Above the prose, because a gate that fired is the one thing a trader
          mid-run must not have to read a paragraph to find. */}
      {judgement.vetoes.length > 0 && (
        <ul className="space-y-0.5 rounded-sm bg-down/10 px-1.5 py-1" data-testid="ai-vetoes">
          {judgement.vetoes.map((line, index) => (
            <li key={index} className="flex gap-1 text-[11px] font-semibold leading-snug text-down">
              <span className="shrink-0">✕</span>
              <span className="min-w-0">{line}</span>
            </li>
          ))}
        </ul>
      )}

      <Pillars pillars={judgement.pillars} />

      <p className="text-[11px] leading-relaxed text-ink-2" data-testid="ai-judgement">
        {judgement.judgement}
      </p>

      {judgement.watch.length > 0 && (
        <div data-testid="ai-watch">
          <p className="mb-0.5 text-[9px] font-bold uppercase tracking-wider text-ink-3">
            What changes this
          </p>
          <ul className="space-y-0.5">
            {judgement.watch.map((line, index) => (
              <li key={index} className="flex gap-1 text-[10px] leading-snug text-ink-2">
                <span className="shrink-0 text-ink-3">›</span>
                <span className="min-w-0">{line}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="pt-1 text-[9px] leading-relaxed text-ink-3">
        Ross Cameron&rsquo;s framework, applied by {judgement.model}. A score is a read of
        the setup, not an instruction — and it has not seen the order book.
      </p>
    </div>
  );
}

/**
 * The five, always all five, always in this order.
 *
 * A missing pillar reads as unknown rather than as passing, because the row
 * is scanned rather than read and a gap in it would be taken for a blank.
 *
 * The server fills the gaps too. Doing it in both places is not redundancy:
 * the server's job is that the *judgement* names all five, and this one's is
 * that the *row* always means the same thing — five chips, same order, so the
 * eye can find FLOAT without reading the labels.
 */
function Pillars({ pillars }: { pillars: Pillar[] }) {
  const byName = new Map(pillars.map((pillar) => [pillar.name, pillar]));
  const row = PILLAR_ORDER.map(
    (name) => byName.get(name) ?? { name, state: 'unknown' as const, note: '' },
  );

  return (
    <div className="flex flex-wrap gap-1" data-testid="ai-pillars">
      {row.map((pillar) => (
        <span
          key={pillar.name}
          data-testid={`ai-pillar-${pillar.name}`}
          data-state={pillar.state}
          title={pillar.note || 'Not reported'}
          className={`rounded-sm px-1 py-[1px] text-[9px] font-semibold uppercase tracking-wide ${PILLAR_CLASS[pillar.state]}`}
        >
          {PILLAR_LABEL[pillar.name]}
          {pillar.note && <span className="ml-1 font-normal normal-case">{pillar.note}</span>}
        </span>
      ))}
    </div>
  );
}

/**
 * Ask for a judgement when the tab opens on a symbol, and when asked again.
 *
 * Deliberately not keyed on price: this reads a moving target, and a hook
 * that followed the tape would spawn a process a second. The symbol changing
 * is a new question; everything else is the refresh button.
 */
function useJudgement(symbol: string) {
  const [judgement, setJudgement] = useState<SetupJudgement | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [nonce, setNonce] = useState(0);
  const forced = useRef(false);

  useEffect(() => {
    if (!symbol) {
      setJudgement(null);
      setNote(null);
      return;
    }
    const controller = new AbortController();
    const force = forced.current;
    forced.current = false;
    setLoading(true);
    void (async () => {
      try {
        const response = await api.setup(symbol, force, controller.signal);
        if (controller.signal.aborted) return;
        // A reply for the symbol that was current when the request went out,
        // not the one the user has since typed.
        if (response.symbol !== symbol) return;
        setJudgement(response.judgement);
        setNote(response.note ?? null);
      } catch {
        if (!controller.signal.aborted) {
          setJudgement(null);
          setNote('The reader could not be reached.');
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [symbol, nonce]);

  const refresh = useCallback(() => {
    forced.current = true;
    setNonce((value) => value + 1);
  }, []);

  return { judgement, note, loading, refresh };
}
