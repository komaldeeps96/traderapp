import yaml
from datetime import datetime, timedelta
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockTradesRequest

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

    client = StockHistoricalDataClient(api_key, secret_key)
    
    symbol = "AAPL"
    
    # We need a recent trading day. Let's use 3 days ago.
    # Convert to Eastern Time as 10:00 AM ET is what is meant.
    tz = pytz.timezone('America/New_York')
    base_date = datetime.now(tz) - timedelta(days=3)
    
    # If weekend, move to Friday
    if base_date.weekday() >= 5:
        base_date = base_date - timedelta(days=base_date.weekday() - 4)

    start_time = base_date.replace(hour=10, minute=0, second=0, microsecond=0)
    end_time = base_date.replace(hour=10, minute=1, second=0, microsecond=0)

    print(f"Testing Alpaca Historical Tick Data (Trades) for {symbol}")
    print(f"Time range (ET): {start_time} to {end_time}")
    
    try:
        request_params = StockTradesRequest(
            symbol_or_symbols=symbol,
            start=start_time,
            end=end_time,
            feed="sip"
        )
        trades = client.get_stock_trades(request_params)
        trade_list = trades.data.get(symbol, [])
        print(f"Success! SIP feed returned {len(trade_list)} trades.")
        if trade_list:
            print("First 3 trades:")
            for t in trade_list[:3]:
                print(f"  Time: {t.timestamp}, Price: {t.price}, Size: {t.size}, Exchange: {t.exchange}")
    except Exception as e:
        print(f"SIP Feed failed: {e}")

    print("\n--- Testing IEX Feed ---")
    try:
        request_params = StockTradesRequest(
            symbol_or_symbols=symbol,
            start=start_time,
            end=end_time,
            feed="iex"
        )
        trades = client.get_stock_trades(request_params)
        trade_list = trades.data.get(symbol, [])
        print(f"Success! IEX feed returned {len(trade_list)} trades.")
        if trade_list:
            print("First 3 trades:")
            for t in trade_list[:3]:
                print(f"  Time: {t.timestamp}, Price: {t.price}, Size: {t.size}, Exchange: {t.exchange}")
    except Exception as e:
        print(f"IEX Feed failed: {e}")

if __name__ == "__main__":
    main()
