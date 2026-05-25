import yaml
import logging
import asyncio
import pandas as pd
from datetime import datetime, timedelta, timezone
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from ..core.constants import CONFIG_PATH

logger = logging.getLogger(__name__)

class AlpacaProvider:
    def __init__(self, config_path=CONFIG_PATH):
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

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today_start - timedelta(days=365 * 3)
        end = today_start
        await self._fetch_bars_range(ticker, TimeFrame.Day, start, "1d", end=end)

    # ── 1m data ────────────────────────────────────────────

    async def fetch_1m_data(self, ticker: str):
        if not self.client:
            logger.error("Alpaca client not initialized.")
            return

        now = datetime.now(timezone.utc)
        start = now - timedelta(days=5)
        end = now - timedelta(minutes=30)
        await self._fetch_bars_range(ticker, TimeFrame.Minute, start, "1m", end=end)

    # ── generic bar fetch ──────────────────────────────────

    async def _fetch_bars_range(self, ticker: str, timeframe, start: datetime, label: str, end: datetime = None):
        try:
            end_time = end or (datetime.now(timezone.utc) - timedelta(minutes=16))

            logger.info(f"Fetching Alpaca {label} data for {ticker} from {start} to {end_time}")

            request_params = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=timeframe,
                start=start,
                end=end_time,
                feed="sip"
            )

            loop = asyncio.get_running_loop()
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
