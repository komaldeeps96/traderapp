import { useState, useEffect } from 'react';

export function useVolumePane(chartRef) {
  const [volPaneBottom, setVolPaneBottom] = useState(191);

  useEffect(() => {
    const updateHeight = () => {
      const bottom = chartRef.current?.getVolumePaneBottom() ?? 191;
      setVolPaneBottom(prev => prev !== bottom ? bottom : prev);
    };

    // 1. Initial check
    updateHeight();

    // 2. Listen to window resize
    window.addEventListener('resize', updateHeight);

    // 3. Listen to mousemove with active clicks (splitter drag) on document
    const handleMouseMove = (e) => {
      // e.buttons === 1 indicates the left mouse button is held down (dragging)
      if (e.buttons === 1) {
        updateHeight();
      }
    };
    
    // Listen to mouseup to capture the final drag drop coordinate
    const handleMouseUp = () => {
      updateHeight();
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    // Run a deferred check to ensure correct layout after chart mounts/animates
    const timer = setTimeout(updateHeight, 500);

    return () => {
      window.removeEventListener('resize', updateHeight);
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      clearTimeout(timer);
    };
  }, [chartRef]);

  return volPaneBottom;
}
