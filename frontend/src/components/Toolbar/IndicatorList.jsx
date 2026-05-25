import React, { forwardRef, useImperativeHandle, useRef } from 'react';
import { makeEyeIcon } from '../../utils/format.js';

const IndicatorList = forwardRef(({ indicators, timeframe, visibility, onToggle, volPaneBottom }, ref) => {
  const valRefs = useRef({});
  const pctRefs = useRef({});
  const rowRefs = useRef({});
  const tbodyRef = useRef(null);

  const applicable = indicators.filter(
    ind => ind.type !== 'volume' && ind.timeframes && ind.timeframes[timeframe] !== undefined
  );

  // 1D SMA/EMA overlays are daily indicators, meaning they are also key levels!
  const standard = applicable.filter(ind => ind.type !== 'daily');
  const keyLevels = applicable.filter(ind => ind.type === 'daily');

  useImperativeHandle(ref, () => ({
    setData(bar) {
      // 1. Update Standard indicators
      for (const ind of standard) {
        const el = valRefs.current[ind.id];
        if (el) {
          const val = bar?.[ind.id];
          el.innerText = val != null ? `: ${val.toFixed(2)}` : '';
        }
      }

      // 2. Update Key Levels values and % distances
      const close = bar?.close;
      for (const ind of keyLevels) {
        const val = bar?.[ind.id];
        
        // Update value element
        const valEl = valRefs.current[ind.id];
        if (valEl) {
          valEl.innerText = val != null ? val.toFixed(2) : '--';
        }

        // Update % distance element
        const pctEl = pctRefs.current[ind.id];
        if (pctEl) {
          if (val != null && close != null) {
            const pct = ((val - close) / close) * 100;
            const sign = pct >= 0 ? '+' : '';
            pctEl.innerText = `${sign}${pct.toFixed(2)}%`;
            
            // Color coding: green if above current price (resistance), red/rose if below (support)
            if (pct >= 0) {
              pctEl.className = "py-1 text-right font-mono text-[10px] text-emerald-500 font-semibold pr-1";
            } else {
              pctEl.className = "py-1 text-right font-mono text-[10px] text-rose-500 font-semibold pr-1";
            }
          } else {
            pctEl.innerText = '--';
            pctEl.className = "py-1 text-right font-mono text-[10px] text-gray-400 pr-1";
          }
        }
      }

      // 3. Dynamic sorting: largest values at the top
      const tbody = tbodyRef.current;
      if (tbody && bar) {
        const sorted = [...keyLevels].sort((a, b) => {
          const valA = bar?.[a.id] ?? -Infinity;
          const valB = bar?.[b.id] ?? -Infinity;
          return valB - valA;
        });

        for (const ind of sorted) {
          const row = rowRefs.current[ind.id];
          if (row) {
            tbody.appendChild(row);
          }
        }
      }
    }
  }));

  if (applicable.length === 0) return null;

  return (
    <div className="flex flex-col gap-5 h-full w-full pointer-events-auto overflow-hidden">
      {/* ── Standard Indicators (Top Pill Chips) ── */}
      {standard.length > 0 && (
        <div className="flex flex-col gap-2.5 shrink-0">
          <div className="flex items-center justify-between select-none">
            <span className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 font-bold">
              Timeframe Indicators
            </span>
            <span className="text-[9px] font-mono text-gray-400 dark:text-gray-500 font-semibold bg-gray-50 dark:bg-gray-900 px-1.5 py-0.5 rounded">
              {standard.length} Active
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5 w-full">
            {standard.map(ind => {
              const shown = visibility[ind.id] ?? false;
              return (
                <div
                  key={ind.id}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-150 dark:border-gray-800 transition-all duration-200 hover:border-gray-250 dark:hover:border-gray-700 shadow-sm"
                >
                  <button
                    className="flex items-center justify-center w-3.5 h-3.5 p-0 bg-transparent border-none text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 cursor-pointer transition-colors"
                    onClick={() => onToggle(ind.id)}
                    dangerouslySetInnerHTML={{ __html: makeEyeIcon(shown) }}
                  />
                  <span
                    className="text-[10px] font-bold flex items-center select-none"
                    style={{ color: ind.color }}
                  >
                    <span>{ind.label}</span>
                    <span
                      ref={el => {
                        if (el) valRefs.current[ind.id] = el;
                        else delete valRefs.current[ind.id];
                      }}
                      className="ml-1 font-mono font-normal opacity-90 text-[10px]"
                    />
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Key Trading Levels Table ── */}
      {keyLevels.length > 0 && (
        <div className="flex-1 flex flex-col min-h-0">
          <div className="text-[11px] font-bold text-gray-800 dark:text-gray-200 border-b border-gray-150 dark:border-gray-850 pb-2 mb-2 flex items-center justify-between select-none">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              <span className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 font-bold">
                Key Trading Levels
              </span>
            </div>
            <span className="text-[9px] font-mono font-semibold text-gray-400 dark:text-gray-500 bg-gray-50 dark:bg-gray-900 px-1.5 py-0.5 rounded">
              Sorted by Value
            </span>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar pr-0.5">
            <table className="w-full text-left border-collapse">
              <thead className="sticky top-0 bg-white dark:bg-gray-950 z-10 shadow-[0_1px_0_0_rgba(0,0,0,0.03)] dark:shadow-[0_1px_0_0_rgba(255,255,255,0.03)]">
                <tr className="text-[9px] uppercase tracking-wider text-gray-400 dark:text-gray-500 font-bold select-none">
                  <th className="pb-2 w-6 text-center"></th>
                  <th className="pb-2 text-left">Level</th>
                  <th className="pb-2 text-right font-mono pr-2">Value</th>
                  <th className="pb-2 text-right font-mono w-16 pr-1">% Dist</th>
                </tr>
              </thead>
              <tbody ref={tbodyRef} className="divide-y divide-gray-50 dark:divide-gray-900/40">
                {keyLevels.map(ind => {
                  const shown = visibility[ind.id] ?? false;
                  return (
                    <tr
                      key={ind.id}
                      ref={el => {
                        if (el) rowRefs.current[ind.id] = el;
                        else delete rowRefs.current[ind.id];
                      }}
                      className="hover:bg-gray-50/50 dark:hover:bg-gray-900/20 transition-colors"
                    >
                      <td className="py-2 w-6 text-center">
                        <button
                          className="flex items-center justify-center w-4 h-4 p-0 mx-auto bg-transparent border-none text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 cursor-pointer transition-colors"
                          onClick={() => onToggle(ind.id)}
                          dangerouslySetInnerHTML={{ __html: makeEyeIcon(shown) }}
                        />
                      </td>
                      <td className="py-2 text-[10px] font-semibold text-gray-600 dark:text-gray-300 select-none">
                        {ind.label}
                      </td>
                      <td
                        ref={el => {
                          if (el) valRefs.current[ind.id] = el;
                          else delete valRefs.current[ind.id];
                        }}
                        className="py-2 text-right font-mono text-[10px] font-bold text-gray-800 dark:text-gray-100 pr-2"
                      >
                        --
                      </td>
                      <td
                        ref={el => {
                          if (el) pctRefs.current[ind.id] = el;
                          else delete pctRefs.current[ind.id];
                        }}
                        className="py-2 text-right font-mono text-[10px] text-gray-400 pr-1"
                      >
                        --
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Vanilla CSS styling for custom scrollbars directly in React */}
      <style>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 3px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(156, 163, 175, 0.2);
          border-radius: 9px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgba(156, 163, 175, 0.4);
        }
      `}</style>
    </div>
  );
});

IndicatorList.displayName = 'IndicatorList';

export default IndicatorList;

