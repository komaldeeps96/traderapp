import pandas as pd
import asyncio
import logging
from typing import Dict, List, Optional

from ..core.constants import (
    TIMEFRAMES, TIMEFRAME_1M, TIMEFRAME_1D,
    MAX_BARS_MEMORY, PERIODIC_REFRESH_INTERVAL,
    REGULAR_HOURS_START, REGULAR_HOURS_END
)

logger = logging.getLogger(__name__)


class AggregatorService:
    """Central data pipeline: storage, bar building, indicator computation, emission."""

    def __init__(self):
        self.dataframes: Dict[str, pd.DataFrame] = {}
        self._live_bars: Dict[str, dict] = {}
        self._on_bar_callbacks: list = []
        self._on_history_callbacks: list = []
        self._current_ticker: str = ''
        self._current_timeframes: set = set()
        self._daily_indicators: Dict[str, Dict[str, dict]] = {}
        self._refresh_task = None

        self._indicator_config: List[dict] = []
        self._emas_by_timeframe: Dict[str, list] = {}
        self._indicator_ids_by_timeframe: Dict[str, list] = {}
        self._timeframes_with_vwap: set = set()
        self._daily_indicator_ids: list = []

        self._bar_cache: Dict[str, tuple] = {}

    def set_indicator_config(self, config: list):
        self._indicator_config = config
        self._emas_by_timeframe.clear()
        self._indicator_ids_by_timeframe.clear()
        self._timeframes_with_vwap.clear()
        self._daily_indicator_ids.clear()
        self._bar_cache.clear()

        for tf in TIMEFRAMES:
            self._emas_by_timeframe[tf] = []
            self._indicator_ids_by_timeframe[tf] = []

        for ind in config:
            ind_type = ind.get('type')
            ind_id = ind['id']
            timeframes = ind.get('timeframes', {})

            if ind_type == 'daily':
                self._daily_indicator_ids.append(ind_id)

            for tf in TIMEFRAMES:
                if tf in timeframes:
                    self._indicator_ids_by_timeframe[tf].append(ind_id)

            if ind_type == 'ema':
                for tf in timeframes:
                    cfg = timeframes[tf]
                    self._emas_by_timeframe[tf].append({
                        'id': ind_id,
                        'span': cfg['span']
                    })

            if ind_id == 'vwap':
                for tf in timeframes:
                    self._timeframes_with_vwap.add(tf)

        logger.info(
            f"Indicator config indexed: EMAs={sum(len(v) for v in self._emas_by_timeframe.values())}, "
            f"VWAP timeframes={self._timeframes_with_vwap}, daily={self._daily_indicator_ids}"
        )

    def register_bar_callback(self, callback):
        self._on_bar_callbacks.append(callback)

    def register_history_callback(self, callback):
        self._on_history_callbacks.append(callback)

    def set_active_timeframe(self, timeframe: str):
        self._current_timeframes = {'1m', '1d'}
        if timeframe not in self._current_timeframes:
            self._current_timeframes.add(timeframe)

    def set_active_ticker(self, ticker: str):
        self._current_ticker = ticker

    def start_periodic_refresh(self, interval: float = PERIODIC_REFRESH_INTERVAL):
        async def _loop():
            while True:
                await asyncio.sleep(interval)
                ticker = self._current_ticker
                for tf in list(self._current_timeframes):
                    await self._emit_current_bar(ticker, tf)
        self._refresh_task = asyncio.create_task(_loop())

    @staticmethod
    def _compute_emas(ohlcv: pd.DataFrame, ema_configs: List[dict]):
        for ema_cfg in ema_configs:
            col = ema_cfg['id']
            ohlcv[col] = ohlcv['close'].ewm(span=ema_cfg['span'], adjust=False).mean()

    @staticmethod
    def _compute_vwap(ohlcv: pd.DataFrame):
        tp = (ohlcv['high'] + ohlcv['low'] + ohlcv['close']) / 3
        tp_vol = tp * ohlcv['volume']
        dates = ohlcv.index.normalize()
        ohlcv['vwap'] = tp_vol.groupby(dates).cumsum() / ohlcv['volume'].groupby(dates).cumsum()

    @staticmethod
    def _compute_premarket_bounds(ohlcv: pd.DataFrame):
        if ohlcv.empty:
            return
        ny_time = (
            ohlcv.index.tz_convert('America/New_York')
            if ohlcv.index.tz
            else ohlcv.index.tz_localize('UTC').tz_convert('America/New_York')
        )
        is_pre = (ny_time.hour + ny_time.minute / 60.0 >= 4.0) & (ny_time.hour + ny_time.minute / 60.0 < 9.5)
        
        pm_highs = ohlcv['high'].where(is_pre).groupby(ny_time.date).max()
        ohlcv['pm_high'] = pm_highs.reindex(ny_time.date).values

        pm_lows = ohlcv['low'].where(is_pre).groupby(ny_time.date).min()
        ohlcv['pm_low'] = pm_lows.reindex(ny_time.date).values

    def _compute_tf_indicators(self, ohlcv: pd.DataFrame, timeframe: str):
        ema_configs = self._emas_by_timeframe.get(timeframe, [])
        if ema_configs:
            self._compute_emas(ohlcv, ema_configs)
        if timeframe in self._timeframes_with_vwap:
            self._compute_vwap(ohlcv)
        if timeframe == TIMEFRAME_1M:
            self._compute_premarket_bounds(ohlcv)

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

            if tid.startswith('d_sma'):
                if span is None: continue
                series = close.rolling(window=span).mean()
            elif tid.startswith('d_ema'):
                if span is None: continue
                series = close.ewm(span=span, adjust=False).mean()
            elif tid.startswith('d_high'):
                if span is None: continue
                series = df['high'].rolling(window=span).max()
            elif tid.startswith('d_low'):
                if span is None: continue
                series = df['low'].rolling(window=span).min()
            elif tid == 'd_prev_day_high':
                series = df['high'].shift(1)
            elif tid == 'd_prev_day_low':
                series = df['low'].shift(1)
            elif tid == 'd_prev_day_close':
                series = df['close'].shift(1)
            elif tid == 'd_prev_week_high':
                weekly = df.resample('W').agg({'high': 'max'})
                series = weekly['high'].shift(1).reindex(df.index, method='ffill')
            elif tid == 'd_prev_week_low':
                weekly = df.resample('W').agg({'low': 'min'})
                series = weekly['low'].shift(1).reindex(df.index, method='ffill')
            elif tid == 'd_prev_week_close':
                weekly = df.resample('W').agg({'close': 'last'})
                series = weekly['close'].shift(1).reindex(df.index, method='ffill')
            elif tid == 'd_prev_month_high':
                try:
                    monthly = df.resample('ME').agg({'high': 'max'})
                except Exception:
                    monthly = df.resample('M').agg({'high': 'max'})
                series = monthly['high'].shift(1).reindex(df.index, method='ffill')
            elif tid == 'd_prev_month_low':
                try:
                    monthly = df.resample('ME').agg({'low': 'min'})
                except Exception:
                    monthly = df.resample('M').agg({'low': 'min'})
                series = monthly['low'].shift(1).reindex(df.index, method='ffill')
            elif tid == 'd_prev_month_close':
                try:
                    monthly = df.resample('ME').agg({'close': 'last'})
                except Exception:
                    monthly = df.resample('M').agg({'close': 'last'})
                series = monthly['close'].shift(1).reindex(df.index, method='ffill')
            else:
                continue

            for idx in df.index:
                date_str = idx.strftime('%Y-%m-%d')
                val = series.loc[idx]
                indicators[date_str][tid] = float(val) if pd.notna(val) else None

        self._daily_indicators[ticker] = indicators
        logger.info(f"Computed daily indicators for {ticker}: {len(indicators)} days")

    @staticmethod
    def _get_daily_indicator_for_time(daily_cache: dict, timestamp: float) -> dict:
        if not daily_cache:
            return {}
        dt = pd.Timestamp(timestamp, unit='s', tz='UTC')
        date_str = dt.strftime('%Y-%m-%d')
        if date_str in daily_cache:
            return daily_cache[date_str]
        sorted_dates = sorted(daily_cache.keys())
        prior = None
        for d in sorted_dates:
            if d <= date_str:
                prior = d
            else:
                break
        if prior:
            return daily_cache[prior]
        return {}

    def _build_bar_data(self, row, ticker: str, timeframe: str) -> dict:
        bar_time = float(row.name.timestamp())
        daily = self._get_daily_indicator_for_time(
            self._daily_indicators.get(ticker, {}), bar_time
        )

        if timeframe == TIMEFRAME_1D:
            is_regular = True
        else:
            ny_time = (
                row.name.tz_convert('America/New_York')
                if row.name.tz
                else row.name.tz_localize('UTC').tz_convert('America/New_York')
            )
            is_regular = REGULAR_HOURS_START <= (ny_time.hour + ny_time.minute / 60.0) < REGULAR_HOURS_END

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

        active_ids = self._indicator_ids_by_timeframe.get(timeframe, [])
        for ind_id in active_ids:
            if ind_id == 'volume' or ind_id in bar_data:
                continue
            val = row.get(ind_id)
            if val is not None and pd.notna(val):
                bar_data[ind_id] = float(val)
            else:
                bar_data[ind_id] = None

        return bar_data

    def _dataframe_to_bars(self, df: pd.DataFrame, ticker: str, timeframe: str, force: bool = False) -> List[dict]:
        cache_key = f"{ticker}_{timeframe}"
        df_hash = hash(tuple(df.index)) if not df.empty else None

        if not force and cache_key in self._bar_cache:
            cached_hash, cached_bars = self._bar_cache[cache_key]
            if cached_hash == df_hash:
                return cached_bars

        bars = []
        for idx, row in df.iterrows():
            bars.append(self._build_bar_data(row, ticker, timeframe))

        if len(bars) > MAX_BARS_MEMORY:
            bars = bars[-MAX_BARS_MEMORY:]

        self._bar_cache[cache_key] = (df_hash, bars)
        return bars

    async def _emit_current_bar(self, ticker: str, timeframe: str):
        if not ticker:
            return
        key = f"{ticker}_{timeframe}"
        state = self._live_bars.get(key)
        if state is None:
            df = self.dataframes.get(key)
            if df is None or df.empty:
                return
            latest = df.iloc[-1]
            bar_data = self._build_bar_data(latest, ticker, timeframe)
        else:
            bar_data = self._live_bar_to_data(state, ticker, timeframe)

        for callback in self._on_bar_callbacks:
            await callback(ticker, timeframe, bar_data)

    def _live_bar_to_data(self, state: dict, ticker: str, timeframe: str) -> dict:
        bar_time = float(state['period'])
        daily = self._get_daily_indicator_for_time(
            self._daily_indicators.get(ticker, {}), bar_time
        )

        if timeframe == TIMEFRAME_1D:
            is_regular = True
        else:
            dt = pd.Timestamp(state['period'], unit='s', tz='UTC')
            ny_time = dt.tz_convert('America/New_York')
            is_regular = REGULAR_HOURS_START <= (ny_time.hour + ny_time.minute / 60.0) < REGULAR_HOURS_END

        bar_data = {
            'time': bar_time,
            'open': float(state['open']),
            'high': float(state['high']),
            'low': float(state['low']),
            'close': float(state['close']),
            'volume': float(state['volume']),
            'is_regular': is_regular,
            **daily,
        }

        return bar_data

    def _bar_period(self, timestamp: float, timeframe: str) -> float:
        if timeframe == TIMEFRAME_1D:
            dt = pd.Timestamp(timestamp, unit='s', tz='UTC')
            return dt.normalize().timestamp()
        else:
            # 1m: floor to nearest 60-second boundary
            period_ts = (int(timestamp) // 60) * 60
            return float(period_ts)

    async def on_tick(self, ticker: str, timestamp: float, price: float, volume: int):
        if not self._current_ticker:
            return

        for tf in list(self._current_timeframes):
            key = f"{ticker}_{tf}"
            state = self._live_bars.get(key)
            period = self._bar_period(timestamp, tf)

            if state is None or period != state['period']:
                if state is not None:
                    await self._finalize_bar(ticker, tf, state)
                self._live_bars[key] = {
                    'period': period,
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': volume,
                }
            else:
                state['high'] = max(state['high'], price)
                state['low'] = min(state['low'], price)
                state['close'] = price
                state['volume'] += volume

    async def _finalize_bar(self, ticker: str, timeframe: str, state: dict):
        row = pd.DataFrame([{
            'open': state['open'],
            'high': state['high'],
            'low': state['low'],
            'close': state['close'],
            'volume': float(state['volume']),
        }], index=[pd.to_datetime(state['period'], unit='s', utc=True)])

        key = f"{ticker}_{timeframe}"
        existing = self.dataframes.get(key)

        if existing is not None and not existing.empty:
            ohlcv = pd.concat([existing, row])
            ohlcv = ohlcv[~ohlcv.index.duplicated(keep='last')]
            ohlcv.sort_index(inplace=True)
        else:
            ohlcv = row

        self._compute_tf_indicators(ohlcv, timeframe)
        self.dataframes[key] = ohlcv
        self._bar_cache.pop(key, None)

        bar_data = self._build_bar_data(row.iloc[0], ticker, timeframe)

        for callback in self._on_bar_callbacks:
            await callback(ticker, timeframe, bar_data)

    async def ingest_ohlcv(self, ticker: str, timeframe: str, df: pd.DataFrame, source: Optional[str] = None):
        key = f"{ticker}_{timeframe}"

        if timeframe == TIMEFRAME_1M and source == 'alpaca' and key in self.dataframes:
            # IBKR bars already loaded — merge Alpaca underneath (keep IBKR where overlap)
            existing = self.dataframes[key]
            combined = pd.concat([df, existing])  # existing (IBKR) appended last
            combined = combined[~combined.index.duplicated(keep='last')]  # keep IBKR
            combined.sort_index(inplace=True)
            self.dataframes[key] = combined
        elif key in self.dataframes:
            historical_df = self.dataframes[key]
            combined = pd.concat([historical_df, df])
            combined = combined[~combined.index.duplicated(keep='last')]
            combined.sort_index(inplace=True)
            self.dataframes[key] = combined
        else:
            self.dataframes[key] = df

        ohlcv = self.dataframes[key]

        if timeframe == TIMEFRAME_1M:
            self._compute_tf_indicators(ohlcv, timeframe)

        if timeframe == TIMEFRAME_1D:
            ema_configs = self._emas_by_timeframe.get(TIMEFRAME_1D, [])
            if ema_configs:
                self._compute_emas(ohlcv, ema_configs)
            self._compute_daily_indicators(ticker)
            await self.re_emit_with_daily_indicators(ticker)

        self._bar_cache.pop(key, None)

        bars = self._dataframe_to_bars(ohlcv, ticker, timeframe, force=True)

        for callback in self._on_history_callbacks:
            await callback(ticker, timeframe, bars)

    async def re_emit_with_daily_indicators(self, ticker: str):
        for tf in [TIMEFRAME_1M]:
            key = f"{ticker}_{tf}"
            df = self.dataframes.get(key)
            if df is not None and not df.empty:
                bars = self._dataframe_to_bars(df, ticker, tf, force=True)
                logger.info(f"Re-emitting {key} with updated daily indicators: {len(bars)} bars")
                for callback in self._on_history_callbacks:
                    await callback(ticker, tf, bars)

    def cleanup_ticker(self, ticker: str = None):
        t = ticker or self._current_ticker
        if not t:
            return
        for tf in TIMEFRAMES:
            key = f"{t}_{tf}"
            self.dataframes.pop(key, None)
            self._live_bars.pop(key, None)
            self._bar_cache.pop(key, None)
        self._daily_indicators.pop(t, None)
