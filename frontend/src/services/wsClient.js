const WS_URL = 'ws://localhost:8000/ws';
const HEARTBEAT_INTERVAL = 5000;
const MAX_RECONNECT_DELAY = 30000;

class WSClient {
  constructor() {
    this._ws = null;
    this._heartbeatTimer = null;
    this._reconnectAttempt = 0;
    this._reconnectTimer = null;
    this._messageCallback = null;
    this._statusCallback = null;
    this._destroyed = false;
    this._lastTicker = null;
    this._lastTimeframe = null;
  }

  connect() {
    if (this._destroyed) return;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._ws) {
      const rs = this._ws.readyState;
      if (rs === WebSocket.OPEN || rs === WebSocket.CONNECTING) return;
    }

    this._ws = new WebSocket(WS_URL);

    this._ws.onopen = () => {
      this._reconnectAttempt = 0;
      if (this._statusCallback) this._statusCallback(true);
      this._startHeartbeat();
      if (this._lastTicker && this._lastTimeframe) {
        this._send({ action: 'subscribe', ticker: this._lastTicker, timeframe: this._lastTimeframe });
      }
    };

    this._ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (this._messageCallback) this._messageCallback(msg);
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    this._ws.onclose = () => {
      if (this._statusCallback) this._statusCallback(false);
      this._stopHeartbeat();
      this._scheduleReconnect();
    };

    this._ws.onerror = () => {
      this._scheduleReconnect();
    };
  }

  subscribe(ticker, timeframe) {
    this._lastTicker = ticker;
    this._lastTimeframe = timeframe;
    this._send({ action: 'subscribe', ticker, timeframe });
  }

  onMessage(callback) {
    this._messageCallback = callback;
  }

  onStatusChange(callback) {
    this._statusCallback = callback;
  }

  destroy() {
    this._destroyed = true;
    this._lastTicker = null;
    this._lastTimeframe = null;
    this._stopHeartbeat();
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }
  }

  _send(payload) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(payload));
    }
  }

  _scheduleReconnect() {
    if (this._destroyed || this._reconnectTimer) return;
    const delay = Math.min(1000 * Math.pow(2, this._reconnectAttempt), MAX_RECONNECT_DELAY);
    this._reconnectAttempt++;
    console.log(`WebSocket reconnecting in ${delay}ms (attempt ${this._reconnectAttempt})`);
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this.connect();
    }, delay);
  }

  _startHeartbeat() {
    this._stopHeartbeat();
    this._heartbeatTimer = setInterval(() => {
      this._send({ action: 'ping' });
    }, HEARTBEAT_INTERVAL);
  }

  _stopHeartbeat() {
    if (this._heartbeatTimer) {
      clearInterval(this._heartbeatTimer);
      this._heartbeatTimer = null;
    }
  }
}

export const wsClient = new WSClient();
export { WSClient };
