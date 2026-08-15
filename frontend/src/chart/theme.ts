/**
 * Chart colours.
 *
 * Dark is a selected palette rather than an inverted one: each colour is a
 * step chosen against the dark surface. The indicator hues themselves come
 * from the backend (`indicators.yaml`), which carries a light and a dark value
 * per indicator; this file covers the chrome and the candles.
 *
 * Candle up/down is a polarity pair, not a categorical series, so it keeps the
 * conventional green/red rather than drawing from the indicator palette.
 */

export type ThemeName = 'light' | 'dark';

export interface ChartPalette {
  surface: string;
  textPrimary: string;
  textMuted: string;
  grid: string;
  border: string;
  crosshair: string;
  crosshairLabel: string;
  up: string;
  down: string;
  upFill: string;
  downFill: string;
  /** Wash marking pre-market and after-hours periods. */
  extendedHours: string;
  /** Whole-dollar gridline — psychological levels are traded, so they are
   *  drawn faintly rather than inferred. */
  wholeDollar: string;
  halfDollar: string;
  /** Bar countdown chip, under the last-price label on the axis. Neutral by
   *  design: it is a clock, not a price, and must not read as one. */
  countdown: string;
  countdownText: string;
  /** The final tenth of a bar, where its shape stops changing. */
  countdownClosing: string;
  /** Text on that chip. The closing fill is a saturated red, so the text has
   *  to flip polarity — the ordinary countdown text measures 2.8:1 on it. */
  countdownClosingText: string;
}

export const CHART_PALETTES: Record<ThemeName, ChartPalette> = {
  light: {
    surface: '#ffffff',
    textPrimary: '#0b0b0b',
    textMuted: '#6d6b66',
    grid: '#eceae4',
    border: '#c3c2b7',
    crosshair: '#898781',
    crosshairLabel: '#0b0b0b',
    up: '#1a7f37',
    down: '#cf222e',
    upFill: 'rgba(26, 127, 55, 0.45)',
    downFill: 'rgba(207, 34, 46, 0.45)',
    extendedHours: 'rgba(137, 135, 129, 0.10)',
    wholeDollar: 'rgba(109, 107, 102, 0.35)',
    halfDollar: 'rgba(109, 107, 102, 0.18)',
    countdown: '#6d6b66',
    countdownText: '#ffffff',
    countdownClosing: '#cf222e',
    countdownClosingText: '#ffffff',
  },
  dark: {
    surface: '#131722',
    textPrimary: '#ffffff',
    // Axis labels and tick marks. The old warm grey measured 4.98:1 on the
    // chart surface — the weakest text anywhere in the terminal, on the
    // smallest type. This is 6.7:1 at worst and shares the surface's hue.
    textMuted: '#9ba6ba',
    grid: '#1e222d',
    border: '#39414f',
    crosshair: '#8b96a8',
    crosshairLabel: '#0b0b0b',
    up: '#3fb950',
    down: '#f85149',
    upFill: 'rgba(63, 185, 80, 0.45)',
    downFill: 'rgba(248, 81, 73, 0.45)',
    extendedHours: 'rgba(137, 135, 129, 0.14)',
    wholeDollar: 'rgba(154, 152, 145, 0.30)',
    halfDollar: 'rgba(154, 152, 145, 0.15)',
    countdown: '#3f4959',
    countdownText: '#e4eaf3',
    countdownClosing: '#f85149',
    countdownClosingText: '#0b0b0b',
  },
};

export function paletteFor(theme: ThemeName): ChartPalette {
  return CHART_PALETTES[theme];
}
