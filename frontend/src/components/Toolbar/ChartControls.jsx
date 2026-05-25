import React from 'react';

export default function ChartControls({ onZoomIn, onZoomOut, onScrollLeft, onScrollRight, onAutoFit, style }) {
  return (
    <div className="absolute left-0 right-0 flex items-center justify-center pointer-events-none" style={style}>
      <button
        className="absolute right-1 w-6 h-6 flex items-center justify-center p-0 bg-white/85 border border-[#d1d4dc] rounded-md text-[10px] font-bold text-[#2962ff] cursor-pointer transition-all shadow-[0_1px_2px_rgba(0,0,0,0.04)] hover:bg-white hover:text-[#1e4eb8] pointer-events-auto"
        title="Auto Fit"
        onClick={onAutoFit}
      >
        A
      </button>
      <div className="flex items-center gap-0.5 px-1 py-0.5 rounded-md pointer-events-auto">
        <button className="w-6 h-6 flex items-center justify-center p-0 bg-white/85 border border-[#d1d4dc] rounded-md text-[#787b86] text-base font-medium cursor-pointer transition-all shadow-[0_1px_2px_rgba(0,0,0,0.04)] hover:bg-white hover:text-[#131722]" onClick={onScrollLeft}>&#8249;</button>
        <div className="w-px h-3.5 bg-[#d1d4dc]/30 mx-0.5" />
        <button className="w-6 h-6 flex items-center justify-center p-0 bg-white/85 border border-[#d1d4dc] rounded-md text-[#787b86] text-base font-medium cursor-pointer transition-all shadow-[0_1px_2px_rgba(0,0,0,0.04)] hover:bg-white hover:text-[#131722]" onClick={onZoomOut}>−</button>
        <button className="w-6 h-6 flex items-center justify-center p-0 bg-white/85 border border-[#d1d4dc] rounded-md text-[#787b86] text-base font-medium cursor-pointer transition-all shadow-[0_1px_2px_rgba(0,0,0,0.04)] hover:bg-white hover:text-[#131722]" onClick={onZoomIn}>+</button>
        <div className="w-px h-3.5 bg-[#d1d4dc]/30 mx-0.5" />
        <button className="w-6 h-6 flex items-center justify-center p-0 bg-white/85 border border-[#d1d4dc] rounded-md text-[#787b86] text-base font-medium cursor-pointer transition-all shadow-[0_1px_2px_rgba(0,0,0,0.04)] hover:bg-white hover:text-[#131722]" onClick={onScrollRight}>&#8250;</button>
      </div>
    </div>
  );
}
