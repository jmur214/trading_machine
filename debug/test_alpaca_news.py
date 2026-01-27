
import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Try importing alpaca library
try:
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
    from alpaca.common.enums import Sort
except ImportError:
    print("❌ alpaca-py not installed or incorrect module path.")
    sys.exit(1)

def main():
    load_dotenv()
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    
    if not api_key:
        print("❌ ALPACA_API_KEY not found in env.")
        return

    print(f"Connecting to Alpaca News API...")
    client = NewsClient(api_key=api_key, secret_key=secret_key)

    # Try to fetch news from early 2024 to verify history
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 7)
    symbol = "TSLA"

    print(f"Fetching news for {symbol} from {start_date.date()} to {end_date.date()}...")

    req = NewsRequest(
        symbols=symbol,
        start=start_date,
        end=end_date,
        limit=5,
        sort=Sort.ASC
    )

    try:
        news = client.get_news(req)
        print(f"✅ Success! Response Type: {type(news)}")
        
        # 'data' logic
        if hasattr(news, 'data'):
            items = news.data.get('news', []) if isinstance(news.data, dict) else news.data
        else:
            items = []

        print(f"Retrieved {len(items)} articles.")
        for item in items[:3]:
            # Inspect item structure
            created = getattr(item, 'created_at', 'N/A')
            headline = getattr(item, 'headline', 'N/A')
            source = getattr(item, 'source', 'N/A')
            print(f"   - [{created}] {headline} (Source: {source})")
            
        print("\n[VERDICT] Historical News Data is AVAILABLE.")
        
    except Exception as e:
        print(f"❌ Failed to fetch news: {e}")
        print("\n[VERDICT] Historical News Data is UNAVAILABLE or requires different plan.")

if __name__ == "__main__":
    main()
