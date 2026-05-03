from ib_async import IB, Stock
import asyncio
import logging
import pandas as pd

logger = logging.getLogger(__name__)

class IBKRProvider:
    def __init__(self, host='127.0.0.1', port=7496, client_id=1):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        self._subscriptions = {}
        self._aggregator = None
        self._connect_lock = asyncio.Lock()
        self._should_reconnect = False
        self._reconnect_task = None
        self._on_tick_callbacks = []
        self._contracts = {}

    # ── callbacks ──────────────────────────────────────────

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

    # ── contract cache ─────────────────────────────────────

    async def _get_contract(self, ticker: str):
        if ticker in self._contracts:
            return self._contracts[ticker]
        contract = Stock(ticker, 'SMART', 'USD')
        await self.ib.qualifyContractsAsync(contract)
        self._contracts[ticker] = contract
        return contract

    # ── connection ─────────────────────────────────────────

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

    # ── historical data ────────────────────────────────────

    async def fetch_historical(self, ticker: str):
        """Fetch 1D of 10s bars from IBKR. Skips if already cached in aggregator."""
        cache_key = f"{ticker}_10s"
        if self._aggregator and cache_key in self._aggregator.dataframes:
            logger.info(f"IBKR historical data for {ticker} already cached. Skipping fetch.")
            return

        if not await self._ensure_connected():
            logger.warning(f"IBKR is not connected. Cannot fetch historical data for {ticker}.")
            return

        contract = await self._get_contract(ticker)

        try:
            logger.info(f"Requesting 1D of 10s bars from IBKR for {ticker}")
            bars_10s = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime='',
                durationStr='1 D',
                barSizeSetting='10 secs',
                whatToShow='TRADES',
                useRTH=False,
                formatDate=2
            )

            if bars_10s and self._aggregator:
                df_10s = self._bars_to_dataframe(bars_10s)
                await self._aggregator.ingest_ohlcv(ticker, '10s', df_10s)

                df_1m = self._resample_10s_to_1m(df_10s)
                bars_1m = 0
                if not df_1m.empty:
                    await self._aggregator.ingest_ohlcv(ticker, '1m', df_1m)
                    bars_1m = len(df_1m)

                logger.info(f"IBKR historical: {len(df_10s)} 10s bars, {bars_1m} 1m bars for {ticker}")

        except Exception as e:
            logger.error(f"Failed to fetch IBKR historical data for {ticker}: {e}", exc_info=True)

    # ── realtime subscription ──────────────────────────────

    async def subscribe_realtime(self, ticker: str):
        """Subscribe to live tick-by-tick trade stream."""
        if ticker in self._subscriptions:
            logger.info(f"IBKR realtime already subscribed to {ticker}. Skipping.")
            return

        if not await self._ensure_connected():
            logger.warning(f"IBKR is not connected. Cannot subscribe to realtime data for {ticker}.")
            return

        contract = await self._get_contract(ticker)

        ticker_obj = self.ib.reqTickByTickData(contract, 'AllLast', numberOfTicks=0, ignoreSize=False)
        self._subscriptions[ticker] = {
            'contract': contract,
            'ticker_obj': ticker_obj,
            'last_tick_idx': 0,
        }

        ticker_obj.updateEvent += self._on_tick_by_tick
        logger.info(f"IBKR realtime subscribed: {ticker}")

    async def unsubscribe_realtime(self, ticker: str):
        if ticker in self._subscriptions:
            sub = self._subscriptions[ticker]
            self.ib.cancelTickByTickData(sub['contract'], 'AllLast')
            del self._subscriptions[ticker]
            logger.info(f"IBKR realtime unsubscribed: {ticker}")

    # ── tick handler ───────────────────────────────────────

    def _on_tick_by_tick(self, ticker):
        ticks = ticker.tickByTicks
        if not ticks:
            return

        symbol = ticker.contract.symbol
        sub = None
        for s in self._subscriptions.values():
            if s['ticker_obj'] is ticker:
                sub = s
                break
        if not sub:
            return

        start = sub['last_tick_idx']
        for i in range(start, len(ticks)):
            tick = ticks[i]
            timestamp = tick.time.timestamp() if tick.time else asyncio.get_event_loop().time()
            price = float(tick.price) if tick.price == tick.price else 0.0
            size = int(tick.size) if tick.size == tick.size else 0
            if price > 0 and size > 0:
                asyncio.create_task(self.emit_tick(symbol, timestamp, price, size))

        sub['last_tick_idx'] = len(ticks)

    # ── data utilities ─────────────────────────────────────

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
        df.set_index('time', inplace=True)
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, utc=True)
        elif df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        else:
            df.index = df.index.tz_convert('UTC')
        return df

    def _resample_10s_to_1m(self, df_10s: pd.DataFrame) -> pd.DataFrame:
        ohlcv_1m = df_10s.resample('1min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
        })
        ohlcv_1m = ohlcv_1m.dropna(subset=['open'])
        return ohlcv_1m
