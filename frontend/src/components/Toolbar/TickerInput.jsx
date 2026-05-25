import React, { useState, useEffect } from 'react';

const TIMEFRAMES = ['1m', '1d'];

export default function TickerInput({ ticker, timeframe, onSubscribe }) {
  const [inputVal, setInputVal] = useState(ticker);

  useEffect(() => {
    setInputVal(ticker);
  }, [ticker]);

  function handleSubmit(e) {
    e.preventDefault();
    const val = inputVal.toUpperCase().trim();
    if (val) onSubscribe(val, timeframe);
  }

  function handleTimeframeChange(e) {
    const tf = e.target.value;
    const val = inputVal.toUpperCase().trim();
    if (val) onSubscribe(val, tf);
  }

  function handleFocus() {
    setTimeout(() => {
      const el = document.querySelector('.toolbar-input');
      if (el) el.select();
    }, 0);
  }

  return (
    <form className="flex items-center gap-1.5" onSubmit={handleSubmit}>
      <input
        type="text"
        className="toolbar-input w-[72px] px-2 py-1 bg-white border border-gray-300 rounded text-[13px] text-gray-800 uppercase outline-none transition-colors focus:border-blue-500"
        placeholder="Ticker"
        value={inputVal}
        onChange={(e) => setInputVal(e.target.value.toUpperCase())}
        onFocus={handleFocus}
      />
      <select
        className="px-1.5 py-1 bg-white border border-gray-300 rounded text-[13px] text-gray-800 outline-none"
        value={timeframe}
        onChange={handleTimeframeChange}
      >
        {TIMEFRAMES.map(tf => (
          <option key={tf} value={tf}>
            {tf === '1d' ? '1D' : tf.toUpperCase()}
          </option>
        ))}
      </select>
      <button type="submit" className="hidden">Load</button>
    </form>
  );
}
