import asyncio
import yaml
import pandas as pd
from datetime import datetime, timezone
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockTradesRequest

async def main():
    ticker = 'AAPL'
    ny_tz = pytz.timezone('America/New_York')
    today = datetime.now(ny_tz).date()
    
    start_dt_ny = ny_tz.localize(datetime.combine(today, datetime.strptime("09:00:00", "%H:%M:%S").time()))
    end_dt_ny = ny_tz.localize(datetime.combine(today, datetime.strptime("09:05:00", "%H:%M:%S").time()))
    
    start_dt_utc = start_dt_ny.astimezone(timezone.utc)
    end_dt_utc = end_dt_ny.astimezone(timezone.utc)
    
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
    
    trades = alpaca_client.get_stock_trades(req)
    
    if trades and trades.data and ticker in trades.data:
        trades_data = trades.data[ticker]
        df = pd.DataFrame([{
            'time': t.timestamp,
            'price': t.price,
            'size': t.size,
            'exchange': t.exchange,
            'conditions': tuple(t.conditions) if t.conditions else ()
        } for t in trades_data])
        
        print("Total trades:", len(df))
        print("Exchanges present:", df['exchange'].unique())
        print("Conditions present:", df['conditions'].unique()[:10])
        
        # Filter FINRA ADF (often D)
        df_filtered = df[df['exchange'] != 'D']
        print("Total trades without ADF (D):", len(df_filtered))

if __name__ == "__main__":
    asyncio.run(main())
