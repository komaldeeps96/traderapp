/**
 * Confluence bands, drawn as shaded price zones.
 *
 * A shelf of levels stacked within a fraction of a percent is one area of
 * supply, not five lines — and it has a *thickness*. Collapsing it to a single
 * heavier line threw that away: the trader could see that something mattered
 * there but not where it started and stopped, which is the part a stop is
 * placed against.
 *
 * Drawn as a series primitive rather than extra series so the zone spans the
 * whole pane regardless of where bar data begins or ends, and so adding or
 * removing a band never churns the chart's series list.
 */

import type {
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts';

export interface PriceBand {
  low: number;
  high: number;
  /** Fill, already carrying its alpha. */
  color: string;
}

/** A band thinner than this is drawn at this height so it stays visible. */
const MIN_BAND_PIXELS = 2;

class BandRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly bands: readonly PriceBand[],
    private readonly series: ISeriesApi<SeriesType> | null,
  ) {}

  draw(): void {
    // Bands belong behind the candles; everything is painted in
    // drawBackground so price action always sits on top of its context.
  }

  drawBackground(target: {
    useBitmapCoordinateSpace: (
      fn: (scope: {
        context: CanvasRenderingContext2D;
        bitmapSize: { width: number; height: number };
        verticalPixelRatio: number;
      }) => void,
    ) => void;
  }): void {
    const series = this.series;
    if (!series || this.bands.length === 0) return;

    target.useBitmapCoordinateSpace(({ context, bitmapSize, verticalPixelRatio }) => {
      for (const band of this.bands) {
        const top = series.priceToCoordinate(band.high);
        const bottom = series.priceToCoordinate(band.low);
        if (top === null || bottom === null) continue;

        const y1 = top * verticalPixelRatio;
        const y2 = bottom * verticalPixelRatio;
        const height = Math.max(Math.abs(y2 - y1), MIN_BAND_PIXELS * verticalPixelRatio);

        context.fillStyle = band.color;
        context.fillRect(0, Math.min(y1, y2), bitmapSize.width, height);
      }
    });
  }
}

class BandPaneView implements IPrimitivePaneView {
  constructor(private readonly primitive: ConfluenceBands) {}

  zOrder() {
    return 'bottom' as const;
  }

  renderer(): IPrimitivePaneRenderer {
    return new BandRenderer(this.primitive.bands, this.primitive.series);
  }
}

export class ConfluenceBands implements ISeriesPrimitive {
  bands: readonly PriceBand[] = [];
  series: ISeriesApi<SeriesType> | null = null;

  private readonly views: readonly IPrimitivePaneView[] = [new BandPaneView(this)];
  private requestUpdate: (() => void) | null = null;

  attached(param: SeriesAttachedParameter<Time, SeriesType>): void {
    this.series = param.series;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.series = null;
    this.requestUpdate = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }

  setBands(bands: readonly PriceBand[]): void {
    this.bands = bands;
    this.requestUpdate?.();
  }
}
