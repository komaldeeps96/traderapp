const WS_URL = 'ws://localhost:8000/ws';
const HEARTBEAT_INTERVAL = 5_000;   // 5s ping to prevent uvicorn timeout
const MAX_RECONNECT_DELAY = 30_000; // 30s max backoff

let ws = null;
let heartbeatTimer = null;
let reconnectAttempt = 0;
let reconnectTimer = null;
let messageCallback = null;
let statusCallback = null;
let activeTicker = null;
let activeTimeframe = null;
let destroyed = false;

function connect() {
  if (destroyed) return;
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    reconnectAttempt = 0;
    if (statusCallback) statusCallback(true);
    startHeartbeat();
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (messageCallback) messageCallback(msg);
    } catch (err) {
      console.error('Failed to parse WebSocket message:', err);
    }
  };

  ws.onclose = () => {
    if (statusCallback) statusCallback(false);
    stopHeartbeat();

    if (destroyed) return;

    const delay = Math.min(1000 * Math.pow(2, reconnectAttempt), MAX_RECONNECT_DELAY);
    reconnectAttempt++;
    console.log(`WebSocket closed, reconnecting in ${delay}ms (attempt ${reconnectAttempt})`);
    reconnectTimer = setTimeout(connect, delay);
  };

  ws.onerror = (err) => {
    console.error('WebSocket error:', err);
  };
}

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'ping' }));
    }
  }, HEARTBEAT_INTERVAL);
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

export function init() {
  destroyed = false;
  connect();
}

export function subscribe(ticker, timeframe) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    if (activeTicker) {
      ws.send(JSON.stringify({ action: 'unsubscribe', ticker: activeTicker }));
    }
    activeTicker = ticker;
    activeTimeframe = timeframe;
    ws.send(JSON.stringify({ action: 'subscribe', ticker, timeframe }));
  }
}

export function onMessage(callback) {
  messageCallback = callback;
}

export function onStatusChange(callback) {
  statusCallback = callback;
}

export function getActiveTicker() {
  return activeTicker;
}

export function getActiveTimeframe() {
  return activeTimeframe;
}

export function destroy() {
  destroyed = true;
  stopHeartbeat();
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws) {
    ws.close();
    ws = null;
  }
}
