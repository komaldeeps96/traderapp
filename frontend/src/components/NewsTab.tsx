import { useCallback, useEffect, useState } from 'react';

import { formatNewsTime } from '@/lib/format';
import { api } from '@/lib/http';
import { useTerminalStore } from '@/store/useTerminalStore';
import type { Catalyst, Headline } from '@/types/protocol';

import { DockBody, DockEmpty } from './DockPanel';

/**
 * The news feed, read in place.
 *
 * IBKR is entitled to eight feeds here — Briefing.com and Dow Jones — with
 * thirty days of history, live headlines on generic tick 292 and full article
 * bodies, while every fundamentals request on the same connection answers
 * error 10358. Nothing needs a browser: headlines on top, the article in a
 * pane below, and clicking a row never leaves the terminal.
 *
 * Rows are tinted by what the headline does to the tape, not by sentiment.
 * "Announces Pricing of Public Offering" is the loudest row on the screen
 * because it is the one that ends a long, and a trader scanning a feed
 * mid-run is asking exactly that question.
 *
 * Live headlines arrive over the WebSocket and are merged into the same list
 * the backfill produced, deduplicated as a whole — Dow Jones sends the same
 * story as a starred bulletin seconds before the fuller press release, and
 * appending would show it twice.
 */
const CATALYST_CLASS: Record<Catalyst, string> = {
  supply: 'text-down font-semibold',
  distress: 'text-down',
  upside: 'text-up',
  none: 'text-ink-2',
};

const CATALYST_TITLE: Record<Catalyst, string> = {
  supply: 'Stock is being sold, or is about to be',
  distress: 'The company is in trouble — where supply usually comes from next',
  upside: 'A reason to be long',
  none: '',
};

export function NewsTab() {
  const symbol = useTerminalStore((state) => state.symbol);
  const headlines = useTerminalStore((state) => state.news);
  const status = useTerminalStore((state) => state.newsStatus);
  const providers = useTerminalStore((state) => state.newsProviders);
  const [open, setOpen] = useState<Headline | null>(null);

  // A different symbol's article must not stay open over the new feed.
  useEffect(() => setOpen(null), [symbol]);

  if (!symbol) return empty('Load a symbol to see its news.');
  if (status === 'loading' && headlines.length === 0) return empty(`Loading ${symbol} news…`);
  if (status === 'error') return empty(`News is unavailable for ${symbol}.`);
  if (headlines.length === 0) {
    return empty(
      providers.length === 0
        ? 'No news feed is reachable. Check the Alpaca keys, or start TWS.'
        : `No headlines for ${symbol} in the last 30 days.`,
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="dock-news">
      <Feeds providers={providers} />
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {headlines.map((headline) => (
          <Row
            key={headline.article_id}
            headline={headline}
            active={open?.article_id === headline.article_id}
            onOpen={() => setOpen((current) => (current === headline ? null : headline))}
          />
        ))}
      </div>
      {open && <Reader symbol={symbol} headline={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

/**
 * Which feeds are behind the list.
 *
 * Worth the one line because the answer is not fixed: the wire feeds are an
 * IBKR entitlement and vanish with TWS, while Benzinga rides in on Alpaca and
 * does not. A panel that goes thin should say which half went away.
 */
function Feeds({ providers }: { providers: Array<{ code: string; name: string }> }) {
  if (providers.length === 0) return null;
  return (
    <p
      className="shrink-0 truncate border-b border-line px-2 py-0.5 text-[9px] uppercase tracking-wide text-ink-3"
      data-testid="news-providers"
      title={providers.map((entry) => entry.name).join('\n')}
    >
      {providers.length} feed{providers.length === 1 ? '' : 's'} ·{' '}
      {providers.some((entry) => entry.code.startsWith('BZ')) ? 'Benzinga' : 'wire only'}
      {providers.some((entry) => entry.code.startsWith('DJ')) ? ' + Dow Jones' : ''}
    </p>
  );
}

function empty(message: string) {
  return (
    <DockBody testId="dock-news">
      <DockEmpty message={message} />
    </DockBody>
  );
}

function Row({
  headline,
  active,
  onOpen,
}: {
  headline: Headline;
  active: boolean;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid="news-row"
      data-catalyst={headline.catalyst}
      aria-expanded={active}
      title={CATALYST_TITLE[headline.catalyst]}
      className={`grid w-full grid-cols-[46px_44px_1fr] items-baseline gap-2 border-b border-line px-2 py-1 text-left outline-none hover:bg-elevated focus-visible:bg-elevated ${
        active ? 'bg-elevated' : ''
      } ${headline.roundup ? 'opacity-60' : ''}`}
    >
      <span className="tnum text-[10px] text-ink-3">{formatNewsTime(headline.time)}</span>
      <span className="truncate text-[9px] uppercase tracking-wide text-ink-3">
        {headline.provider}
      </span>
      <span className={`text-[11px] leading-snug ${CATALYST_CLASS[headline.catalyst]}`}>
        {headline.headline}
        {headline.related.length > 0 && (
          <span className="ml-1 text-[9px] text-ink-3" title="Duplicate wire copies folded in">
            +{headline.related.length}
          </span>
        )}
        {/* A movers list names a dozen companies and this one is merely among
            them, so the headline is usually about somebody else. Dimmed and
            labelled rather than hidden: being on that list is itself a tell. */}
        {headline.roundup && (
          <span
            className="ml-1 rounded-sm bg-elevated px-1 text-[9px] text-ink-3"
            data-testid="news-roundup"
            title={`A roundup naming ${headline.symbol_count} companies, not this one's news`}
          >
            LIST
          </span>
        )}
      </span>
    </button>
  );
}

/**
 * The article body.
 *
 * Paragraphs of plain text, never markup: the wire sends an HTML fragment and
 * it is converted to text on the server, because this is third-party content
 * on the page that also holds the trading UI.
 */
function Reader({
  symbol,
  headline,
  onClose,
}: {
  symbol: string;
  headline: Headline;
  onClose: () => void;
}) {
  const { paragraphs, error, loading } = useArticle(symbol, headline);

  return (
    <section
      className="flex max-h-[55%] min-h-0 shrink-0 flex-col border-t border-line-strong bg-panel"
      data-testid="news-article"
      aria-label="Article"
    >
      <header className="flex shrink-0 items-start gap-2 border-b border-line px-2 py-1.5">
        <p className="min-w-0 flex-1 text-[11px] font-semibold leading-snug text-ink">
          {headline.headline}
        </p>
        {/* Only Benzinga publishes one; a wire article exists nowhere but on
            the connection it came down. `noreferrer` because this is a
            third-party link on the page that also holds the trading UI. */}
        {headline.url && (
          <a
            href={headline.url}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="news-source-link"
            title="Open the original on the publisher's site"
            className="shrink-0 rounded-sm px-1 text-[10px] leading-none text-ink-3 outline-none hover:text-accent-text focus-visible:text-accent-text"
          >
            Source ↗
          </a>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close article"
          data-testid="news-close"
          className="shrink-0 rounded-sm px-1 text-[12px] leading-none text-ink-3 outline-none hover:text-ink focus-visible:text-ink"
        >
          ×
        </button>
      </header>
      <div className="scroll-thin min-h-0 flex-1 space-y-2 overflow-y-auto px-2 py-2">
        {loading && <p className="text-[11px] text-ink-3">Loading article…</p>}
        {error && <p className="text-[11px] text-ink-3">{error}</p>}
        {paragraphs.map((paragraph, index) => (
          <p key={index} className="text-[11px] leading-relaxed text-ink-2">
            {paragraph}
          </p>
        ))}
        {!loading && !error && paragraphs.length === 0 && (
          <p className="text-[11px] text-ink-3">
            This provider sent no body for the headline — only the headline itself.
          </p>
        )}
      </div>
    </section>
  );
}

function useArticle(symbol: string, headline: Headline) {
  const [paragraphs, setParagraphs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setParagraphs([]);
    void (async () => {
      try {
        const response = await api.article(
          symbol,
          headline.provider,
          headline.article_id,
          controller.signal,
        );
        setParagraphs(response.paragraphs);
      } catch {
        if (!controller.signal.aborted) setError('Could not load this article.');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [symbol, headline.provider, headline.article_id]);

  return { paragraphs, error, loading };
}

/**
 * Load the feed when the symbol changes.
 *
 * Lives here rather than in `useTerminal` because it is the panel's own
 * concern, but writes to the store so a live headline arriving over the
 * WebSocket can merge into the same list.
 */
export function useNewsFeed(symbol: string): void {
  const setNews = useTerminalStore((state) => state.setNews);
  const setStatus = useTerminalStore((state) => state.setNewsStatus);

  const load = useCallback(
    async (signal: AbortSignal) => {
      setStatus('loading');
      try {
        const response = await api.news(symbol, signal);
        if (signal.aborted) return;
        setNews(response.symbol, response.headlines, response.providers);
        setStatus('ready');
      } catch {
        if (!signal.aborted) setStatus('error');
      }
    },
    [symbol, setNews, setStatus],
  );

  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [symbol, load]);
}
