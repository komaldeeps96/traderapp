import { formatPrice } from '@/lib/format';
import { overlayIndicators, paneIndicators } from '@/store/selectors';
import { useTerminalStore } from '@/store/useTerminalStore';
import { indicatorLabel } from '@/types/protocol';

import { EyeToggle } from './EyeToggle';

interface IndicatorPanelProps {
  onToggle: (id: string) => void;
}

/** Overlays and sub-panes, with each indicator's current value. */
export function IndicatorPanel({ onToggle }: IndicatorPanelProps) {
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
    <section className="shrink-0 border-b border-line px-2 py-1.5" data-testid="indicator-panel">
      <h2 className="pb-1 text-[10px] font-bold uppercase tracking-wider text-ink-3">
        Indicators
      </h2>
      <ul className="flex flex-wrap gap-1">
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
              className="flex items-center gap-1 rounded-sm border border-line bg-elevated px-1 py-0.5"
            >
              <EyeToggle visible={visible} label={label} onToggle={() => onToggle(spec.id)} />
              {/* The swatch carries identity; the label stays in ink. Colouring
                  10px text with the series hue drops it below the contrast
                  floor and makes identity rest on colour alone. */}
              <span
                className="h-0.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: theme === 'dark' ? spec.color_dark : spec.color }}
                aria-hidden
              />
              <span className="text-[10px] font-bold text-ink-2">{label}</span>
              {value !== undefined && (
                <span className="tnum font-mono text-[10px] text-ink-2">{formatPrice(value)}</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
