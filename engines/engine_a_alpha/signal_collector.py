import traceback
import numbers


class SignalCollector:
    """
    Collects raw edge signals for each ticker.

    Expected edge interface:
        generate(df: pd.DataFrame) -> {"signal": float, "weight": float}

    Returns:
        dict[ticker -> list[{"signal": float, "weight": float, "edge": str}]]
    """

    def __init__(self, edges: dict, edge_weights: dict | None = None, debug: bool = True):
        self.edges = edges or {}
        self.edge_weights = edge_weights or {}
        self.debug = debug

    # ---------------- Internal Helpers ----------------
    def _coerce_number(self, x, default=0.0) -> float:
        """Try to convert to float safely."""
        try:
            if isinstance(x, numbers.Number):
                return float(x)
            return float(str(x).strip())
        except Exception:
            return float(default)

    # ---------------- Main Collector ----------------
    def collect(self, market_slice: dict, timestamp=None) -> dict:
        out = {t: [] for t in market_slice.keys()}
        if not self.edges:
            if self.debug:
                print("[ALPHA][COLLECTOR] No active edges configured.")
            return out

        for ticker, df in market_slice.items():
            if df is None or df.empty:
                if self.debug:
                    print(f"[ALPHA][COLLECTOR][{ticker}] Empty data frame — skipping.")
                continue

            for edge_name, edge_mod in self.edges.items():
                try:
                    payload = edge_mod.generate(df)
                    if not isinstance(payload, dict):
                        if self.debug:
                            print(f"[ALPHA][WARN][{edge_name}] Returned non-dict payload for {ticker}")
                        continue

                    # Coerce values
                    s = self._coerce_number(payload.get("signal", 0.0), 0.0)
                    w_cfg = self.edge_weights.get(edge_name)
                    w_mod = payload.get("weight")
                    w = self._coerce_number(w_cfg if w_cfg is not None else w_mod, 1.0)

                    # Skip invalid or zero signals
                    if not isinstance(s, (int, float)) or abs(s) <= 1e-9:
                        continue

                    out[ticker].append({
                        "signal": s,
                        "weight": w,
                        "edge": edge_name,
                    })

                except Exception as e:
                    if self.debug:
                        msg = "".join(traceback.format_exception_only(type(e), e)).strip()
                        print(f"[ALPHA][ERROR][{edge_name}] {ticker}: {msg}")
                    continue

        if self.debug:
            summary = {t: len(v) for t, v in out.items()}
            print(f"[ALPHA][COLLECTOR] Summary: {summary}")

        return out