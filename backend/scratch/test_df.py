import asyncio
import yaml
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
    
    with open("config/config.yaml", 'r') as f:
        config = yaml.safe_load(f)
    api_key = config['alpaca']['api_key']
    secret_key = config['alpaca']['secret_key']
    alpaca_client = StockHistoricalDataClient(api_key, secret_key)
    
    req = StockTradesRequest(
        symbol_or_symbols=ticker,
        start=start_dt_ny.astimezone(timezone.utc),
        end=end_dt_ny.astimezone(timezone.utc),
        feed="sip"
    )
    
    trades = alpaca_client.get_stock_trades(req)
    
    print("Using .df:")
    df = trades.df
    print(df.head())
    print("Columns:", df.columns)
    print("Index:", df.index.names)

if __name__ == "__main__":
    asyncio.run(main())
