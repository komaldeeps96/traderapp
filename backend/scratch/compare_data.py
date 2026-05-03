import asyncio
import yaml
import pandas as pd
from datetime import datetime, timezone
import pytz
from ib_async import IB, Stock
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockTradesRequest

async def main():
    ticker = 'AAPL'
    
    # Timezone aware start and end for today 9:00 AM to 10:00 AM NY Time
    ny_tz = pytz.timezone('America/New_York')
    today = datetime.now(ny_tz).date()
    
    start_dt_ny = ny_tz.localize(datetime.combine(today, datetime.strptime("09:00:00", "%H:%M:%S").time()))
    end_dt_ny = ny_tz.localize(datetime.combine(today, datetime.strptime("10:00:00", "%H:%M:%S").time()))
    
    # Convert to UTC
    start_dt_utc = start_dt_ny.astimezone(timezone.utc)
    end_dt_utc = end_dt_ny.astimezone(timezone.utc)
    
    print(f"Fetching data from {start_dt_ny} to {end_dt_ny} (NY Time)")
    print(f"UTC: {start_dt_utc} to {end_dt_utc}")
    
    # ------------------
    # 1. Fetch Alpaca
    # ------------------
    print("\n--- Fetching Alpaca ---")
    try:
        with open("config/config.yaml", 'r') as f:
            config = yaml.safe_load(f)
        api_key = config['alpaca']['api_key']
        secret_key = config['alpaca']['secret_key']
        alpaca_client = StockHistoricalDataClient(api_key, secret_key)
        
        req = StockTradesRequest(
            symbol_or_symbols=ticker,
            start=start_dt_utc,
            end=end_dt_utc,
            feed="sip"
        )
        
        loop = asyncio.get_event_loop()
        trades = await loop.run_in_executor(None, alpaca_client.get_stock_trades, req)
        
        df_alpaca = pd.DataFrame()
        if trades and trades.data and ticker in trades.data:
            trades_data = trades.data[ticker]
            df = pd.DataFrame([{
                'time': t.timestamp,
                'price': t.price,
                'size': t.size,
                'exchange': t.exchange
            } for t in trades_data])
            
            if not df.empty:
                df = df[df['exchange'] != 'D'] # Filter FINRA ADF
                
                df.set_index('time', inplace=True)
                df.index = pd.to_datetime(df.index, utc=True)
                
                df_alpaca = df.resample('10s').agg({
                    'price': 'ohlc',
                    'size': 'sum'
                })
                df_alpaca.columns = df_alpaca.columns.droplevel()
                df_alpaca.rename(columns={'size': 'volume'}, inplace=True)
                df_alpaca['trades'] = df['size'].resample('10s').count()
                df_alpaca = df_alpaca.dropna(subset=['open'])
        
        print(f"Alpaca 10s bars: {len(df_alpaca)}")
        if not df_alpaca.empty:
            print("Alpaca Sample (first 2):")
            print(df_alpaca.head(2))
    except Exception as e:
        print(f"Alpaca fetch failed: {e}")
        df_alpaca = pd.DataFrame()

    # ------------------
    # 2. Fetch IBKR
    # ------------------
    print("\n--- Fetching IBKR ---")
    ib = IB()
    df_ibkr = pd.DataFrame()
    try:
        await ib.connectAsync('127.0.0.1', 7496, clientId=99, readonly=True)
        contract = Stock(ticker, 'SMART', 'USD')
        await ib.qualifyContractsAsync(contract)
        
        # IBKR uses formatting YYYYMMDD HH:mm:ss for endDateTime (in local timezone of connection or 'UTC' if specified)
        end_str = end_dt_utc.strftime("%Y%md %H:%M:%S") # wait, better to use the exact time
        end_str = end_dt_utc.strftime("%Y%m%d %H:%M:%S UTC")
        
        # We need duration string. 9am to 10am is 1 hour = 3600 S
        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime=end_str,
            durationStr='3600 S',
            barSizeSetting='10 secs',
            whatToShow='TRADES',
            useRTH=False,
            formatDate=2
        )
        
        if bars:
            df_ibkr = pd.DataFrame([{
                'time': b.date,
                'open': b.open,
                'high': b.high,
                'low': b.low,
                'close': b.close,
                'volume': float(b.volume),
                'trades': b.barCount
            } for b in bars])
            
            df_ibkr.set_index('time', inplace=True)
            df_ibkr.index = pd.to_datetime(df_ibkr.index, utc=True)
        
        print(f"IBKR 10s bars: {len(df_ibkr)}")
        if not df_ibkr.empty:
            print("IBKR Sample (first 2):")
            print(df_ibkr.head(2))
            
    except Exception as e:
        print(f"IBKR fetch failed: {e}")
    finally:
        ib.disconnect()

    # ------------------
    # 3. Compare
    # ------------------
    print("\n--- Comparison ---")
    if not df_alpaca.empty and not df_ibkr.empty:
        # Align indexes
        common_idx = df_alpaca.index.intersection(df_ibkr.index)
        print(f"Common timestamps: {len(common_idx)}")
        
        if len(common_idx) > 0:
            diff_close = (df_alpaca.loc[common_idx, 'close'] - df_ibkr.loc[common_idx, 'close']).abs()
            diff_vol = (df_alpaca.loc[common_idx, 'volume'] - df_ibkr.loc[common_idx, 'volume']).abs()
            
            print(f"Max close price diff: {diff_close.max():.4f}")
            print(f"Mean close price diff: {diff_close.mean():.4f}")
            print(f"Max volume diff: {diff_vol.max():.2f}")
            
            print("\nComparing a specific bar (First common):")
            idx = common_idx[0]
            print(f"Time: {idx}")
            print(f"Alpaca -> Open: {df_alpaca.loc[idx, 'open']}, High: {df_alpaca.loc[idx, 'high']}, Low: {df_alpaca.loc[idx, 'low']}, Close: {df_alpaca.loc[idx, 'close']}, Vol: {df_alpaca.loc[idx, 'volume']}")
            print(f"IBKR   -> Open: {df_ibkr.loc[idx, 'open']}, High: {df_ibkr.loc[idx, 'high']}, Low: {df_ibkr.loc[idx, 'low']}, Close: {df_ibkr.loc[idx, 'close']}, Vol: {df_ibkr.loc[idx, 'volume']}")
    else:
        print("Missing data from one of the providers. Cannot compare.")

if __name__ == "__main__":
    asyncio.run(main())
