import { formatPrice } from '@/lib/format';
import { overlayIndicators, paneIndicators } from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';
import { indicatorLabel } from '@/types/protocol';

import { EyeToggle } from './EyeToggle';

interface ChartLegendProps {
  onToggle: (id: string) => void;
}

/**
 * The indicator legend, over the top-left of the chart.
 *
 * It reads where it is drawn. Every other terminal puts the legend on the
 * chart because that is where the lines are: naming a hue in a sidebar three
 * hundred pixels away asks the eye to carry a colour across the screen and
 * back, and the row that says which blue is which was the furthest thing from
 * the blue it described.
 *
 * The wash is what makes it legible without a panel around it. Candles reach
 * the top-left whenever price is near the high of the window, and 10px type
 * over a bright candle body disappears; a translucent skim of the chart's own
 * surface keeps the text readable while the bars stay visible through it.
 *
 * Only the rows take pointer events — the gaps between them stay live for
 * panning and the crosshair, so the legend costs no chart surface.
 */
export function ChartLegend({ onToggle }: ChartLegendProps) {
  const specs = useTerminalStore((state) => state.specs);
  const timeframe = useTerminalStore((state) => state.timeframe);
  const visibility = useTerminalStore((state) => state.visibility);
  const theme = useTerminalStore((state) => state.theme);
  const hovered = useTerminalStore((state) => state.hovered);
  const live = useTerminalStore((state) => state.live);

  const values = (hovered ?? live)?.values ?? {};
  const overlays = overlayIndicators(specs, timeframe);
  const panes = paneIndicators(specs, timeframe);

  if (overlays.length === 0 && panes.length === 0) return null;

  return (
    <ul
      className="pointer-events-none absolute left-1.5 top-1.5 z-10 flex flex-col items-start"
      data-testid="chart-legend"
      aria-label="Chart indicators"
    >
      {[...overlays, ...panes].map((spec) => {
        const value = values[spec.id];
        const visible = visibility[spec.id] ?? true;
        // The 10s chart renames the minute EMAs (EMA 9 -> EMA 54).
        const label = indicatorLabel(spec, timeframe);
        return (
          <li
            key={spec.id}
            data-testid={`indicator-${spec.id}`}
            data-visible={visible ? 'true' : 'false'}
            className="pointer-events-auto flex items-center gap-1 rounded-sm bg-surface/70 pr-1"
          >
            <EyeToggle visible={visible} label={label} onToggle={() => onToggle(spec.id)} />
            {/* The swatch carries identity; the label stays in ink. Colouring
                10px text with the series hue drops it below the contrast
                floor and makes identity rest on colour alone. */}
            <span
              className={`h-0.5 w-2.5 shrink-0 rounded-full ${visible ? '' : 'opacity-40'}`}
              style={{ backgroundColor: theme === 'dark' ? spec.color_dark : spec.color }}
              aria-hidden
            />
            <span
              className={`text-[10px] font-bold leading-4 ${visible ? 'text-ink-2' : 'text-ink-3'}`}
            >
              {label}
            </span>
            {value !== undefined && (
              <span
                className={`tnum font-mono text-[10px] leading-4 ${
                  visible ? 'text-ink-2' : 'text-ink-3'
                }`}
              >
                {formatPrice(value)}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
