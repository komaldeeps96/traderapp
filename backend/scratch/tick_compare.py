"""
Tick Data Comparison: IBKR vs Alpaca
Fetches raw trade ticks for AAPL, yesterday 9:00-10:00 AM ET.
Caches to scratch/data/ as parquet to avoid re-downloading.
Skips FINRA DF (exchange 'D') in Alpaca (late prints).
"""
import asyncio
import os
import sys
import yaml
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ── Config ────────────────────────────────────────────────────────────────────
TICKER = "AAPL"
NY_TZ = pytz.timezone('America/New_York')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# Yesterday's date, skip weekends
_today = datetime.now(NY_TZ).date()
_yesterday = _today - timedelta(days=1)
if _yesterday.weekday() == 5:    # Saturday -> Friday
    _yesterday -= timedelta(days=1)
elif _yesterday.weekday() == 6:  # Sunday -> Friday
    _yesterday -= timedelta(days=2)

START_NY = NY_TZ.localize(datetime.combine(_yesterday, datetime.strptime("09:00:00", "%H:%M:%S").time()))
END_NY   = NY_TZ.localize(datetime.combine(_yesterday, datetime.strptime("10:00:00", "%H:%M:%S").time()))
START_UTC = START_NY.astimezone(timezone.utc)
END_UTC   = END_NY.astimezone(timezone.utc)

DATE_STR = _yesterday.strftime('%Y%m%d')
ALPACA_FILE = os.path.join(DATA_DIR, f'{TICKER}_{DATE_STR}_alpaca_ticks.parquet')
IBKR_FILE   = os.path.join(DATA_DIR, f'{TICKER}_{DATE_STR}_ibkr_ticks.parquet')

# Alpaca CTA -> Exchange Name mapping
ALPACA_EXCHANGE_MAP = {
    'A': 'NYSE_AMER', 'B': 'NASDAQ_BX', 'C': 'NSX', 'D': 'FINRA_ADF',
    'H': 'MIAX', 'J': 'EDGA', 'K': 'EDGX', 'M': 'CHX', 'N': 'NYSE',
    'P': 'ARCA', 'Q': 'NASDAQ', 'T': 'NASDAQ_TRF', 'V': 'IEX',
    'W': 'CBOE', 'X': 'NASDAQ_PSX', 'Y': 'BYX', 'Z': 'BZX',
}

# IBKR exchange name normalisation (map IBKR names to unified names)
IBKR_EXCHANGE_MAP = {
    'ISLAND': 'NASDAQ', 'ARCA': 'ARCA', 'NYSE': 'NYSE', 'IEX': 'IEX',
    'BYX': 'BYX', 'EDGX': 'EDGX', 'EDGA': 'EDGA', 'BEX': 'NASDAQ_BX',
    'PSX': 'NASDAQ_PSX', 'CHX': 'CHX', 'PEARL': 'MIAX', 'MEMX': 'MEMX',
    'LTSE': 'LTSE', 'DRCTEDGE': 'EDGX', 'AMEX': 'NYSE_AMER',
    'BZX': 'BZX', 'CBOE': 'CBOE',
}


def load_config():
    cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml')
    with open(cfg_path) as f:
        return yaml.safe_load(f)


# ── Alpaca Fetch ──────────────────────────────────────────────────────────────
def fetch_alpaca_ticks():
    """Fetch raw trade ticks from Alpaca SIP feed."""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockTradesRequest

    cfg = load_config()
    client = StockHistoricalDataClient(cfg['alpaca']['api_key'], cfg['alpaca']['secret_key'])

    print(f"  Fetching Alpaca SIP trades for {TICKER} ...")
    req = StockTradesRequest(
        symbol_or_symbols=TICKER,
        start=START_UTC,
        end=END_UTC,
        feed="sip"
    )
    trades = client.get_stock_trades(req)
    trade_list = trades.data.get(TICKER, [])
    print(f"  Got {len(trade_list):,} raw trades from Alpaca")

    rows = []
    for t in trade_list:
        rows.append({
            'timestamp': t.timestamp,
            'price': float(t.price),
            'size': int(t.size),
            'exchange': t.exchange,
            'conditions': ','.join(t.conditions) if t.conditions else '',
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    return df


# ── IBKR Fetch (backward pagination via endDateTime) ─────────────────────────
async def fetch_ibkr_ticks():
    """Fetch raw trade ticks from IBKR with backward pagination (max 1000/request).
    
    Uses endDateTime going backwards to avoid infinite loops when many ticks
    share the same second (IBKR only has second-level timestamp precision).
    """
    from ib_async import IB, Stock

    ib = IB()
    await ib.connectAsync('127.0.0.1', 7496, clientId=99, readonly=True)
    contract = Stock(TICKER, 'SMART', 'USD')
    await ib.qualifyContractsAsync(contract)

    all_ticks = []
    current_end = END_UTC.strftime("%Y%m%d %H:%M:%S UTC")
    start_dt = START_UTC

    print(f"  Fetching IBKR historical ticks for {TICKER} (backward pagination, 1000/page) ...")
    page = 0
    while True:
        page += 1
        ticks = await ib.reqHistoricalTicksAsync(
            contract,
            startDateTime='',
            endDateTime=current_end,
            numberOfTicks=1000,
            whatToShow='TRADES',
            useRth=False
        )

        if not ticks:
            break

        # Filter to our window (>= start)
        filtered = [t for t in ticks if t.time.astimezone(timezone.utc) >= start_dt]
        before_count = len(all_ticks)
        all_ticks = filtered + all_ticks  # prepend (going backwards)
        print(f"    Page {page}: got {len(ticks)} ticks, {len(filtered)} in window (total: {len(all_ticks):,})")

        if len(ticks) < 1000:
            break

        # Oldest tick in this batch
        oldest = ticks[0].time.astimezone(timezone.utc)
        if oldest <= start_dt:
            break

        # Move end backward to the oldest tick's time
        current_end = ticks[0].time.strftime("%Y%m%d %H:%M:%S UTC")
        await asyncio.sleep(0.2)  # pacing

    ib.disconnect()
    print(f"  Got {len(all_ticks):,} total ticks from IBKR")

    rows = []
    for t in all_ticks:
        rows.append({
            'timestamp': t.time,
            'price': float(t.price),
            'size': int(t.size),
            'exchange': t.exchange,
            'conditions': t.specialConditions if t.specialConditions else '',
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        # Deduplicate (pagination overlap at boundary seconds)
        df = df.drop_duplicates(subset=['timestamp', 'price', 'size', 'exchange'])
        df = df.sort_values('timestamp').reset_index(drop=True)
    return df


# ── Load / Cache ──────────────────────────────────────────────────────────────
async def load_data():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Alpaca
    if os.path.exists(ALPACA_FILE):
        print(f"  Loading cached Alpaca data: {ALPACA_FILE}")
        df_alpaca = pd.read_parquet(ALPACA_FILE)
        df_alpaca['timestamp'] = pd.to_datetime(df_alpaca['timestamp'], utc=True)
    else:
        df_alpaca = fetch_alpaca_ticks()
        if not df_alpaca.empty:
            df_alpaca.to_parquet(ALPACA_FILE, index=False)
            print(f"  Saved -> {ALPACA_FILE}")

    # IBKR
    if os.path.exists(IBKR_FILE):
        print(f"  Loading cached IBKR data: {IBKR_FILE}")
        df_ibkr = pd.read_parquet(IBKR_FILE)
        df_ibkr['timestamp'] = pd.to_datetime(df_ibkr['timestamp'], utc=True)
    else:
        df_ibkr = await fetch_ibkr_ticks()
        if not df_ibkr.empty:
            df_ibkr.to_parquet(IBKR_FILE, index=False)
            print(f"  Saved -> {IBKR_FILE}")

    return df_alpaca, df_ibkr


# ── Comparison ────────────────────────────────────────────────────────────────
def sep(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print('='*70)


def compare(df_alpaca_raw, df_ibkr):
    # Filter out FINRA DF (exchange D) from Alpaca
    finra_count = len(df_alpaca_raw[df_alpaca_raw['exchange'] == 'D'])
    df_alpaca = df_alpaca_raw[df_alpaca_raw['exchange'] != 'D'].copy()

    # ── 1. Overview ───────────────────────────────────────────────────────
    sep("1. OVERVIEW")
    print(f"  Date          : {_yesterday} (yesterday)")
    print(f"  Window        : {START_NY.strftime('%H:%M')} - {END_NY.strftime('%H:%M')} ET")
    print(f"  Ticker        : {TICKER}")
    print(f"")
    print(f"  {'':20s} {'Alpaca':>12s} {'IBKR':>12s} {'Diff':>12s}")
    print(f"  {'-'*56}")
    print(f"  {'Total Trades':20s} {len(df_alpaca):>12,d} {len(df_ibkr):>12,d} {len(df_alpaca)-len(df_ibkr):>+12,d}")
    print(f"  {'Total Volume':20s} {df_alpaca['size'].sum():>12,d} {df_ibkr['size'].sum():>12,d} {df_alpaca['size'].sum()-df_ibkr['size'].sum():>+12,d}")
    vwap_a = np.average(df_alpaca['price'], weights=df_alpaca['size']) if len(df_alpaca) else 0
    vwap_i = np.average(df_ibkr['price'], weights=df_ibkr['size']) if len(df_ibkr) else 0
    print(f"  {'VWAP':20s} {vwap_a:>12.4f} {vwap_i:>12.4f} {vwap_a-vwap_i:>+12.6f}")
    print(f"  {'Min Price':20s} {df_alpaca['price'].min():>12.4f} {df_ibkr['price'].min():>12.4f}")
    print(f"  {'Max Price':20s} {df_alpaca['price'].max():>12.4f} {df_ibkr['price'].max():>12.4f}")
    print(f"  {'FINRA DF skipped':20s} {finra_count:>12,d} {'N/A':>12s}")

    # ── 2. Timestamp Precision ────────────────────────────────────────────
    sep("2. TIMESTAMP PRECISION")

    # Alpaca: check nanosecond precision
    alpaca_ns = df_alpaca['timestamp'].astype(np.int64)
    alpaca_sub_sec = alpaca_ns % 10**9  # nanoseconds within the second
    alpaca_sub_ms  = alpaca_ns % 10**6  # nanoseconds within the millisecond
    alpaca_sub_us  = alpaca_ns % 10**3  # nanoseconds within the microsecond

    has_ns = (alpaca_sub_us != 0).any()
    has_us = (alpaca_sub_ms != 0).any()
    has_ms = (alpaca_sub_sec != 0).any()

    print(f"  Alpaca:")
    print(f"    Has sub-second data   : {has_ms}")
    print(f"    Has sub-millisecond   : {has_us}")
    print(f"    Has nanosecond detail : {has_ns}")
    print(f"    Sample timestamps:")
    for ts in df_alpaca['timestamp'].head(5):
        print(f"      {ts.strftime('%H:%M:%S')}.{ts.nanosecond:09d}")

    ibkr_ns = df_ibkr['timestamp'].astype(np.int64)
    ibkr_sub_sec = ibkr_ns % 10**9
    ibkr_sub_ms  = ibkr_ns % 10**6
    ibkr_sub_us  = ibkr_ns % 10**3

    print(f"  IBKR:")
    print(f"    Has sub-second data   : {(ibkr_sub_sec != 0).any()}")
    print(f"    Has sub-millisecond   : {(ibkr_sub_ms != 0).any()}")
    print(f"    Has nanosecond detail : {(ibkr_sub_us != 0).any()}")
    print(f"    Sample timestamps:")
    for ts in df_ibkr['timestamp'].head(5):
        print(f"      {ts.strftime('%H:%M:%S')}.{ts.nanosecond:09d}")

    # ── 3. Exchange Coverage ──────────────────────────────────────────────
    sep("3. EXCHANGE COVERAGE")

    alpaca_exch = df_alpaca.groupby('exchange').agg(
        trades=('size', 'count'), volume=('size', 'sum'),
        avg_size=('size', 'mean')
    ).sort_values('trades', ascending=False)
    alpaca_exch['name'] = alpaca_exch.index.map(lambda x: ALPACA_EXCHANGE_MAP.get(x, x))
    alpaca_exch['pct_trades'] = (alpaca_exch['trades'] / alpaca_exch['trades'].sum() * 100)

    ibkr_exch = df_ibkr.groupby('exchange').agg(
        trades=('size', 'count'), volume=('size', 'sum'),
        avg_size=('size', 'mean')
    ).sort_values('trades', ascending=False)
    ibkr_exch['name'] = ibkr_exch.index.map(lambda x: IBKR_EXCHANGE_MAP.get(x, x))
    ibkr_exch['pct_trades'] = (ibkr_exch['trades'] / ibkr_exch['trades'].sum() * 100)

    print(f"\n  Alpaca exchanges ({len(alpaca_exch)}):")
    print(f"  {'Code':>6s} {'Name':>12s} {'Trades':>10s} {'%':>7s} {'Volume':>12s} {'AvgSize':>8s}")
    for idx, row in alpaca_exch.iterrows():
        print(f"  {idx:>6s} {row['name']:>12s} {row['trades']:>10,.0f} {row['pct_trades']:>6.1f}% {row['volume']:>12,.0f} {row['avg_size']:>8.1f}")

    print(f"\n  IBKR exchanges ({len(ibkr_exch)}):")
    print(f"  {'Code':>6s} {'Name':>12s} {'Trades':>10s} {'%':>7s} {'Volume':>12s} {'AvgSize':>8s}")
    for idx, row in ibkr_exch.iterrows():
        print(f"  {idx:>6s} {row['name']:>12s} {row['trades']:>10,.0f} {row['pct_trades']:>6.1f}% {row['volume']:>12,.0f} {row['avg_size']:>8.1f}")

    # Find exchanges in one but not the other (by unified name)
    alpaca_names = set(alpaca_exch['name'].values)
    ibkr_names = set(ibkr_exch['name'].values)
    only_alpaca = alpaca_names - ibkr_names
    only_ibkr = ibkr_names - alpaca_names

    print(f"\n  Exchanges only in Alpaca : {only_alpaca if only_alpaca else 'None'}")
    print(f"  Exchanges only in IBKR   : {only_ibkr if only_ibkr else 'None'}")

    # ── 4. Per-Minute Distribution ────────────────────────────────────────
    sep("4. PER-MINUTE TRADE & VOLUME DISTRIBUTION")

    df_alpaca['minute'] = df_alpaca['timestamp'].dt.floor('min')
    df_ibkr['minute'] = df_ibkr['timestamp'].dt.floor('min')

    alpaca_min = df_alpaca.groupby('minute').agg(trades=('size', 'count'), volume=('size', 'sum'))
    ibkr_min = df_ibkr.groupby('minute').agg(trades=('size', 'count'), volume=('size', 'sum'))

    merged = alpaca_min.join(ibkr_min, lsuffix='_alp', rsuffix='_ibkr', how='outer').fillna(0)
    merged['trade_diff'] = merged['trades_alp'] - merged['trades_ibkr']
    merged['vol_diff'] = merged['volume_alp'] - merged['volume_ibkr']

    print(f"  {'Minute':>20s} {'A.Trades':>10s} {'I.Trades':>10s} {'Δ Trades':>10s} {'A.Vol':>10s} {'I.Vol':>10s} {'Δ Vol':>10s}")
    for idx, row in merged.iterrows():
        ts = idx.strftime('%H:%M') if hasattr(idx, 'strftime') else str(idx)
        print(f"  {ts:>20s} {row['trades_alp']:>10,.0f} {row['trades_ibkr']:>10,.0f} {row['trade_diff']:>+10,.0f} {row['volume_alp']:>10,.0f} {row['volume_ibkr']:>10,.0f} {row['vol_diff']:>+10,.0f}")

    # ── 5. Trade Size Distribution ────────────────────────────────────────
    sep("5. TRADE SIZE DISTRIBUTION")

    bins = [0, 1, 10, 50, 100, 500, 1000, float('inf')]
    labels = ['1', '2-10', '11-50', '51-100', '101-500', '501-1000', '1000+']

    alpaca_sizes = pd.cut(df_alpaca['size'], bins=bins, labels=labels).value_counts().sort_index()
    ibkr_sizes = pd.cut(df_ibkr['size'], bins=bins, labels=labels).value_counts().sort_index()

    print(f"  {'Size Bucket':>12s} {'Alpaca':>10s} {'IBKR':>10s} {'Diff':>10s}")
    for lbl in labels:
        a = alpaca_sizes.get(lbl, 0)
        i = ibkr_sizes.get(lbl, 0)
        print(f"  {lbl:>12s} {a:>10,d} {i:>10,d} {a-i:>+10,d}")

    # ── 6. Duplicate Timestamps ───────────────────────────────────────────
    sep("6. DUPLICATE TIMESTAMP ANALYSIS")

    alpaca_dup = df_alpaca.groupby('timestamp').size()
    ibkr_dup = df_ibkr.groupby('timestamp').size()

    print(f"  Alpaca:")
    print(f"    Unique timestamps     : {len(alpaca_dup):,}")
    print(f"    Max trades/timestamp  : {alpaca_dup.max()}")
    print(f"    Timestamps with >1    : {(alpaca_dup > 1).sum():,}")

    print(f"  IBKR:")
    print(f"    Unique timestamps     : {len(ibkr_dup):,}")
    print(f"    Max trades/timestamp  : {ibkr_dup.max()}")
    print(f"    Timestamps with >1    : {(ibkr_dup > 1).sum():,}")

    # ── 7. Inter-Trade Time Gaps ──────────────────────────────────────────
    sep("7. INTER-TRADE TIME GAPS")

    for name, df in [('Alpaca', df_alpaca), ('IBKR', df_ibkr)]:
        gaps = df['timestamp'].diff().dropna()
        gaps_ms = gaps.dt.total_seconds() * 1000
        print(f"  {name}:")
        print(f"    Min gap     : {gaps_ms.min():.3f} ms")
        print(f"    Median gap  : {gaps_ms.median():.3f} ms")
        print(f"    Mean gap    : {gaps_ms.mean():.3f} ms")
        print(f"    Max gap     : {gaps_ms.max():.3f} ms  ({gaps_ms.max()/1000:.1f}s)")
        print(f"    Gaps > 1s   : {(gaps_ms > 1000).sum():,}")
        print(f"    Gaps > 5s   : {(gaps_ms > 5000).sum():,}")

    # ── 8. 10-Second Bar Comparison ───────────────────────────────────────
    sep("8. 10-SECOND BAR RECONSTRUCTION COMPARISON")

    # Build 10s bars from both tick feeds
    df_a = df_alpaca.set_index('timestamp').sort_index()
    df_i = df_ibkr.set_index('timestamp').sort_index()

    bars_a = df_a.resample('10s').agg(
        open=('price', 'first'), high=('price', 'max'),
        low=('price', 'min'), close=('price', 'last'),
        volume=('size', 'sum'), trades=('size', 'count')
    ).dropna(subset=['open'])

    bars_i = df_i.resample('10s').agg(
        open=('price', 'first'), high=('price', 'max'),
        low=('price', 'min'), close=('price', 'last'),
        volume=('size', 'sum'), trades=('size', 'count')
    ).dropna(subset=['open'])

    common = bars_a.index.intersection(bars_i.index)
    only_a = bars_a.index.difference(bars_i.index)
    only_i = bars_i.index.difference(bars_a.index)

    print(f"  10s bars from Alpaca : {len(bars_a)}")
    print(f"  10s bars from IBKR   : {len(bars_i)}")
    print(f"  Common timestamps    : {len(common)}")
    print(f"  Only in Alpaca       : {len(only_a)}")
    print(f"  Only in IBKR         : {len(only_i)}")

    if len(common) > 0:
        close_diff = (bars_a.loc[common, 'close'] - bars_i.loc[common, 'close']).abs()
        vol_diff = (bars_a.loc[common, 'volume'] - bars_i.loc[common, 'volume']).abs()
        trade_diff = (bars_a.loc[common, 'trades'] - bars_i.loc[common, 'trades']).abs()

        print(f"\n  On common 10s bars:")
        print(f"    Close price - exact matches : {(close_diff == 0).sum()}/{len(common)} ({(close_diff==0).sum()/len(common)*100:.1f}%)")
        print(f"    Close price - max diff      : ${close_diff.max():.4f}")
        print(f"    Close price - mean diff     : ${close_diff.mean():.6f}")
        print(f"    Volume      - exact matches : {(vol_diff == 0).sum()}/{len(common)} ({(vol_diff==0).sum()/len(common)*100:.1f}%)")
        print(f"    Volume      - max diff      : {vol_diff.max():.0f}")
        print(f"    Trade count - exact matches : {(trade_diff == 0).sum()}/{len(common)} ({(trade_diff==0).sum()/len(common)*100:.1f}%)")
        print(f"    Trade count - max diff      : {trade_diff.max():.0f}")

        # Show worst mismatches
        worst = vol_diff.nlargest(5)
        if worst.max() > 0:
            print(f"\n  Top 5 worst volume mismatches (10s bars):")
            for ts in worst.index:
                t_str = ts.strftime('%H:%M:%S')
                print(f"    {t_str}  Alpaca: vol={bars_a.loc[ts,'volume']:,.0f} trades={bars_a.loc[ts,'trades']:.0f}  |  IBKR: vol={bars_i.loc[ts,'volume']:,.0f} trades={bars_i.loc[ts,'trades']:.0f}")

    # ── 9. Conditions / Special Codes ─────────────────────────────────────
    sep("9. TRADE CONDITIONS")

    alpaca_conds = df_alpaca[df_alpaca['conditions'] != '']['conditions'].value_counts().head(15)
    ibkr_conds = df_ibkr[df_ibkr['conditions'] != '']['conditions'].value_counts().head(15)

    print(f"  Alpaca top conditions:")
    if len(alpaca_conds):
        for c, n in alpaca_conds.items():
            print(f"    {c:30s} : {n:,}")
    else:
        print(f"    (none)")

    print(f"  IBKR top conditions:")
    if len(ibkr_conds):
        for c, n in ibkr_conds.items():
            print(f"    {c:30s} : {n:,}")
    else:
        print(f"    (none)")

    # ── 10. First/Last Trade Comparison ───────────────────────────────────
    sep("10. FIRST & LAST TRADES")

    for label, df in [('Alpaca', df_alpaca), ('IBKR', df_ibkr)]:
        first = df.iloc[0]
        last = df.iloc[-1]
        print(f"  {label}:")
        print(f"    First: {first['timestamp'].strftime('%H:%M:%S.%f')}  ${first['price']:.2f}  x{first['size']}  exch={first['exchange']}")
        print(f"    Last : {last['timestamp'].strftime('%H:%M:%S.%f')}  ${last['price']:.2f}  x{last['size']}  exch={last['exchange']}")

    # Cleanup temp columns
    df_alpaca.drop(columns=['minute'], inplace=True, errors='ignore')
    df_ibkr.drop(columns=['minute'], inplace=True, errors='ignore')


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print(f"{'='*70}")
    print(f"  TICK DATA COMPARISON: IBKR vs ALPACA")
    print(f"  {TICKER} | {_yesterday} | {START_NY.strftime('%H:%M')}-{END_NY.strftime('%H:%M')} ET")
    print(f"{'='*70}")

    print(f"\n--- Loading Data ---")
    df_alpaca, df_ibkr = await load_data()

    if df_alpaca.empty:
        print("ERROR: No Alpaca data. Exiting.")
        return
    if df_ibkr.empty:
        print("ERROR: No IBKR data. Exiting.")
        return

    print(f"\n  Alpaca raw: {len(df_alpaca):,} trades")
    print(f"  IBKR raw  : {len(df_ibkr):,} trades")

    compare(df_alpaca, df_ibkr)

    print(f"\n{'='*70}")
    print(f"  DONE")
    print(f"{'='*70}")


if __name__ == '__main__':
    asyncio.run(main())
