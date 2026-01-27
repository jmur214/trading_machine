
import os
from dotenv import load_dotenv, find_dotenv

def check_env():
    # 1. Try finding it
    env_file = find_dotenv()
    print(f"Propsective .env path: {env_file}")
    
    # 2. Load it
    res = load_dotenv(env_file, verbose=True, override=True)
    print(f"load_dotenv result: {res}")
    
    # 3. Check Keys
    key_id = os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_SECRET_KEY")
    base = os.getenv("ALPACA_API_BASE_URL")
    
    print(f"\nScanning for Alpaca Keys:")
    print(f"ALPACA_API_KEY Found? {'YES' if key_id else 'NO'}")
    if key_id:
        print(f"  Length: {len(key_id)}")
        print(f"  Preview: {key_id[:4]}...{key_id[-4:] if len(key_id)>8 else ''}")
        
    print(f"ALPACA_SECRET_KEY Found? {'YES' if secret else 'NO'}")
    if secret:
        print(f"  Length: {len(secret)}")
        
    print(f"ALPACA_API_BASE_URL: {base}")

    # Check for malformed keys (e.g. quotes included in value)
    if key_id and (key_id.startswith('"') or key_id.startswith("'")):
        print("WARNING: API Key seems to have quotes included in the value. This might be an error in .env format.")

if __name__ == "__main__":
    check_env()
