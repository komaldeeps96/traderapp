from ib_async import IB, Stock
import asyncio
import logging
import pandas as pd

from ..core.constants import (
    IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID,
    TICK_BY_TICK_TYPE,
)

logger = logging.getLogger(__name__)


class IBKRProvider:
    def __init__(self, host=IBKR_HOST, port=IBKR_PORT, client_id=IBKR_CLIENT_ID):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        self._subscription = None
        self._fetch_task = None
        self._aggregator = None
        self._connect_lock = asyncio.Lock()
        self._should_reconnect = False
        self._reconnect_task = None
        self._on_tick_callbacks = []
        self._contracts = {}

    def register_callback(self, callback):
        self._on_tick_callbacks.append(callback)

    async def emit_tick(self, ticker: str, timestamp: float, price: float, volume: int):
        for callback in self._on_tick_callbacks:
            try:
                await callback(ticker, timestamp, price, volume)
            except Exception as e:
                logger.error(f"Error in tick callback: {e}", exc_info=True)

    def set_aggregator(self, aggregator):
        self._aggregator = aggregator

    async def _get_contract(self, ticker: str):
        if ticker in self._contracts:
            return self._contracts[ticker]
        contract = Stock(ticker, 'SMART', 'USD')
        await self.ib.qualifyContractsAsync(contract)
        self._contracts[ticker] = contract
        return contract

    def _setup_disconnect_handler(self):
        self.ib.disconnectedEvent += self._on_disconnected

    def _on_disconnected(self):
        logger.warning("IBKR connection lost. Will attempt reconnection...")
        asyncio.create_task(self._reconnect_loop())

    async def _try_connect_once(self):
        await self.ib.connectAsync(self.host, self.port, clientId=self.client_id, readonly=True)
        logger.info("Connected to IBKR TWS/Gateway.")
        self._setup_disconnect_handler()

    async def connect(self):
        self._should_reconnect = True
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        attempt = 0
        while self._should_reconnect and not self.ib.isConnected():
            async with self._connect_lock:
                if self.ib.isConnected():
                    return
                attempt += 1
                delay = min(2 ** min(attempt - 1, 5), 30)
                try:
                    logger.info(f"IBKR connect attempt {attempt}...")
                    await self._try_connect_once()
                except Exception as e:
                    logger.warning(f"IBKR connect failed (attempt {attempt}): {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)

    async def disconnect(self):
        self._should_reconnect = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        self.ib.disconnectedEvent -= self._on_disconnected
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Disconnected from IBKR.")
        self._contracts.clear()

    async def _ensure_connected(self):
        if self.ib.isConnected():
            return True
        async with self._connect_lock:
            if self.ib.isConnected():
                return True
            try:
                logger.info("IBKR not connected, attempting connect now...")
                await self._try_connect_once()
                return True
            except Exception as e:
                logger.warning(f"IBKR connection failed: {e}")
                return False

    async def fetch_recent_1m_bars(self, ticker: str):
        """Fetch last 1 hour of 1-minute bars from IBKR and ingest as '1m'.

        Single reqHistoricalDataAsync call — no pagination, no pacing concerns.
        useRTH=False includes pre-market and after-hours.
        """
        if self._fetch_task and not self._fetch_task.done():
            self._fetch_task.cancel()
        self._fetch_task = asyncio.current_task()

        if not await self._ensure_connected():
            self._fetch_task = None
            logger.warning(f"IBKR not connected. Cannot fetch 1m bars for {ticker}.")
            return

        contract = await self._get_contract(ticker)

        try:
            logger.info(f"Fetching 1m bars (1 hour) from IBKR for {ticker}")
            bars = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime='',
                durationStr='3600 S',
                barSizeSetting='1 min',
                whatToShow='TRADES',
                useRTH=False,
                formatDate=2,
            )

            if not bars or not self._aggregator:
                logger.warning(f"IBKR 1m bars: got empty response for {ticker}")
                return

            df_1m = self._bars_to_dataframe(bars)

            if not df_1m.empty:
                await self._aggregator.ingest_ohlcv(ticker, '1m', df_1m, source='ibkr')

            logger.info(f"IBKR 1m bars: {len(df_1m)} bars for {ticker}")

        except Exception as e:
            logger.error(f"Failed to fetch IBKR 1m bars for {ticker}: {e}", exc_info=True)
        finally:
            if self._fetch_task is asyncio.current_task():
                self._fetch_task = None



    async def subscribe_realtime(self, ticker: str):
        if self._subscription is not None:
            logger.info(f"Already subscribed. Unsubscribing first.")
            await self.unsubscribe_realtime()

        if not await self._ensure_connected():
            logger.warning(f"IBKR not connected. Cannot subscribe to realtime for {ticker}.")
            return

        contract = await self._get_contract(ticker)

        ticker_obj = self.ib.reqTickByTickData(contract, TICK_BY_TICK_TYPE, numberOfTicks=0)
        ticker_obj.updateEvent += self._on_tick_by_tick

        self._subscription = {
            'ticker': ticker,
            'contract': contract,
            'ticker_obj': ticker_obj,
        }

        logger.info(f"IBKR realtime subscribed (tick-by-tick AllLast): {ticker}")

    async def unsubscribe_realtime(self, ticker: str = None):
        if self._fetch_task and not self._fetch_task.done():
            self._fetch_task.cancel()
            self._fetch_task = None
        if self._subscription is None:
            return
        sub = self._subscription
        self._subscription = None
        self.ib.cancelTickByTickData(sub['contract'], TICK_BY_TICK_TYPE)
        logger.info(f"IBKR realtime unsubscribed: {sub['ticker']}")

    def _on_tick_by_tick(self, tick):
        sub = self._subscription
        if not sub or sub['ticker_obj'] is not tick:
            return

        if not tick.tickByTicks:
            return
        tbt = tick.tickByTicks[-1]
        tick.tickByTicks.clear()

        price = float(tbt.price) if tbt.price == tbt.price else 0.0
        size = int(tbt.size) if tbt.size == tbt.size else 0

        if tbt.time:
            timestamp = tbt.time.timestamp()
        else:
            from datetime import datetime, timezone
            timestamp = datetime.now(timezone.utc).timestamp()

        if price > 0 and size > 0:
            asyncio.create_task(self.emit_tick(sub['ticker'], timestamp, price, size))

    def _bars_to_dataframe(self, bars) -> pd.DataFrame:
        data = []
        for b in bars:
            data.append({
                'time': b.date,
                'open': b.open,
                'high': b.high,
                'low': b.low,
                'close': b.close,
                'volume': float(b.volume),
            })
        df = pd.DataFrame(data)
        if not df.empty:
            df.set_index('time', inplace=True)
            df.index = pd.to_datetime(df.index, utc=True)
        return df
