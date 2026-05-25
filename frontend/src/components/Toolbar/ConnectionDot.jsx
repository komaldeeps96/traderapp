import React from 'react';

export default function ConnectionDot({ connected }) {
  return (
    <div
      className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
        connected ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 'bg-red-500'
      }`}
      title={connected ? 'Connected' : 'Disconnected'}
    />
  );
}
