const BASE_URL = 'http://localhost:8000';

async function fetchJson(endpoint) {
  const res = await fetch(`${BASE_URL}${endpoint}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  return res.json();
}

export function fetchIndicators() {
  return fetchJson('/api/indicators');
}

export function fetchActiveTicker() {
  return fetchJson('/api/active-ticker');
}

export function fetchActiveTimeframe() {
  return fetchJson('/api/active-timeframe');
}
