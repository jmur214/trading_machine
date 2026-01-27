
import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus

# Load env
load_dotenv()

def fetch_universe():
    api_key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    
    if not api_key or not secret_key:
        print("Missing API Keys.")
        return

    print("Connecting to Alpaca Trading Client...")
    # using paper=True for safety, though Assets are global usually
    trading_client = TradingClient(api_key, secret_key, paper=True)

    search_params = GetAssetsRequest(
        asset_class=AssetClass.US_EQUITY,
        status=AssetStatus.ACTIVE
    )

    print("Fetching active US Equities...")
    assets = trading_client.get_all_assets(search_params)
    
    tradable = [a for a in assets if a.tradable]
    print(f"Total Assets Found: {len(assets)}")
    print(f"Total Tradable: {len(tradable)}")
    
    if len(tradable) > 0:
        print("Sample tickers:", [a.symbol for a in tradable[:10]])
        # Check specifically for NVDA
        nvda = next((a for a in tradable if a.symbol == "NVDA"), None)
        if nvda:
            print(f"Found NVDA: {nvda}")
            
if __name__ == "__main__":
    fetch_universe()
