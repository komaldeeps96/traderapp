import {
  formatCompact,
  formatMoney,
  formatPrice,
  formatRotation,
  formatUnsignedPercent,
} from '@/lib/format';
import { FLOAT_DISAGREE_PERCENT, type InfoView, type OhlcvView } from '@/store/selectors';

import { Divider, Field, Row } from './PanelField';

/**
 * The day, as of whatever bar is being read: the provider's own figure while
 * the crosshair is off, the chart's cumulative sum once it rewinds the day.
 */
export function SessionRow({
  info,
  atBar,
  hovering,
}: {
  info: InfoView | null;
  atBar: OhlcvView | null;
  hovering: boolean;
}) {
  const volume = asOf(hovering, atBar?.sessionVolume, info?.dayVolume);
  const relVol = asOf(hovering, atBar?.rvolAtBar, info?.relVol);
  const rotation = asOf(hovering, atBar?.rotationAtBar, info?.floatRotation);
  const currentCap = atBar?.marketCapAtBar ?? null;

  return (
    <Row className="pt-0.5" testId="session-row" hovering={hovering}>
      <Field
        label="VOL"
        value={formatCompact(volume)}
        testId="tp-vol"
        title="Shares traded today, pre-market included — cumulative to the hovered bar"
      />
      <Field
        label="RVOL"
        value={formatRotation(relVol)}
        testId="tp-rvol"
        highlight={relVol != null && relVol >= 5}
        title="The day's pace over the 10-day average — 5x is the line"
      />
      {atBar?.windowRvol != null && (
        <Field
          label="WRVOL"
          value={formatRotation(atBar.windowRvol)}
          testId="tp-wrvol"
          title="Time-matched relative volume — this 4am→bar window against a typical session's volume by the same time of day, over the last 50 sessions"
        />
      )}

      <Divider />

      <FloatField info={info} />
      <Field
        label="ROT"
        value={formatRotation(rotation)}
        testId="tp-rot"
        highlight={rotation != null && rotation >= 1}
        title="Times the float has traded today — supply exhaustion read"
      />
      {info?.pmFloatRotation != null && info.pmVolume > 0 && (
        <Field
          label="PM ROT"
          value={formatUnsignedPercent(info.pmFloatRotation * 100, 0)}
          testId="tp-pm-rotation"
          highlight={info.pmFloatRotation >= 0.1}
          title="Premarket volume as a share of the float — 10%+ flags a runner"
        />
      )}

      <Divider />

      {/* Two caps, because the pair is the read: what the company was worth
          before the move, and what the tape is asking for it now. One number
          alone cannot say "a $9M shell being bid at $12M". */}
      <Field
        label="MCAP"
        value={formatMoney(info?.marketCap)}
        testId="tp-mcap"
        title={`Market cap on the previous close — shares outstanding × ${formatPrice(info?.prevClose)}. Fixed for the session, so it says what the company was worth before today. Under $500M is the small-cap lane`}
      />
      <Field
        label="C_MCAP"
        value={formatMoney(currentCap)}
        testId="tp-cmcap"
        title="Market cap right now — shares outstanding × the last trade; it follows the crosshair back to the hovered bar"
      />
      <Field
        label="AVG10D"
        value={formatCompact(info?.avgVol10d)}
        testId="tp-avgvol"
        title="Average daily volume over the last ten sessions — the RVOL denominator"
      />
      <Field
        label="PREV"
        value={formatPrice(info?.prevClose)}
        testId="tp-prevclose"
        title="Previous session's close — the gap and halt-band reference"
      />
    </Row>
  );
}

/**
 * The figure for the bar being read: the snapshot while live, the chart's
 * own reconstruction once the crosshair rewinds it — and either one as a
 * fallback when the other has nothing to say.
 */
function asOf(
  hovering: boolean,
  atBar: number | null | undefined,
  snapshot: number | null | undefined,
): number | null {
  const primary = hovering ? atBar : snapshot;
  return primary ?? atBar ?? snapshot ?? null;
}

function FloatField({ info }: { info: InfoView | null }) {
  const variation = info?.floatDisagreePercent ?? null;
  // The badge earns ink only past the threshold; the hover carries the
  // two-source comparison at ANY variation, because "the sources agree" is
  // itself information and invisible agreement is indistinguishable from
  // Yahoo never having answered.
  const disagree = variation != null && variation >= FLOAT_DISAGREE_PERCENT ? variation : null;
  const value = `${formatCompact(info?.floatShares)}${info?.floatSuspect ? ' ⚠' : ''}${
    disagree != null ? ` ±${Math.round(disagree)}%` : ''
  }`;
  const compared =
    variation != null
      ? `TradingView ${formatCompact(info?.floatShares)} vs Yahoo ${formatCompact(info?.yahooFloat)} · ±${Math.round(variation)}%`
      : 'Yahoo has not answered, so this is TradingView alone';
  // Two ways this number can be lying, in order of severity: impossible
  // against shares outstanding, or contradicted by the second source.
  const title = info?.floatSuspect
    ? `Float exceeds shares outstanding — reference data is stale or broken. ${compared}`
    : disagree != null
      ? `Sources disagree — an offering may have repriced the float. ${compared}`
      : `Float under 20M is the screen; under 10M preferred. ${compared}`;
  return (
    <Field
      label="FLOAT"
      value={value}
      testId="tp-float"
      tone={info?.floatSuspect || disagree != null ? 'text-down' : undefined}
      highlight={
        !info?.floatSuspect &&
        disagree == null &&
        info?.floatShares != null &&
        info.floatShares <= 20_000_000
      }
      title={title}
    />
  );
}
