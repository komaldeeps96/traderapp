import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.constants import DEFAULT_TIMEFRAME, INDICATORS_CONFIG_PATH
from .core.logging_config import setup_logging
from .api.router import api_router
from .api.endpoints.ws_handler import websocket_endpoint
from .services.container import get_container

# Setup core backend logging configurations for TraderApp dashboard
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

app.include_router(api_router)
app.websocket("/ws")(websocket_endpoint)


@app.on_event("startup")
async def startup_event():
    logger.info("Starting up TraderApp backend...")

    container = get_container()
    container.init_indicators(INDICATORS_CONFIG_PATH)
    container.aggregator.start_periodic_refresh()

    await container.ibkr_provider.connect()

    ticker = container.state_manager.get_active_ticker()
    if ticker:
        logger.info(f"Loading initial active ticker: {ticker}")
        timeframe = container.state_manager.get_active_timeframe()
        await container.state_manager.save_state(ticker, timeframe or DEFAULT_TIMEFRAME)
        container.aggregator.set_active_timeframe(timeframe or DEFAULT_TIMEFRAME)
        container.aggregator.set_active_ticker(ticker)
        await container.ibkr_provider.fetch_recent_1m_bars(ticker)
        await container.ibkr_provider.subscribe_realtime(ticker)
        asyncio.create_task(container.alpaca_provider.fetch_1d_data(ticker))
        asyncio.create_task(container.alpaca_provider.fetch_1m_data(ticker))


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down...")
    container = get_container()
    await container.ibkr_provider.disconnect()
