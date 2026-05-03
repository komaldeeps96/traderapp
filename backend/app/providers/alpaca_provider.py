import yaml
import logging
import asyncio
import pandas as pd
from datetime import datetime, timedelta, timezone
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

logger = logging.getLogger(__name__)

class AlpacaProvider:
    def __init__(self, config_path="config/config.yaml"):
        self.config_path = config_path
        self.client = None
        self._aggregator = None
        self._load_config()

    def _load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            api_key = config.get('alpaca', {}).get('api_key')
            secret_key = config.get('alpaca', {}).get('secret_key')

            if api_key and secret_key:
                self.client = StockHistoricalDataClient(api_key, secret_key)
                logger.info("Alpaca client initialized.")
            else:
                logger.error("Alpaca API keys not found in config.")
        except Exception as e:
            logger.error(f"Failed to load Alpaca config: {e}")

    def set_aggregator(self, aggregator):
        self._aggregator = aggregator

    async def fetch_historical_data(self, ticker: str):
        if not self.client:
            logger.error("Alpaca client not initialized.")
            return

        if self._aggregator and f"{ticker}_1d" in self._aggregator.dataframes:
            logger.info(f"Alpaca 1d data for {ticker} already cached. Skipping fetch.")
            return

        await self._fetch_1d_data(ticker)

    async def _fetch_1d_data(self, ticker: str):
        try:
            end_time = datetime.now(timezone.utc) - timedelta(minutes=16)
            start_time = end_time - timedelta(days=365 * 3)

            logger.info(f"Fetching Alpaca 1d data for {ticker} from {start_time} to {end_time}")

            request_params = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame.Day,
                start=start_time,
                end=end_time,
                feed="sip"
            )

            loop = asyncio.get_event_loop()
            bars = await loop.run_in_executor(None, self.client.get_stock_bars, request_params)

            df_1d = pd.DataFrame()
            if bars and bars.data and ticker in bars.data:
                bars_data = bars.data[ticker]
                df_1d = pd.DataFrame([{
                    'time': b.timestamp,
                    'open': b.open,
                    'high': b.high,
                    'low': b.low,
                    'close': b.close,
                    'volume': b.volume,
                } for b in bars_data])

                if not df_1d.empty:
                    df_1d.set_index('time', inplace=True)
                    df_1d.index = pd.to_datetime(df_1d.index, utc=True)

            if not df_1d.empty and self._aggregator:
                logger.info(f"Alpaca returned {len(df_1d)} 1d bars for {ticker}")
                await self._aggregator.ingest_ohlcv(ticker, '1d', df_1d)

        except Exception as e:
            logger.error(f"Failed to fetch Alpaca 1d data for {ticker}: {e}", exc_info=True)
