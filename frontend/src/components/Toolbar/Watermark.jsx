import React from 'react';

export default function Watermark({ ticker }) {
  return (
    <div className="absolute top-4 left-4 z-0 pointer-events-none select-none text-black/[0.08] text-[60px] font-bold tracking-[0.1em] uppercase">
      {ticker}
    </div>
  );
}
