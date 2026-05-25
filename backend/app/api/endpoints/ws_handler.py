import json
import asyncio
import logging
from fastapi import WebSocket, WebSocketDisconnect

from ...core.constants import TIMEFRAMES, DEFAULT_TIMEFRAME
from ...services.container import get_container

logger = logging.getLogger(__name__)


async def websocket_endpoint(websocket: WebSocket):
    container = get_container()
    conn_mgr = container.connection_manager
    await conn_mgr.connect(websocket)

    aggregator = container.aggregator
    state_mgr = container.state_manager
    ibkr = container.ibkr_provider
    alpaca = container.alpaca_provider

    async def on_bar_update(ticker: str, timeframe: str, bar_data: dict):
        await conn_mgr.send({
            "type": "bar_update",
            "ticker": ticker,
            "timeframe": timeframe,
            "data": bar_data,
        })

    async def on_history(ticker: str, timeframe: str, bars: list):
        logger.info(f"History ready: {ticker}/{timeframe} -> {len(bars)} bars")
        await conn_mgr.send({
            "type": "bar_history",
            "ticker": ticker,
            "timeframe": timeframe,
            "data": bars,
        })

    async def send_cached_history(ticker: str, timeframe: str):
        key = f"{ticker}_{timeframe}"
        df = aggregator.dataframes.get(key)
        if df is not None and not df.empty:
            bars = aggregator._dataframe_to_bars(df, ticker, timeframe)
            logger.info(f"Sending cached history: {key} -> {len(bars)} bars")
            await conn_mgr.send({
                "type": "bar_history",
                "ticker": ticker,
                "timeframe": timeframe,
                "data": bars,
            })
        else:
            logger.info(f"No cached history yet for {key}, will arrive via on_history callback")

    # Clear previous registrations to prevent callback accumulation on reconnect
    aggregator._on_bar_callbacks.clear()
    aggregator._on_history_callbacks.clear()
    aggregator.register_bar_callback(on_bar_update)
    aggregator.register_history_callback(on_history)

    current_ticker = ''

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            logger.info(f"Received: {message}")

            action = message.get("action")
            ticker = message.get("ticker", "").upper()
            timeframe = message.get("timeframe", DEFAULT_TIMEFRAME)

            if action == "subscribe" and ticker:
                if timeframe not in TIMEFRAMES:
                    await conn_mgr.send({
                        "type": "error",
                        "message": f"Unsupported timeframe '{timeframe}'. Supported: {', '.join(TIMEFRAMES)}.",
                    })
                    continue

                current_ticker = ticker
                await state_mgr.save_state(ticker, timeframe)

                await ibkr.unsubscribe_realtime()
                aggregator.cleanup_ticker()
                aggregator.set_active_timeframe(timeframe)
                aggregator.set_active_ticker(ticker)
                await send_cached_history(ticker, timeframe)

                asyncio.create_task(ibkr.fetch_recent_1m_bars(ticker))
                asyncio.create_task(alpaca.fetch_1d_data(ticker))
                asyncio.create_task(alpaca.fetch_1m_data(ticker))
                await ibkr.subscribe_realtime(ticker)

            elif action == "ping":
                pass

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        conn_mgr.disconnect()
