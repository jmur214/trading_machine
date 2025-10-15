import pandas as pd

def basic_summary(trade_log_path: str):
    try:
        df = pd.read_csv(trade_log_path)
    except Exception:
        return {"trades": 0, "pnl_sum": 0}
    return {
        "trades": len(df),
        "first_ts": df["timestamp"].min() if len(df) else None,
        "last_ts": df["timestamp"].max() if len(df) else None
    }