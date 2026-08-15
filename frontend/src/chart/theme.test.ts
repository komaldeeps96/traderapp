import { describe, expect, it } from 'vitest';

import { CHART_PALETTES, type ChartPalette } from './theme';

/**
 * The chart's colours, held to a measured standard.
 *
 * axe scans the DOM in both themes, but the chart is a canvas — its axis
 * labels, tick marks and countdown chip are painted, so nothing automated
 * sees them. These are the numbers that were checked by hand when the dark
 * palette was retuned, written down so they cannot drift back.
 *
 * The dark values had been lifted from the light palette: `textMuted` was a
 * 45° yellow-grey sitting on a 224° blue ground at 4.98:1, on the smallest
 * type in the terminal. Both halves of that — the contrast and the hue clash —
 * are asserted below.
 */

function channels(hex: string): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255) as [number, number, number];
}

function luminance(hex: string): number {
  const [r, g, b] = channels(hex).map((c) =>
    c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  ) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio, 1:1 (identical) to 21:1 (black on white). */
function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (light + 0.05) / (dark + 0.05);
}

/** Hue in degrees, and chroma as max-minus-min channel, 0-100. */
function hue(hex: string): { degrees: number; chroma: number } {
  const [r, g, b] = channels(hex);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  if (delta < 0.001) return { degrees: 0, chroma: 0 };
  let degrees =
    max === r
      ? 60 * (((g - b) / delta) % 6)
      : max === g
        ? 60 * ((b - r) / delta + 2)
        : 60 * ((r - g) / delta + 4);
  if (degrees < 0) degrees += 360;
  return { degrees, chroma: delta * 100 };
}

/** Shortest distance between two hues on the wheel. */
function hueGap(a: string, b: string): number {
  const diff = Math.abs(hue(a).degrees - hue(b).degrees);
  return Math.min(diff, 360 - diff);
}

describe.each([
  // Dark is the working theme and is held to a higher bar than the AA floor;
  // light is kept correct but is not what the terminal is read on.
  ['dark', CHART_PALETTES.dark, 6],
  ['light', CHART_PALETTES.light, 4.5],
])('%s chart palette', (_name, palette: ChartPalette, mutedFloor: number) => {
  it('gives the axis labels real contrast', () => {
    // 9-11px type. The old dark value was 4.98:1 — the AA floor for normal
    // text, and far too thin a margin at this size.
    expect(contrast(palette.textMuted, palette.surface)).toBeGreaterThanOrEqual(mutedFloor);
  });

  it('keeps the primary text well clear', () => {
    expect(contrast(palette.textPrimary, palette.surface)).toBeGreaterThanOrEqual(12);
  });

  it('keeps the crosshair visible without shouting', () => {
    // A dashed 1px line is a graphical object, not text, so 3:1 is the bar.
    expect(contrast(palette.crosshair, palette.surface)).toBeGreaterThanOrEqual(3);
  });

  it('reads the countdown against its own chip, not the surface', () => {
    // Filled boxes, so the fill is what the text has to beat — and the
    // closing chip is saturated red, which the ordinary text washes out on.
    expect(contrast(palette.countdownText, palette.countdown)).toBeGreaterThanOrEqual(4.5);
    expect(
      contrast(palette.countdownClosingText, palette.countdownClosing),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it('separates the candle polarity from the surface', () => {
    expect(contrast(palette.up, palette.surface)).toBeGreaterThanOrEqual(3);
    expect(contrast(palette.down, palette.surface)).toBeGreaterThanOrEqual(3);
  });

  it('keeps the grid quiet enough to sit behind price', () => {
    expect(contrast(palette.grid, palette.surface)).toBeLessThan(2);
  });
});

describe('dark neutrals share the surface hue', () => {
  const { dark } = CHART_PALETTES;

  it.each([
    ['textMuted', 'textMuted' as const],
    ['crosshair', 'crosshair' as const],
    ['border', 'border' as const],
    ['countdown', 'countdown' as const],
    ['countdownText', 'countdownText' as const],
  ])('%s is not a warm cast on a cool ground', (_label, key) => {
    // The failure this catches: a value copied over from the light palette.
    // Those are 45-60° yellow-greys, roughly opposite the 224° surface, and
    // they read as dinge rather than as grey.
    expect(hueGap(dark[key], dark.surface)).toBeLessThan(45);
  });

  it('keeps the neutrals neutral rather than tinting them blue', () => {
    // Hue-matched, but only just — these must still read as grey.
    for (const key of ['textMuted', 'crosshair', 'border'] as const) {
      expect(hue(dark[key]).chroma).toBeLessThan(20);
    }
  });
});
