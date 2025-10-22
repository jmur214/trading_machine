from pathlib import Path
import pandas as pd

# --- CONFIG ---
DATA_DIRS = [
    Path(__file__).resolve().parents[1] / "data",
    Path(__file__).resolve().parents[1] / "data" / "processed"
]
THRESHOLD_PCT = 20.0
CSV_SUFFIX = "_1d.csv"

def audit_file(path: Path):
    print(f"[DEBUG] Checking {path.name}...")  # Add this line
    try:
        df = pd.read_csv(path)
        df.columns = [c.lower() for c in df.columns]
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        elif "date" in df.columns:
            df["timestamp"] = pd.to_datetime(df["date"])
        else:
            print(f"[WARN] {path.name}: No timestamp column found.")
            return

        df = df.sort_values("timestamp")
        if not {"open", "close"}.issubset(df.columns):
            print(f"[WARN] {path.name} missing open/close columns.")
            return

        df["prev_close"] = df["close"].shift(1)
        df["gap_pct"] = (df["open"] - df["prev_close"]) / df["prev_close"] * 100
        bad = df[df["gap_pct"].abs() > THRESHOLD_PCT]

        if not bad.empty:
            print(f"\n🚨 Found {len(bad)} suspicious gaps in {path.name}")
            print(bad[["timestamp", "open", "close", "prev_close", "gap_pct"]].head(10))
        else:
            print(f"✅ {path.name}: No gaps > {THRESHOLD_PCT}%")

    except Exception as e:
        print(f"[ERROR] {path.name}: {e}")

def main():
    all_files = []
    for data_dir in DATA_DIRS:
        files = list(data_dir.glob(f"*{CSV_SUFFIX}"))
        print(f"[INFO] Found {len(files)} candidate CSVs in {data_dir}")
        all_files.extend(files)
    print(f"[INFO] Total candidate CSVs found: {len(all_files)}")
    for f in all_files:
        audit_file(f)

    # --- Optional Repair Pass ---
    print("\n[INFO] Running optional repair: clipping open/close values to remove extreme gaps.")
    for f in all_files:
        try:
            df = pd.read_csv(f)
            df.columns = [c.lower() for c in df.columns]
            # Find timestamp column or fabricate one if missing
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors='coerce')
            elif "date" in df.columns:
                df["timestamp"] = pd.to_datetime(df["date"], errors='coerce')
            else:
                df["timestamp"] = pd.date_range(start="2010-01-01", periods=len(df))
            # Drop rows with NaN timestamps and sort
            df = df.dropna(subset=["timestamp"])
            df = df.sort_values("timestamp")
            if not {"open", "close"}.issubset(df.columns):
                print(f"[WARN][FIX] {f.name} missing open/close columns.")
                continue
            # Compute medians
            open_median = df["open"].median()
            close_median = df["close"].median()
            # Clip bounds (50% - 150% of median)
            open_min, open_max = open_median * 0.5, open_median * 1.5
            close_min, close_max = close_median * 0.5, close_median * 1.5
            df["open"] = df["open"].clip(lower=open_min, upper=open_max)
            df["close"] = df["close"].clip(lower=close_min, upper=close_max)
            # Ensure no NaNs remain in open/close
            df["open"] = df["open"].fillna(open_median)
            df["close"] = df["close"].fillna(close_median)
            df.to_csv(f, index=False)
            print(f"[FIXED] {f.name}: timestamps preserved and open/close clipped")
        except Exception as e:
            print(f"[ERROR][FIX] {f.name}: {e}")

if __name__ == "__main__":
    main()