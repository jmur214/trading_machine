
import os
# Force debug BEFORE imports
os.environ["DATA_MANAGER_DEBUG"] = "1"
from engines.data_manager.data_manager import DataManager

def test_dm_fallback():
    print("Testing DataManager fallback for NVDA...")
    dm = DataManager()
    data = dm.ensure_data(["NVDA"], start="2024-01-01", end="2024-02-01")
    
    if "NVDA" in data and not data["NVDA"].empty:
        print(f"Success! NVDA rows: {len(data['NVDA'])}")
        print(data["NVDA"].head())
    else:
        print("Failure. NVDA not found or empty.")

if __name__ == "__main__":
    test_dm_fallback()
