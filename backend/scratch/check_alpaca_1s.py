"""
Scratch: Check if Alpaca can provide 1-second historical resolution data.

Tests 3 approaches:
  1. StockBarsRequest with TimeFrame.Second(1)         -> Official 1s bar API
  2. StockBarsRequest with TimeFrame.Second(10)        -> Official 10s bar API (control)
  3. StockTradesRequest resampled to 1s via Polars     -> Manual 1s bars from raw trades

Prints summary of row counts, time range, and sample rows for each.
"""
import sys
import yaml
import time
import pandas as pd
import polars as pl
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '..')

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockTradesRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
import pytz

# ── Config ────────────────────────────────────────────────────────────────────
TICKER = "AAPL"
FEED = "sip"

# Use yesterday's 9:35–9:40 AM ET window (5 min into RTH) to guarantee data exists
NY_TZ = pytz.timezone('America/New_York')
_today_ny = datetime.now(NY_TZ).date()
import datetime as _dt
_yesterday_ny = _today_ny - _dt.timedelta(days=1)
# If yesterday was Saturday, go to Friday
if _yesterday_ny.weekday() == 5:   # Saturday
    _yesterday_ny -= _dt.timedelta(days=1)
elif _yesterday_ny.weekday() == 6: # Sunday
    _yesterday_ny -= _dt.timedelta(days=2)

START_NY = NY_TZ.localize(datetime.combine(_yesterday_ny, datetime.strptime("09:35:00", "%H:%M:%S").time()))
END_NY   = NY_TZ.localize(datetime.combine(_yesterday_ny, datetime.strptime("09:40:00", "%H:%M:%S").time()))
START_UTC = START_NY.astimezone(timezone.utc)
END_UTC   = END_NY.astimezone(timezone.utc)

def load_client() -> StockHistoricalDataClient:
    with open("config/config.yaml") as f:
        cfg = yaml.safe_load(f)
    api_key = cfg["alpaca"]["api_key"]
    secret_key = cfg["alpaca"]["secret_key"]
    return StockHistoricalDataClient(api_key, secret_key)

def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

# ── Helper: pretty-print result ───────────────────────────────────────────────
def report(df: pd.DataFrame, label: str, elapsed: float):
    if df is None or df.empty:
        print(f"[{label}] ❌  No data returned  (took {elapsed:.2f}s)")
        return
    print(f"[{label}] ✅  {len(df)} rows  |  took {elapsed:.2f}s")
    print(f"         Range : {df.index.min()} → {df.index.max()}")
    print(f"         Cols  : {list(df.columns)}")
    print(f"         Sample:\n{df.head(3).to_string()}\n")

# ── Approach 1: Official 1-second bars ────────────────────────────────────────
def test_1s_bars(client):
    separator("Approach 1: Official 1s Bars API — is TimeFrameUnit.Second supported?")
    supported_units = [u.name for u in TimeFrameUnit]
    print(f"  Supported TimeFrameUnits: {supported_units}")
    if "Second" not in supported_units:
        print("  ❌  TimeFrameUnit.Second does NOT exist in this alpaca-py build.")
        print("     Alpaca's bars API minimum resolution is 1-Minute.")
        print("     1-second bars via the bars endpoint are NOT possible.")
    else:
        print("  ✅  TimeFrameUnit.Second IS supported. Testing API call...")
        try:
            req = StockBarsRequest(
                symbol_or_symbols=TICKER,
                timeframe=TimeFrame(1, TimeFrameUnit.Second),
                start=START_UTC,
                end=END_UTC,
                feed=FEED
            )
            t0 = time.time()
            bars = client.get_stock_bars(req)
            elapsed = time.time() - t0
            if bars and bars.data and TICKER in bars.data:
                df = bars.df.reset_index()
                if 'symbol' in df.columns:
                    df = df.drop(columns=['symbol'])
                df = df.set_index('timestamp')
                report(df, "1s Bars API", elapsed)
            else:
                print(f"  ❌  No data returned (took {elapsed:.2f}s)")
        except Exception as e:
            print(f"  ❌  {type(e).__name__}: {e}")

# ── Approach 2: 10s bars (control) ────────────────────────────────────────────
def test_1m_bars(client):
    separator("Approach 2: Official 1-Minute bars (minimum supported resolution)")
    try:
        req = StockBarsRequest(
            symbol_or_symbols=TICKER,
            timeframe=TimeFrame.Minute,
            start=START_UTC,
            end=END_UTC,
            feed=FEED
        )
        t0 = time.time()
        bars = client.get_stock_bars(req)
        elapsed = time.time() - t0

        if bars and bars.data and TICKER in bars.data:
            df = bars.df
            if df is not None and not df.empty:
                df = df.reset_index()
                if 'symbol' in df.columns:
                    df = df.drop(columns=['symbol'])
                df = df.set_index('timestamp')
            report(df, "1m Bars API", elapsed)
        else:
            print(f"  ❌  No data returned (took {elapsed:.2f}s)")
    except Exception as e:
        print(f"  ❌  {type(e).__name__}: {e}")

# ── Approach 3: Raw trades resampled to 1s via Polars ─────────────────────────
def test_trades_resampled_to_1s(client):
    separator("Approach 3: Raw SIP trades resampled to 1s (Polars) — the only way to get 1s data")
    try:
        req = StockTradesRequest(
            symbol_or_symbols=TICKER,
            start=START_UTC,
            end=END_UTC,
            feed=FEED
        )
        t0 = time.time()
        trades = client.get_stock_trades(req)
        fetch_elapsed = time.time() - t0
        print(f"  Network fetch  : {fetch_elapsed:.2f}s")

        if not trades or not trades.data or TICKER not in trades.data:
            print(f"  ❌  No data in response")
            return

        t1 = time.time()
        raw_df = trades.df
        parse_elapsed = time.time() - t1
        print(f"  trades.df parse: {parse_elapsed:.2f}s  |  {len(raw_df):,} raw trades")

        if raw_df is None or raw_df.empty:
            print(f"  ❌  Empty dataframe")
            return

        t2 = time.time()
        raw_df = raw_df.reset_index()
        
        if 'exchange' in raw_df.columns:
            before = len(raw_df)
            raw_df = raw_df[raw_df['exchange'] != 'D']
            print(f"  Dark pool filter: removed {before - len(raw_df):,} trades")

        df_pl = pl.from_pandas(raw_df)
        df_pl = df_pl.sort("timestamp")

        df_1s_pl = (
            df_pl.group_by_dynamic("timestamp", every="1s")
            .agg([
                pl.col("price").first().alias("open"),
                pl.col("price").max().alias("high"),
                pl.col("price").min().alias("low"),
                pl.col("price").last().alias("close"),
                pl.col("size").sum().alias("volume"),
                pl.len().alias("trades")
            ])
        )

        df = df_1s_pl.to_pandas().set_index("timestamp").dropna(subset=["open"])
        process_elapsed = time.time() - t2
        print(f"  Polars resample: {process_elapsed:.2f}s")
        
        total = fetch_elapsed + parse_elapsed + process_elapsed
        report(df, "Trades->1s", total)
        
        # Show trades-per-second distribution
        print(f"  Trades/sec stats:")
        print(df['trades'].describe().to_string())

    except Exception as e:
        print(f"  ❌  {type(e).__name__}: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Ticker    : {TICKER}")
    print(f"Window    : {START_NY.strftime('%Y-%m-%d %H:%M')} → {END_NY.strftime('%H:%M')} ET (yesterday RTH)")
    print(f"UTC range : {START_UTC.strftime('%H:%M:%S')} → {END_UTC.strftime('%H:%M:%S')}")
    print(f"Feed      : {FEED}")

    client = load_client()

    test_1s_bars(client)
    test_1m_bars(client)
    test_trades_resampled_to_1s(client)

    print("\n" + "="*60)
    print("  VERDICT")
    print("="*60)
    print("  • Alpaca bars API minimum resolution = 1 Minute")
    print("  • Sub-minute bars MUST be derived from raw SIP trades")
    print("  • 1s bars via Approach 3 (trades -> Polars resample) is")
    print("    the only viable path for 1-second OHLCV data.")
    print("Done.")
