/**
 * Time left in the current bar, drawn on the price axis.
 *
 * It rides directly under the last-price label, where the eye already is in a
 * candle's closing seconds. Each chart counts down its own timeframe.
 *
 * `fixedCoordinate` rather than `coordinate`: the axis nudges ordinary labels
 * apart to stop collisions, which would drift this one off the price label it
 * belongs to. Fixed labels are drawn exactly where they ask, and the docs
 * require a large negative `coordinate` alongside so auto-placement does not
 * also reserve a gap.
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
/** A digit's width, so padding matches the price labels' tabular figures. */
const FIGURE_SPACE = ' ';
/** "10.07", "0.3712", "123.45": what a price label holds. */
const LABEL_CHARS = 6;

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
    // A primitive's box is as wide as its text; padded to a price label's
    // width it covers the axis tick beneath instead of leaving its tail out.
    return (this.primitive.state?.text ?? '').padStart(LABEL_CHARS, FIGURE_SPACE);
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
   * Set the countdown, or clear it with `null`. Redraws only when something
   * visible changed: the clock is polled several times a second so the shown
   * second is never stale, but the text turns over only once a second.
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
