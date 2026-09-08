import { useCallback, useEffect, useRef, useState } from 'react';

import { formatNewsDay, formatWindowStart } from '@/lib/format';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { NewsBrief as Brief, NewsVerdict } from '@/types/protocol';

/**
 * The news panel's top half: one day, read and scored, so the list below can
 * be skimmed rather than opened.
 *
 * The server runs the `claude` CLI already installed on this machine — no
 * tools, no session, a JSON schema — against the day's headlines and the
 * bodies behind them. The rubric is Ross Cameron's treatment of catalysts,
 * which is why the score is worth reading at all: it knows that a registered
 * direct is not good news however the press release is worded, and that a
 * partnership with no counterparty and no figure is a sentence anyone can
 * write for free.
 *
 * Three things about it are deliberate.
 *
 * **It reads one session, not thirty days.** The window runs from the
 * previous close to now, because a press release at 16:05 is not today's
 * news — it is tomorrow's gap, and a rule keyed on the calendar date filed
 * it under the wrong day. The session and the window are both on the header,
 * because they are different facts: on a Sunday it reads "for Monday, since
 * Friday 16:00", which is the honest description and the useful one.
 *
 * **The score is catalyst quality, not a trade signal.** The reader sees the
 * headlines and nothing else — no float, no gap, no relative volume, no
 * regime — so a 2 means the news is not a reason to be long, never that the
 * stock is untradeable. The tooltip on the chip says so, because a number in
 * a box invites being read as a verdict on the trade.
 *
 * **It costs about a cent and a dozen seconds**, which is why the toolbar
 * carries a switch and why a reading is cached against the article ids it
 * covers. Switching away and back is free; a live headline that collapsed
 * into a story already on screen starts nothing.
 */
const VERDICT_CLASS: Record<NewsVerdict, string> = {
  strong: 'bg-up/20 text-up',
  tradeable: 'text-up',
  mixed: 'text-ink-2',
  weak: 'text-down',
  avoid: 'bg-down/20 text-down',
};

const VERDICT_TITLE: Record<NewsVerdict, string> = {
  strong: 'A costly signal — a regulator, a customer or an institution had to act',
  tradeable: 'Real and credible, but generic or theme-riding rather than company-specific',
  mixed: 'A real event that is thin, unquantified, or second-order',
  weak: 'Junk by cost of production, or a real headline undercut by an obvious flaw',
  avoid: 'A dilution structure, or nothing here is a catalyst at all',
};

export function NewsBriefPanel({ symbol }: { symbol: string }) {
  const enabled = useTerminalStore((state) => state.newsAi);
  const headlines = useTerminalStore((state) => state.news);
  const { brief, note, loading, refresh } = useBrief(symbol, enabled, headlines);

  if (!enabled) return null;

  return (
    <section
      className="flex max-h-[45%] min-h-0 shrink-0 flex-col border-b border-line-strong bg-panel"
      data-testid="news-brief"
      data-status={loading ? 'loading' : brief ? 'ready' : 'empty'}
      aria-label="AI news summary"
    >
      <header className="flex shrink-0 items-center gap-1.5 border-b border-line px-2 py-0.5">
        <span className="text-[9px] font-bold uppercase tracking-wider text-ink-3">AI read</span>
        {brief && (
          <span
            className="truncate text-[9px] uppercase tracking-wide text-ink-3"
            data-testid="news-brief-window"
            title={`The window read: ${formatWindowStart(brief.covers_from)} to now. News after a close belongs to the next session — a 16:05 press release is what the next morning gaps on.`}
          >
            {formatNewsDay(brief.session)} · since {formatWindowStart(brief.covers_from)} ·{' '}
            {brief.headline_count} headline{brief.headline_count === 1 ? '' : 's'}
          </span>
        )}
        {/* New headlines have landed since this was written, and the cooldown
            has not yet let another reading start. Saying so is the difference
            between a summary that is behind and one that is wrong. */}
        {brief?.stale && (
          <span
            className="rounded-sm bg-elevated px-1 text-[9px] uppercase tracking-wide text-ink-3"
            data-testid="news-brief-stale"
            title="Newer headlines have arrived since this reading — refresh to include them"
          >
            behind
          </span>
        )}
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          aria-label="Re-read today's news"
          title="Read the day again, ignoring the cached reading"
          data-testid="news-brief-refresh"
          className="ml-auto shrink-0 rounded-sm px-1 text-[11px] leading-none text-ink-3 outline-none hover:text-ink disabled:opacity-40 focus-visible:text-ink"
        >
          ⟳
        </button>
      </header>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-2 py-1.5">
        {loading && (
          <p className="text-[11px] text-ink-3" data-testid="news-brief-loading">
            Reading {symbol}&rsquo;s news…
          </p>
        )}
        {!loading && !brief && (
          <p className="text-[11px] text-ink-3" data-testid="news-brief-note">
            {note ?? 'No summary yet.'}
          </p>
        )}
        {!loading && brief && <Body brief={brief} />}
      </div>
    </section>
  );
}

function Body({ brief }: { brief: Brief }) {
  return (
    <div className="flex gap-2">
      <span
        className={`tnum flex h-[34px] w-[34px] shrink-0 flex-col items-center justify-center rounded-sm text-[15px] font-bold leading-none ${VERDICT_CLASS[brief.verdict]}`}
        data-testid="news-brief-score"
        data-verdict={brief.verdict}
        data-score={brief.score}
        title={`${brief.score}/10 — ${VERDICT_TITLE[brief.verdict]}. This scores the catalyst, not the trade: it does not see the float, the gap or the regime, so a low score means the news is not a reason to be long — not that the stock is untradeable.`}
      >
        {brief.score}
        <span className="mt-0.5 text-[7px] font-semibold uppercase tracking-wide opacity-80">
          {brief.verdict}
        </span>
      </span>

      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-[11px] leading-snug text-ink-2" data-testid="news-brief-summary">
          {brief.summary}
        </p>

        {brief.bullets.length > 0 && (
          <ul className="space-y-0.5" data-testid="news-brief-bullets">
            {brief.bullets.map((line, index) => (
              <li key={index} className="flex gap-1 text-[10px] leading-snug text-ink-2">
                <span className="shrink-0 text-ink-3">·</span>
                <span className="min-w-0">{line}</span>
              </li>
            ))}
          </ul>
        )}

        {/* Kept apart from the bullets, and in the colour every other
            disqualifier on this screen uses. A trader mid-run must not have
            to read a paragraph to find the offering in it. */}
        {brief.risks.length > 0 && (
          <ul className="space-y-0.5" data-testid="news-brief-risks">
            {brief.risks.map((line, index) => (
              <li key={index} className="flex gap-1 text-[10px] leading-snug text-down">
                <span className="shrink-0">⚠</span>
                <span className="min-w-0">{line}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/**
 * Ask the server to read the day, and again when the day's headlines change.
 *
 * The dependency is the article ids, not the array identity: the store
 * replaces `news` on every live push, and half of those are the starred
 * bulletin collapsing into a press release already on screen — which changes
 * nothing the reader would read and must not start a process. The server
 * keys its own cache the same way and holds a cooldown behind that, so the
 * two agree about what counts as new.
 */
function useBrief(
  symbol: string,
  enabled: boolean,
  headlines: Array<{ article_id: string }>,
) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [nonce, setNonce] = useState(0);
  const forced = useRef(false);

  const key = headlines.map((row) => row.article_id).join(',');

  useEffect(() => {
    if (!symbol || !enabled) {
      setBrief(null);
      setNote(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    const force = forced.current;
    forced.current = false;
    setLoading(true);
    void (async () => {
      try {
        const response = await api.newsBrief(symbol, force, controller.signal);
        if (controller.signal.aborted) return;
        // A reply for the symbol that was current when the request went out,
        // not the one the user has since typed.
        if (response.symbol !== symbol) return;
        setBrief(response.brief);
        setNote(response.note ?? null);
      } catch {
        if (!controller.signal.aborted) {
          setBrief(null);
          setNote('The reader could not be reached.');
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
    // `key` stands in for the headline set; the array itself is replaced on
    // every push and would re-run this for no change.
  }, [symbol, enabled, key, nonce]);

  const refresh = useCallback(() => {
    forced.current = true;
    setNonce((value) => value + 1);
  }, []);

  return { brief, note, loading, refresh };
}
