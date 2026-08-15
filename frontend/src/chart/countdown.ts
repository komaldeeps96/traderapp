/**
 * Time left in the current bar, drawn on the price axis.
 *
 * It used to sit in the toolbar's top-right corner, which is the wrong place
 * for it: the read on a candle firms up in its closing seconds, so the timer
 * is only useful while the eye is on the candle — and the eye is on the right
 * edge, where the live bar and its price label are. Reading it meant looking
 * away from the thing it describes.
 *
 * So it rides directly under the last-price label instead, one chart at a
 * time — each chart counts down its own timeframe.
 *
 * `fixedCoordinate` rather than `coordinate`: the axis nudges ordinary labels
 * apart to stop them colliding, which would let this one drift off the price
 * label it belongs to. Fixed labels are drawn exactly where they ask to be,
 * and the docs require a large negative `coordinate` alongside so the
 * auto-placement does not also reserve a gap for it.
 */

import type {
  ISeriesApi,
  ISeriesPrimitive,
  ISeriesPrimitiveAxisView,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts';

/** Keeps the automatic placement of ordinary labels from reserving a slot. */
const OFF_AXIS = -1000;

export interface CountdownState {
  /** Price the last-value label is sitting at. */
  price: number;
  text: string;
  /** In the bar's closing stretch. */
  closing: boolean;
  /** Height of the last-value label, so this one clears it. */
  labelHeight: number;
}

class CountdownAxisView implements ISeriesPrimitiveAxisView {
  constructor(private readonly primitive: BarCountdown) {}

  coordinate(): number {
    return OFF_AXIS;
  }

  fixedCoordinate(): number | undefined {
    const { state, series } = this.primitive;
    if (!state || !series) return undefined;
    const y = series.priceToCoordinate(state.price);
    return y === null ? undefined : y + state.labelHeight;
  }

  text(): string {
    return this.primitive.state?.text ?? '';
  }

  textColor(): string {
    // The closing chip is a saturated red; the ordinary text washes out on it.
    return this.primitive.state?.closing
      ? this.primitive.colors.closingText
      : this.primitive.colors.text;
  }

  backColor(): string {
    return this.primitive.state?.closing
      ? this.primitive.colors.closing
      : this.primitive.colors.background;
  }

  visible(): boolean {
    return this.primitive.state !== null;
  }

  tickVisible(): boolean {
    // A tick mark would point at a price. This is a duration.
    return false;
  }
}

export interface CountdownColors {
  background: string;
  text: string;
  closing: string;
  closingText: string;
}

export class BarCountdown implements ISeriesPrimitive {
  state: CountdownState | null = null;
  series: ISeriesApi<SeriesType> | null = null;
  // Replaced by the engine's palette on construction; these are the dark
  // values so a chip drawn before that never flashes the wrong colour.
  colors: CountdownColors = {
    background: '#3f4959',
    text: '#e4eaf3',
    closing: '#f85149',
    closingText: '#0b0b0b',
  };

  private readonly views: readonly ISeriesPrimitiveAxisView[] = [new CountdownAxisView(this)];
  private requestUpdate: (() => void) | null = null;

  attached(param: SeriesAttachedParameter<Time, SeriesType>): void {
    this.series = param.series;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.series = null;
    this.requestUpdate = null;
  }

  priceAxisViews(): readonly ISeriesPrimitiveAxisView[] {
    return this.views;
  }

  setColors(colors: CountdownColors): void {
    this.colors = colors;
    this.requestUpdate?.();
  }

  /**
   * Set the countdown, or clear it with `null`.
   *
   * Redraws only when something visible actually changed. The clock is polled
   * several times a second so the displayed second is never stale, but the
   * text only turns over once a second — repainting on every poll would be
   * three charts redrawing for nothing.
   */
  set(state: CountdownState | null): void {
    if (!changed(this.state, state)) {
      this.state = state;
      return;
    }
    this.state = state;
    this.requestUpdate?.();
  }
}

function changed(before: CountdownState | null, after: CountdownState | null): boolean {
  if (before === null || after === null) return before !== after;
  return (
    before.text !== after.text ||
    before.closing !== after.closing ||
    before.price !== after.price ||
    before.labelHeight !== after.labelHeight
  );
}
