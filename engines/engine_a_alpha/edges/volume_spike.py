def edge(df, lookback=20, mult=1.5):
    if len(df) < lookback + 1:
        return 0
    v = df["Volume"]
    avg = v.rolling(lookback).mean().iloc[-1]
    if avg == 0: 
        return 0
    spike = v.iloc[-1] > mult * avg
    up = df["Close"].iloc[-1] > df["Open"].iloc[-1]
    dn = df["Close"].iloc[-1] < df["Open"].iloc[-1]
    if spike and up: return 1
    if spike and dn: return -1
    return 0