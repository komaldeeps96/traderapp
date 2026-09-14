import { useSymbolResource } from '@/hooks/useSymbolResource';
import { useTerminalStore } from '@/store/useTerminalStore';
import { api } from '@/lib/http';
import { formatCompact, formatMoney, formatNyDate, formatPrice } from '@/lib/format';
import type {
  BusinessStats,
  DatedValue,
  DilutionRead,
  FundamentalsResponse,
} from '@/types/protocol';

import { DockBody, DockEmpty, DockGroup, DockRow } from './DockPanel';

/** Float this many times the last reported figure is the run, not drift. */
const SHELF_GROWN_MULTIPLE = 1.5;

/**
 * What the company is, in the terms this workflow cares about — three
 * questions, in the order they disqualify a candidate:
 *
 *   SUPPLY    warrants, preferred, converts, unissued authorised shares —
 *             stock that exists but is not yet on the tape
 *   NEED      cash against burn, and the shelf capacity to fix it
 *   HABIT     the offering trail and a year of share count
 *
 * Every figure carries the period it was reported for. SEC facts are quarterly
 * and arrive late, so a delinquent filer's newest cash number can be three
 * quarters old — itself the signal. Over two quarters stale is toned down.
 */
export function FundamentalsTab() {
  const symbol = useTerminalStore((state) => state.symbol);
  const lastPrice = useTerminalStore((state) => state.live?.bar.c ?? null);
  const { data, error, loading } = useSymbolResource(symbol, (signal) =>
    api.fundamentals(symbol, signal),
  );

  if (!symbol) return empty('Load a symbol to see its filings and dilution.');
  if (error) return empty(`Could not load ${symbol}'s filings — ${error}.`);
  if (loading || !data) return empty(`Loading ${symbol}…`);
  if (!data.available) {
    return empty('SEC filings are switched off. Set edgar.enabled in settings.yaml.');
  }

  const read = data.dilution;
  if (!read) {
    return (
      <DockBody testId="dock-fundamentals">
        {/* Never claim the company files nothing when the truth is that SEC
            refused us — that sends the reader hunting for a story that is
            really a line of configuration. */}
        <DockEmpty
          message={data.note ?? `${symbol} files nothing with the SEC that this reads.`}
        />
        {data.business && <Business stats={data.business} />}
      </DockBody>
    );
  }

  return (
    <DockBody testId="dock-fundamentals">
      <Header profile={data.profile} read={read} />
      <Supply read={read} lastPrice={lastPrice} />
      <Need read={read} />
      <Habit read={read} />
      {data.business && <Business stats={data.business} />}
    </DockBody>
  );
}

function empty(message: string) {
  return (
    <DockBody testId="dock-fundamentals">
      <DockEmpty message={message} />
    </DockBody>
  );
}

function Header({
  profile,
  read,
}: {
  profile: FundamentalsResponse['profile'];
  read: DilutionRead;
}) {
  return (
    <div className="border-b border-line px-2 pt-2 pb-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[12px] font-semibold text-ink" title={profile?.name}>
          {profile?.name ?? '—'}
        </span>
        <ToneChip tone={read.tone} />
      </div>
      {profile && (
        <p className="mt-0.5 truncate text-[10px] text-ink-3">
          {[profile.sic_description, profile.exchanges.join('/'), profile.state_of_incorporation]
            .filter(Boolean)
            .join(' · ')}
        </p>
      )}
      {read.reasons.length > 0 && (
        <ul className="mt-1.5 space-y-0.5" data-testid="dilution-reasons">
          {read.reasons.map((reason) => (
            <li key={reason} className="text-[10.5px] leading-snug text-ink-2">
              <span className="mr-1 text-ink-3">·</span>
              {reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const TONE_CLASS: Record<DilutionRead['tone'], string> = {
  clean: 'bg-up/15 text-up',
  watch: 'bg-ink-3/15 text-ink-2',
  heavy: 'bg-warn/20 text-warn',
  serial: 'bg-down/20 text-down-text',
};

export function ToneChip({ tone }: { tone: DilutionRead['tone'] }) {
  return (
    <span
      data-testid="dilution-tone"
      className={`shrink-0 rounded-sm px-1.5 py-[1px] text-[9.5px] font-bold uppercase tracking-wider ${TONE_CLASS[tone]}`}
    >
      {tone}
    </span>
  );
}

function Supply({ read, lastPrice }: { read: DilutionRead; lastPrice: number | null }) {
  // The full read ships the strike as a dated figure, unlike the compact
  // block behind the info-strip chip, which sends a bare number.
  const strike = read.warrant_strike;
  const inTheMoney =
    strike != null && lastPrice != null ? lastPrice > strike.value : null;

  return (
    <>
      <DockGroup label="Supply overhang" />
      <Dated label="Shares outstanding" value={read.shares_outstanding} format={formatCompact} />
      <Dated
        label="Warrants"
        value={read.warrants}
        format={formatCompact}
        tone={read.warrant_overhang != null && read.warrant_overhang >= 0.25 ? 'bad' : undefined}
        suffix={
          read.warrant_overhang != null
            ? ` (${Math.round(read.warrant_overhang * 100)}% of s/o)`
            : ''
        }
      />
      {strike != null && (
        <DockRow
          label="Warrant strike"
          value={`${formatPrice(strike.value)}${
            inTheMoney === null ? '' : inTheMoney ? ' · ITM' : ' · OTM'
          }`}
          asOf={strike.as_of}
          tone={inTheMoney ? 'bad' : undefined}
          title={
            inTheMoney
              ? 'Trading above the strike — exercise is live supply'
              : 'Below the strike, for now'
          }
        />
      )}
      <Dated label="Preferred" value={read.preferred} format={formatCompact} />
      <Dated label="Convertible notes" value={read.convertible_notes} format={formatMoney} />
      {read.fully_diluted != null && (
        <DockRow
          label="Fully diluted"
          value={`${formatCompact(read.fully_diluted)}${
            read.fully_diluted_ratio ? ` (${read.fully_diluted_ratio.toFixed(2)}×)` : ''
          }`}
          tone={read.fully_diluted_ratio && read.fully_diluted_ratio >= 1.25 ? 'bad' : undefined}
          // Preferred is excluded on purpose: conversion ratios are set per
          // series in the charter and are not in the XBRL facts.
          title="Common plus warrants. Preferred and converts are shown separately — their conversion ratios are not in the filings."
        />
      )}
      {read.authorized_headroom != null && (
        <DockRow
          label="Unissued authorised"
          value={formatCompact(read.authorized_headroom)}
          asOf={read.shares_authorized?.as_of}
          title="Shares the charter already permits them to issue without asking anyone"
        />
      )}
    </>
  );
}

function Need({ read }: { read: DilutionRead }) {
  const runway = read.runway_months;
  return (
    <>
      <DockGroup label="Need for cash" />
      <Dated label="Cash" value={read.cash} format={formatMoney} />
      <Dated
        label="Operating cash flow"
        value={read.annual_operating_cash_flow}
        format={formatMoney}
        suffix=" /yr"
      />
      {runway != null && (
        <DockRow
          label="Runway"
          value={`${runway.toFixed(1)} months`}
          tone={runway < 6 ? 'bad' : runway < 12 ? 'warn' : undefined}
          title="Cash divided by the reported annual burn"
        />
      )}
      <Dated label="Public float" value={read.public_float} format={formatMoney} />
      <Shelf read={read} />
    </>
  );
}

/**
 * What they may sell off a shelf, at today's prices.
 *
 * The cover-page cap everybody quotes is measured once a year; the rule
 * re-measures on the date of every sale against a 60-day look-back. Both are
 * shown when they disagree, because the gap between them *is* the read.
 */
function Shelf({ read }: { read: DilutionRead }) {
  const live = read.live_shelf;

  // The cap is worth a row only where it is, or was, in play. Apple's float
  // at the 60-day high is four trillion dollars and its one-third limit has
  // never bound anything — rendering that as "lifted" in red states a
  // dramatic fact about a rule the company has never been near. "Lifted"
  // has to have lifted *from* something.
  const inPlay = read.baby_shelf === true || live?.capped === true;
  if (!inPlay) return null;

  if (!live) {
    // No float share count or no prices — fall back to the filed figure
    // rather than showing nothing.
    return read.baby_shelf ? (
      <DockRow
        label="Baby-shelf cap"
        value={`${formatMoney(read.baby_shelf_capacity)} / 12mo`}
        tone="warn"
        title="Public float under $75M: Form S-3 General Instruction I.B.6 caps sales at a third of float per rolling twelve months"
        testId="baby-shelf"
      />
    ) : null;
  }

  const grown = live.multiple != null && live.multiple >= SHELF_GROWN_MULTIPLE;
  return (
    <>
      {live.capped ? (
        <DockRow
          label="Baby-shelf cap"
          value={`${formatMoney(live.capacity)} / 12mo`}
          tone={grown ? 'bad' : 'warn'}
          title={`A third of float measured at ${formatPrice(live.price)}, the 60-day high the rule prices a takedown against — not the figure on the last 10-K cover.${
            live.multiple != null
              ? ` The run has moved float to ${live.multiple.toFixed(1)}× what that cover page reported.`
              : ''
          }`}
          testId="baby-shelf"
        />
      ) : (
        <DockRow
          label="Baby-shelf cap"
          value="lifted"
          tone="bad"
          title={`Float reaches ${formatMoney(live.public_float)} at the 60-day high of ${formatPrice(live.price)}. Past $75M the one-third limit stops applying until the next measurement date — the run has removed the ceiling rather than raised it.`}
          testId="baby-shelf"
        />
      )}
      <DockRow
        label="Float at 60d high"
        value={`${formatMoney(live.public_float)}${
          live.multiple != null ? ` (${live.multiple.toFixed(1)}×)` : ''
        }`}
        tone={grown ? 'warn' : undefined}
        title="Public float priced at the 60-day high, which is what a sale off the shelf is measured against. The multiple compares it to the last reported figure."
        testId="shelf-float"
      />
    </>
  );
}

function Habit({ read }: { read: DilutionRead }) {
  const growth = read.share_growth_12m;
  return (
    <>
      <DockGroup label="Track record" />
      {growth != null && (
        <DockRow
          label="Share count, 12mo"
          value={`${growth > 0 ? '+' : ''}${(growth * 100).toFixed(1)}%`}
          tone={growth >= 0.25 ? 'bad' : growth >= 0.1 ? 'warn' : undefined}
          title="Measured over the year up to the most recent filing"
        />
      )}
      <DockRow
        label="Offerings, 12mo"
        value={String(read.offerings_12m)}
        tone={read.offerings_12m >= 3 ? 'bad' : read.offerings_12m >= 1 ? 'warn' : undefined}
        title="Registration statements and prospectuses filed in the last twelve months"
      />
      {read.delinquent && (
        <DockRow label="Filing status" value="Periodic report late" tone="bad" />
      )}
      {read.listing_deficiency && (
        <DockRow
          label="Listing"
          value="Rule failure notified"
          tone="bad"
          title="8-K item 3.01 — the exchange has told them they fail a continued listing rule"
        />
      )}
      {read.delisting_filed && !read.listing_deficiency && (
        <DockRow
          label="Form 25"
          value="Filed"
          title="A security class was filed for delisting. Often a matured note rather than the common stock."
        />
      )}
    </>
  );
}

/** Last, because it is context rather than a decision; the earnings date is the
 *  row worth planning around. */
function Business({ stats }: { stats: BusinessStats }) {
  const earnings = stats.earnings_next;
  if (!stats.industry && earnings == null) return null;
  return (
    <>
      <DockGroup label="Business" />
      {stats.industry && <DockRow label="Industry" value={stats.industry} />}
      {earnings != null && (
        <DockRow
          label="Next earnings"
          value={formatNyDate(earnings)}
          testId="next-earnings"
          title="TradingView's scheduled report date"
        />
      )}
    </>
  );
}

/**
 * A reported figure with its period end. Over two quarters old is dimmed: still
 * the best number available, but not with the weight of a current one.
 */
const STALE_DAYS = 190;

function Dated({
  label,
  value,
  format,
  tone,
  suffix = '',
}: {
  label: string;
  value: DatedValue | null | undefined;
  format: (value: number | null) => string;
  tone?: 'bad' | 'warn';
  suffix?: string;
}) {
  if (!value) return null;
  const stale = value.stale_days > STALE_DAYS;
  return (
    <DockRow
      label={label}
      value={`${format(value.value)}${suffix}`}
      asOf={value.as_of}
      tone={tone}
      stale={stale}
      title={`Reported for ${value.as_of} on a ${value.form}, ${value.stale_days} days ago`}
    />
  );
}
