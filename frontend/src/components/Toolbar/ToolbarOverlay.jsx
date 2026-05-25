import React from 'react';
import ToolbarBar from './ToolbarBar.jsx';
import ChartControls from './ChartControls.jsx';

export default function ToolbarOverlay({
  ticker,
  timeframe,
  connected,
  indicators,
  visibility,
  volPaneBottom,
  ohlcvRef,
  onSubscribe,
  onToggleIndicator,
  onZoomIn,
  onZoomOut,
  onScrollLeft,
  onScrollRight,
  onAutoFit,
}) {
  const controlsBottom = (volPaneBottom + 10) + 'px';

  return (
    <div className="absolute top-0 left-0 right-0 bottom-0 pointer-events-none z-20 [&>*]:pointer-events-auto">
      <ToolbarBar
        ticker={ticker}
        timeframe={timeframe}
        connected={connected}
        onSubscribe={onSubscribe}
        ohlcvRef={ohlcvRef}
      />
      <ChartControls
        onZoomIn={onZoomIn}
        onZoomOut={onZoomOut}
        onScrollLeft={onScrollLeft}
        onScrollRight={onScrollRight}
        onAutoFit={onAutoFit}
        style={{ bottom: controlsBottom }}
      />
    </div>
  );
}
