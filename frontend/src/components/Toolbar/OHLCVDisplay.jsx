import React, { forwardRef, useImperativeHandle, useRef } from 'react';
import { buildOHLCVHTML } from '../../utils/format.js';

const OHLCVDisplay = forwardRef((_, ref) => {
  const elRef = useRef(null);

  useImperativeHandle(ref, () => ({
    setData(bar, bars, hoverTime) {
      if (elRef.current) {
        elRef.current.innerHTML = buildOHLCVHTML(bar, bars, hoverTime);
      }
    },
  }));

  return (
    <div
      ref={elRef}
      className="flex items-center gap-2.5 font-mono text-[11px] tracking-[0.02em] whitespace-nowrap"
    />
  );
});

OHLCVDisplay.displayName = 'OHLCVDisplay';

export default OHLCVDisplay;
