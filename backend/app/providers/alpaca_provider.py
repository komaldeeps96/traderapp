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

    # ── 1d data ────────────────────────────────────────────

    async def fetch_1d_data(self, ticker: str):
        if not self.client:
            logger.error("Alpaca client not initialized.")
            return

        if self._aggregator and f"{ticker}_1d" in self._aggregator.dataframes:
            logger.info(f"Alpaca 1d data for {ticker} already cached. Skipping fetch.")
            return

        await self._fetch_bars(ticker, TimeFrame.Day, days=365 * 3, label="1d")

    # ── 1m data ────────────────────────────────────────────

    async def fetch_1m_data(self, ticker: str):
        if not self.client:
            logger.error("Alpaca client not initialized.")
            return

        await self._fetch_bars(ticker, TimeFrame.Minute, days=30, label="1m")

    # ── generic bar fetch ──────────────────────────────────

    async def _fetch_bars(self, ticker: str, timeframe, days: int, label: str):
        try:
            end_time = datetime.now(timezone.utc) - timedelta(minutes=16)
            start_time = end_time - timedelta(days=days)

            logger.info(f"Fetching Alpaca {label} data for {ticker} from {start_time} to {end_time}")

            request_params = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=timeframe,
                start=start_time,
                end=end_time,
                feed="sip"
            )

            loop = asyncio.get_event_loop()
            bars = await loop.run_in_executor(None, self.client.get_stock_bars, request_params)

            df = pd.DataFrame()
            if bars and bars.data and ticker in bars.data:
                bars_data = bars.data[ticker]
                df = pd.DataFrame([{
                    'time': b.timestamp,
                    'open': b.open,
                    'high': b.high,
                    'low': b.low,
                    'close': b.close,
                    'volume': b.volume,
                } for b in bars_data])

                if not df.empty:
                    df.set_index('time', inplace=True)
                    df.index = pd.to_datetime(df.index, utc=True)

            if not df.empty and self._aggregator:
                logger.info(f"Alpaca returned {len(df)} {label} bars for {ticker}")
                await self._aggregator.ingest_ohlcv(ticker, label, df)

        except Exception as e:
            logger.error(f"Failed to fetch Alpaca {label} data for {ticker}: {e}", exc_info=True)
