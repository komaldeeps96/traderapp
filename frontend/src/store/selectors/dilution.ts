import type { DilutionSummary, DilutionTone } from '@/types/protocol';

/**
 * The supply read, in the strip's idiom for spread, pullback and borrow: a word
 * beside the numbers, never instead of them. `clean` renders nothing, so an
 * ordinary large cap costs the strip no width.
 */
export interface DilutionView {
  /** Never `clean`: a clean read produces no chip at all. */
  tone: Exclude<DilutionTone, 'clean'>;
  /** The compact chip text, e.g. `W 89%` or `CASH 5.6M`. */
  label: string;
  /** Every reason, for the title attribute. */
  detail: string;
  /** Warrants trading above their strike, so exercise is live supply.
   *  Decided here because this is where the live price is. */
  warrantsInTheMoney: boolean | null;
}

const DILUTION_RANK: Record<DilutionTone, number> = {
  clean: 0,
  watch: 1,
  heavy: 2,
  serial: 3,
};

/**
 * Build the chip, or null when there is nothing worth saying.
 *
 * The label picks the single worst fact rather than concatenating: the strip
 * has room for one chip. The rest go to the tooltip.
 */
export function buildDilutionView(
  dilution: DilutionSummary | null | undefined,
  lastPrice: number | null,
): DilutionView | null {
  if (!dilution || dilution.tone === 'clean') return null;

  const inTheMoney =
    dilution.warrant_strike != null && lastPrice != null
      ? lastPrice > dilution.warrant_strike
      : null;

  return {
    tone: dilution.tone,
    label: dilutionLabel(dilution, inTheMoney),
    detail: dilution.reasons.join(' · '),
    warrantsInTheMoney: inTheMoney,
  };
}

/**
 * The single worst fact, ranked by how soon the supply can reach the tape:
 *
 *   1. warrants in the money — exercisable and sellable today
 *   2. under six months of cash — an offering is coming whatever the price
 *   3. a large overhang out of the money — supply that arms if it runs
 *   4. under eighteen months of cash — eventual
 */
function dilutionLabel(dilution: DilutionSummary, inTheMoney: boolean | null): string {
  const overhang = dilution.warrant_overhang;
  const runway = dilution.runway_months;

  if (overhang != null && overhang >= 0.1 && inTheMoney) {
    return `W ${Math.round(overhang * 100)}% ITM`;
  }
  if (runway != null && runway < 6) return `CASH ${runway.toFixed(1)}MO`;
  if (overhang != null && overhang >= 0.1) return `W ${Math.round(overhang * 100)}%`;
  if (runway != null && runway < 18) return `CASH ${runway.toFixed(1)}MO`;
  return dilution.tone.toUpperCase();
}

/** Whether `a` is a worse read than `b` — for sorting, and for tests. */
export function dilutionWorseThan(a: DilutionTone, b: DilutionTone): boolean {
  return DILUTION_RANK[a] > DILUTION_RANK[b];
}
