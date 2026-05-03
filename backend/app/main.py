import asyncio
import json
import logging
import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List

from .providers.ibkr_provider import IBKRProvider
from .providers.alpaca_provider import AlpacaProvider
from .services.aggregator import AggregatorService

from .logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="TraderApp Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

aggregator = AggregatorService()

ibkr_provider = IBKRProvider(port=7496)
ibkr_provider.set_aggregator(aggregator)

alpaca_provider = AlpacaProvider(config_path="config/config.yaml")
alpaca_provider.set_aggregator(aggregator)

def update_config_ticker(ticker: str):
    config_path = "config/config.yaml"
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f) or {}
        if 'state' not in config:
            config['state'] = {}
        config['state']['active_ticker'] = ticker
        with open(config_path, 'w') as f:
            yaml.dump(config, f)
    except Exception as e:
        logger.error(f"Failed to update config ticker: {e}")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, set] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def send_to(self, websocket: WebSocket, message: dict):
        """Send a message to a single specific client."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending to client: {e}")

    async def broadcast(self, message: dict):
        """Send a message to all connected clients."""
        if not self.active_connections:
            return
        msg_text = json.dumps(message)
        for connection in list(self.active_connections):
            try:
                await connection.send_text(msg_text)
            except Exception as e:
                logger.error(f"Error broadcasting: {e}")

manager = ConnectionManager()

# Live tick → aggregator → broadcast single bar update
ibkr_provider.register_callback(aggregator.on_tick)

async def on_bar_update(ticker: str, timeframe: str, bar_data: dict):
    await manager.broadcast({
        "type": "bar_update",
        "ticker": ticker,
        "timeframe": timeframe,
        "data": bar_data
    })

# History from batch processing → broadcast to all clients
# (only called once per ticker on first subscribe)
async def on_history(ticker: str, timeframe: str, bars: list):
    logger.info(f"Broadcasting history: {ticker}/{timeframe} -> {len(bars)} bars")
    await manager.broadcast({
        "type": "bar_history",
        "ticker": ticker,
        "timeframe": timeframe,
        "data": bars
    })

aggregator.register_bar_callback(on_bar_update)
aggregator.register_history_callback(on_history)


async def send_cached_history(websocket: WebSocket, ticker: str, timeframe: str):
    """
    Immediately send whatever history the aggregator already has
    for this ticker+timeframe directly to one client.
    Called on every subscribe so timeframe switches always get full history.
    """
    key = f"{ticker}_{timeframe}"
    df = aggregator.dataframes.get(key)

    if df is not None and not df.empty:
        bars = aggregator._dataframe_to_bars(df, ticker, timeframe)
        logger.info(f"Sending cached history to client: {key} -> {len(bars)} bars")
        await manager.send_to(websocket, {
            "type": "bar_history",
            "ticker": ticker,
            "timeframe": timeframe,
            "data": bars
        })
    else:
        logger.info(f"No cached history yet for {key}, will arrive via on_history callback")


@app.get("/api/active-ticker")
async def get_active_ticker():
    try:
        with open("config/config.yaml", 'r') as f:
            config = yaml.safe_load(f) or {}
        active_ticker = config.get('state', {}).get('active_ticker')
        return {"active_ticker": active_ticker}
    except Exception as e:
        logger.error(f"Failed to read active ticker: {e}")
        return {"active_ticker": None}

@app.get("/api/indicators")
async def get_indicators():
    try:
        with open("config/indicators.yaml", 'r') as f:
            config = yaml.safe_load(f) or {}
        return config.get('indicators', [])
    except Exception as e:
        logger.error(f"Failed to read indicators config: {e}")
        return []

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up TraderApp backend...")
    await ibkr_provider.connect()
    
    aggregator.start_periodic_refresh(1.0)
    
    try:
        with open("config/indicators.yaml", 'r') as f:
            indicators_config = yaml.safe_load(f) or {}
        aggregator.set_indicator_config(indicators_config.get('indicators', []))
        logger.info(f"Loaded {len(indicators_config.get('indicators', []))} indicators from config")
    except Exception as e:
        logger.warning(f"Could not load indicators config: {e}")

    try:
        with open("config/config.yaml", 'r') as f:
            config = yaml.safe_load(f) or {}
        active_ticker = config.get('state', {}).get('active_ticker')
        if active_ticker:
            logger.info(f"Loading initial active ticker: {active_ticker}")
            await ibkr_provider.fetch_historical(active_ticker)
            await ibkr_provider.subscribe_realtime(active_ticker)
            asyncio.create_task(alpaca_provider.fetch_1d_data(active_ticker))
            asyncio.create_task(alpaca_provider.fetch_1m_data(active_ticker))
    except Exception as e:
        logger.error(f"Failed to load initial ticker: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down...")
    await ibkr_provider.disconnect()

async def cleanup_stale_ibkr(current_ticker: str = None):
    """Unsubscribe IBKR streams for any ticker not currently watched.
    If current_ticker is None, unsubscribes everything (e.g. on disconnect)."""
    for stale in list(ibkr_provider._subscriptions.keys()):
        if stale != current_ticker:
            await ibkr_provider.unsubscribe_realtime(stale)
            # Also clean aggregator live subscriptions for the stale ticker
            for tf in list(aggregator._live_subscriptions.get(stale, [])):
                aggregator.remove_live_subscription(stale, tf)
            logger.info(f"Cleaned up stale subscription: {stale}")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            logger.info(f"Received: {message}")

            action = message.get("action")
            ticker = message.get("ticker", "").upper()
            timeframe = message.get("timeframe", "1m")

            if action == "subscribe" and ticker:
                if timeframe not in ["10s", "1m", "1d"]:
                    await manager.send_to(websocket, {
                        "type": "error",
                        "message": f"Unsupported timeframe '{timeframe}'. Supported: 10s, 1m, 1d."
                    })
                    continue
                
                manager.subscriptions[websocket].add(ticker)

                update_config_ticker(ticker)

                await send_cached_history(websocket, ticker, timeframe)

                aggregator.add_live_subscription(ticker, timeframe)

                async def fetch_and_subscribe(t: str):
                    await ibkr_provider.fetch_historical(t)
                    await ibkr_provider.subscribe_realtime(t)
                    asyncio.create_task(alpaca_provider.fetch_1d_data(t))
                    asyncio.create_task(alpaca_provider.fetch_1m_data(t))
                
                asyncio.create_task(fetch_and_subscribe(ticker))

                # Clean up IBKR streams for tickers no longer watched
                await cleanup_stale_ibkr(ticker)

            elif action == "unsubscribe" and ticker:
                manager.subscriptions[websocket].discard(ticker)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await cleanup_stale_ibkr()  # Single client — clean up everything
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        manager.disconnect(websocket)
        await cleanup_stale_ibkr()
