import React from 'react';
import TickerInput from './TickerInput.jsx';
import OHLCVDisplay from './OHLCVDisplay.jsx';
import ConnectionDot from './ConnectionDot.jsx';

export default function ToolbarBar({ ticker, timeframe, connected, onSubscribe, ohlcvRef }) {
  return (
    <div className="absolute top-4 left-4 flex items-center gap-2.5 bg-white/90 backdrop-blur-lg px-3 py-2 rounded-lg border border-gray-200 shadow-sm">
      <TickerInput ticker={ticker} timeframe={timeframe} onSubscribe={onSubscribe} />
      <div className="w-px h-5 bg-gray-300" />
      <OHLCVDisplay ref={ohlcvRef} />
      <div className="w-px h-5 bg-gray-300" />
      <ConnectionDot connected={connected} />
    </div>
  );
}
