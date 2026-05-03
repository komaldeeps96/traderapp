import yaml
import sys
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockTradesRequest
from alpaca.data.timeframe import TimeFrame

def main():
    try:
        with open('config/config.yaml', 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print("Please create config/config.yaml with your Alpaca keys.")
        return

    api_key = config.get('alpaca', {}).get('api_key')
    secret_key = config.get('alpaca', {}).get('secret_key')

    if not api_key or api_key == "YOUR_API_KEY_HERE":
        print("Please set your Alpaca API key in config/config.yaml")
        return

    # Initialize client
    client = StockHistoricalDataClient(api_key, secret_key)
    
    symbol = "SPY"
    # Get a date older than 1 day (e.g., 5 days ago)
    end_date = datetime.now() - timedelta(days=2)
    start_date = end_date - timedelta(days=1)

    print(f"Testing Alpaca Historical Data for {symbol}")
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    
    # Test 1: IEX Feed
    print("\n--- Testing IEX Feed ---")
    try:
        request_params = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start_date,
            end=end_date,
            feed="iex"
        )
        bars = client.get_stock_bars(request_params)
        print(f"Success! IEX feed returned {len(bars.data.get(symbol, []))} bars.")
    except Exception as e:
        print(f"IEX Feed failed: {e}")

    # Test 2: SIP Feed
    print("\n--- Testing SIP Feed ---")
    try:
        request_params = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start_date,
            end=end_date,
            feed="sip"
        )
        bars = client.get_stock_bars(request_params)
        print(f"Success! SIP feed returned {len(bars.data.get(symbol, []))} bars.")
    except Exception as e:
        print(f"SIP Feed failed: {e}")

if __name__ == "__main__":
    main()
