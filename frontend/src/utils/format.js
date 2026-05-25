export function fmtPrice(val) {
  return val != null ? val.toFixed(2) : '-';
}

export function fmtVol(val) {
  if (val == null) return '-';
  if (val >= 1e6) return (val / 1e6).toFixed(2) + 'M';
  if (val >= 1e3) return (val / 1e3).toFixed(2) + 'K';
  return val.toString();
}

export function compactVolFormat(val) {
  if (val >= 1e6) return (val / 1e6).toFixed(2) + 'M';
  if (val >= 1e3) return (val / 1e3).toFixed(0) + 'K';
  return val.toFixed(0);
}

function changeHtml(displayBar, bars, bar) {
  let prevBar = null;
  if (bars && bar) {
    const idx = bars.findIndex(b => b.time === displayBar.time);
    if (idx > 0) prevBar = bars[idx - 1];
  }

  if (!prevBar || displayBar.close == null) return '';

  const change = displayBar.close - prevBar.close;
  const pct = (change / prevBar.close) * 100;
  const sign = change >= 0 ? '+' : '';
  const cls = change >= 0 ? 'text-green-600 font-semibold' : 'text-red-600 font-semibold';
  return `<span class="${cls}">${sign}${change.toFixed(2)} (${sign}${pct.toFixed(2)}%)</span>`;
}

function dailyHtml(bars, bar) {
  if (!bars || bars.length === 0 || !bar) return '';

  const latestDate = new Date(bar.time * 1000).getDate();
  let prevClose = null;
  for (let i = bars.length - 1; i >= 0; i--) {
    if (new Date(bars[i].time * 1000).getDate() !== latestDate) {
      prevClose = bars[i].close;
      break;
    }
  }
  if (prevClose === null && bars.length > 0) prevClose = bars[0].open;
  if (prevClose === null) return '';

  const dChange = bar.close - prevClose;
  const dPct = (dChange / prevClose) * 100;
  const dSign = dChange >= 0 ? '+' : '';
  const dCls = dChange >= 0 ? 'text-green-600 font-semibold' : 'text-red-600 font-semibold';
  return `<span class="ml-1 ${dCls}">D ${dSign}${dChange.toFixed(2)} (${dSign}${dPct.toFixed(2)}%)</span>`;
}

export function buildOHLCVHTML(bar, bars, hoverTime) {
  const displayBar = hoverTime
    ? bars.find(b => b.time === hoverTime)
    : bar;

  if (!displayBar) return '';

  const change = changeHtml(displayBar, bars, bar);
  const dChange = dailyHtml(bars, bar);
  const volStr = fmtVol(displayBar.volume);

  return `
    <span class="text-gray-500">O <span class="text-gray-900 font-semibold">${fmtPrice(displayBar.open)}</span></span>
    <span class="text-gray-500">H <span class="text-gray-900 font-semibold">${fmtPrice(displayBar.high)}</span></span>
    <span class="text-gray-500">L <span class="text-gray-900 font-semibold">${fmtPrice(displayBar.low)}</span></span>
    <span class="text-gray-500">C <span class="text-gray-900 font-semibold">${fmtPrice(displayBar.close)}</span></span>
    ${change}
    ${dChange}
    <span class="text-gray-500">V <span class="text-gray-900 font-semibold">${volStr}</span></span>
  `;
}

export function buildVolLabelHTML(bar) {
  if (!bar) return '';
  const isUp = bar.close >= bar.open;
  const color = isUp ? '#089981' : '#f23645';
  return `
    <span style="font-size:12px;font-weight:500;color:#787b86">Vol</span>
    <span style="font-size:12px;font-weight:500;color:${color}">${fmtVol(bar.volume)}</span>
  `;
}

export function makeEyeIcon(visible) {
  if (visible) {
    return '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>';
  }
  return '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/></svg>';
}
