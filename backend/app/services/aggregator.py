import pandas as pd
from typing import Dict, List
import asyncio
import logging

logger = logging.getLogger(__name__)

class AggregatorService:
    def __init__(self):
        self.dataframes: Dict[str, pd.DataFrame] = {}
        self.raw_ticks: Dict[str, list] = {}
        self._on_bar_callbacks = []
        self._on_history_callbacks = []
        self._live_subscriptions: Dict[str, set] = {}
        self._daily_indicators: Dict[str, Dict[str, dict]] = {}
        self._refresh_task = None
        self._indicator_config: List[dict] = []

    # ── config ──────────────────────────────────────────────

    def set_indicator_config(self, config: list):
        self._indicator_config = config

    def _active_emas(self, timeframe: str) -> list:
        return [
            {'id': ind['id'], 'span': ind['timeframes'][timeframe]['span']}
            for ind in self._indicator_config
            if ind.get('type') == 'ema' and timeframe in ind.get('timeframes', {})
        ]

    def _active_indicator_ids(self, timeframe: str) -> list:
        return [
            ind['id']
            for ind in self._indicator_config
            if timeframe in ind.get('timeframes', {})
        ]

    def _has_vwap(self, timeframe: str) -> bool:
        return any(
            ind['id'] == 'vwap' and timeframe in ind.get('timeframes', {})
            for ind in self._indicator_config
        )

    def _daily_indicator_ids(self) -> list:
        return [
            ind['id']
            for ind in self._indicator_config
            if ind.get('type') == 'daily'
        ]

    def _emit_indicator_values(self, row, bar_data: dict, timeframe: str):
        for ind_id in self._active_indicator_ids(timeframe):
            if ind_id == 'volume':
                continue
            if ind_id in bar_data:
                continue
            val = row.get(ind_id)
            if val is not None and pd.notna(val):
                bar_data[ind_id] = float(val)
            else:
                bar_data[ind_id] = None

    # ── callbacks ───────────────────────────────────────────

    def register_bar_callback(self, callback):
        self._on_bar_callbacks.append(callback)

    def register_history_callback(self, callback):
        self._on_history_callbacks.append(callback)

    def add_live_subscription(self, ticker: str, timeframe: str):
        if ticker not in self._live_subscriptions:
            self._live_subscriptions[ticker] = set()
        self._live_subscriptions[ticker].add(timeframe)

    def remove_live_subscription(self, ticker: str, timeframe: str):
        if ticker in self._live_subscriptions:
            self._live_subscriptions[ticker].discard(timeframe)

    def start_periodic_refresh(self, interval: float = 1.0):
        async def _loop():
            while True:
                await asyncio.sleep(interval)
                for ticker, timeframes in list(self._live_subscriptions.items()):
                    for tf in list(timeframes):
                        await self._emit_current_bar(ticker, tf)
        self._refresh_task = asyncio.create_task(_loop())

    # ── compute helpers ─────────────────────────────────────

    def _compute_emas(self, ohlcv: pd.DataFrame, timeframe: str):
        for ema in self._active_emas(timeframe):
            ohlcv[ema['id']] = ohlcv['close'].ewm(span=ema['span'], adjust=False).mean()

    def _compute_vwap(self, ohlcv: pd.DataFrame):
        tp = (ohlcv['high'] + ohlcv['low'] + ohlcv['close']) / 3
        tp_vol = tp * ohlcv['volume']
        dates = ohlcv.index.normalize()
        ohlcv['vwap'] = tp_vol.groupby(dates).cumsum() / ohlcv['volume'].groupby(dates).cumsum()

    def _compute_daily_indicators(self, ticker: str):
        key = f"{ticker}_1d"
        df = self.dataframes.get(key)
        if df is None or df.empty:
            return

        close = df['close']

        indicators = {}
        for idx in df.index:
            date_str = idx.strftime('%Y-%m-%d')
            indicators[date_str] = {}

        for ind in self._indicator_config:
            if ind.get('type') != 'daily':
                continue
            tid = ind['id']
            span = ind.get('span')
            if span is None:
                continue

            if tid.startswith('d_sma'):
                series = close.rolling(window=span).mean()
            elif tid.startswith('d_ema'):
                series = close.ewm(span=span, adjust=False).mean()
            else:
                continue

            for idx in df.index:
                date_str = idx.strftime('%Y-%m-%d')
                val = series.loc[idx]
                indicators[date_str][tid] = float(val) if pd.notna(val) else None

        self._daily_indicators[ticker] = indicators
        logger.info(f"Computed daily indicators for {ticker}: {len(indicators)} days")

    def _get_daily_indicator_for_time(self, ticker: str, timestamp: float) -> dict:
        indicators = self._daily_indicators.get(ticker, {})
        if not indicators:
            return {}

        dt = pd.Timestamp(timestamp, unit='s', tz='UTC')
        date_str = dt.strftime('%Y-%m-%d')

        if date_str in indicators:
            return indicators[date_str]

        sorted_dates = sorted(indicators.keys())
        prior = None
        for d in sorted_dates:
            if d <= date_str:
                prior = d
            else:
                break
        if prior:
            return indicators[prior]

        return {}

    # ── bar building ────────────────────────────────────────

    def _build_bar_data(self, row, ticker: str, timeframe: str) -> dict:
        bar_time = float(row.name.timestamp())
        daily = self._get_daily_indicator_for_time(ticker, bar_time)

        if timeframe == '1d':
            is_regular = True
        else:
            ny_time = row.name.tz_convert('America/New_York') if row.name.tz else row.name.tz_localize('UTC').tz_convert('America/New_York')
            is_regular = 9.5 <= (ny_time.hour + ny_time.minute / 60.0) < 16.0

        bar_data = {
            'time': bar_time,
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
            'volume': float(row['volume']),
            'is_regular': is_regular,
            **{k: v for k, v in daily.items()},
        }
        self._emit_indicator_values(row, bar_data, timeframe)
        return bar_data

    def _dataframe_to_bars(self, df: pd.DataFrame, ticker: str, timeframe: str) -> List[dict]:
        bars = []
        for idx, row in df.iterrows():
            bars.append(self._build_bar_data(row, ticker, timeframe))
        return bars

    # ── emit ────────────────────────────────────────────────

    async def _emit_current_bar(self, ticker: str, timeframe: str):
        key = f"{ticker}_{timeframe}"
        df = self.dataframes.get(key)
        if df is None or df.empty:
            return
        latest = df.iloc[-1]
        bar_data = self._build_bar_data(latest, ticker, timeframe)

        for callback in self._on_bar_callbacks:
            await callback(ticker, timeframe, bar_data)

    # ── live tick processing ─────────────────────────────────

    async def on_tick(self, ticker: str, timestamp: float, price: float, volume: int):
        tick_time = pd.to_datetime(timestamp, unit='s', utc=True)
        cutoff = tick_time - pd.Timedelta(minutes=10)

        for timeframe in ['10s', '1m']:
            self._live_subscriptions.setdefault(ticker, set()).add(timeframe)
            key = f"{ticker}_{timeframe}"

            if key not in self.raw_ticks:
                self.raw_ticks[key] = []

            self.raw_ticks[key].append({
                'time': tick_time,
                'price': price,
                'volume': volume,
            })

            # Prune ticks older than 10 minutes
            self.raw_ticks[key] = [
                t for t in self.raw_ticks[key] if t['time'] >= cutoff
            ]

            await self._process_live_tick(ticker, timeframe, key)

    async def _process_live_tick(self, ticker: str, timeframe: str, key: str):
        if not self.raw_ticks[key]:
            return

        df_ticks = pd.DataFrame(self.raw_ticks[key])
        df_ticks.set_index('time', inplace=True)

        resample_rule = '10s' if timeframe == '10s' else '1min'

        live_ohlcv = df_ticks.resample(resample_rule).agg({
            'price': ['first', 'max', 'min', 'last'],
            'volume': 'sum',
        })
        live_ohlcv.columns = ['open', 'high', 'low', 'close', 'volume']
        live_ohlcv = live_ohlcv.dropna(subset=['open'])

        if live_ohlcv.empty:
            return

        existing = self.dataframes.get(key)
        if existing is not None and not existing.empty:
            hist_cols = ['open', 'high', 'low', 'close', 'volume']
            hist_only = existing[hist_cols].loc[~existing.index.isin(live_ohlcv.index)]
            ohlcv = pd.concat([hist_only, live_ohlcv])
            ohlcv.sort_index(inplace=True)
        else:
            ohlcv = live_ohlcv

        self._compute_emas(ohlcv, timeframe)

        if self._has_vwap(timeframe):
            self._compute_vwap(ohlcv)

        self.dataframes[key] = ohlcv

        latest = ohlcv.iloc[-1]
        bar_data = self._build_bar_data(latest, ticker, timeframe)

        for callback in self._on_bar_callbacks:
            await callback(ticker, timeframe, bar_data)

    async def ingest_ohlcv(self, ticker: str, timeframe: str, df: pd.DataFrame):
        key = f"{ticker}_{timeframe}"

        if key in self.dataframes:
            historical_df = self.dataframes[key]
            combined = pd.concat([historical_df, df])
            combined = combined[~combined.index.duplicated(keep='last')]
            combined.sort_index(inplace=True)
            self.dataframes[key] = combined
        else:
            self.dataframes[key] = df

        ohlcv = self.dataframes[key]

        if timeframe in ('10s', '1m'):
            self._compute_emas(ohlcv, timeframe)

            if self._has_vwap(timeframe):
                self._compute_vwap(ohlcv)

        if timeframe == '1d':
            self._compute_emas(ohlcv, timeframe)

        if timeframe == '1d':
            self._compute_daily_indicators(ticker)

        bars = self._dataframe_to_bars(ohlcv, ticker, timeframe)

        for callback in self._on_history_callbacks:
            await callback(ticker, timeframe, bars)

    async def re_emit_with_daily_indicators(self, ticker: str):
        for tf in ['10s', '1m']:
            key = f"{ticker}_{tf}"
            df = self.dataframes.get(key)
            if df is not None and not df.empty:
                bars = self._dataframe_to_bars(df, ticker, tf)
                logger.info(f"Re-emitting {key} with updated daily indicators: {len(bars)} bars")
                for callback in self._on_history_callbacks:
                    await callback(ticker, tf, bars)
