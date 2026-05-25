import React, { forwardRef, useImperativeHandle, useRef } from 'react';
import { buildVolLabelHTML } from '../../utils/format.js';

const VolumeLabel = forwardRef(({ style }, ref) => {
  const elRef = useRef(null);

  useImperativeHandle(ref, () => ({
    setData(bar) {
      if (elRef.current) {
        elRef.current.innerHTML = buildVolLabelHTML(bar);
      }
    },
  }));

  return (
    <div
      ref={elRef}
      className="absolute left-2 z-10 pointer-events-none flex items-center gap-1"
      style={style}
    />
  );
});

VolumeLabel.displayName = 'VolumeLabel';

export default VolumeLabel;
