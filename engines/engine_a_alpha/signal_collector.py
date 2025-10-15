import traceback

class SignalCollector:
    """
    Calls each active edge module's generate() for each ticker.
    Expects each edge module to expose generate(df_slice) -> {signal: float, weight: float}
    Returns: dict[ticker -> list[{"signal": float, "weight": float, "edge": str}]]
    """

    def __init__(self, edges: dict, edge_weights: dict | None = None, debug: bool = True):
        self.edges = edges or {}
        self.edge_weights = edge_weights or {}
        self.debug = debug

    def _coerce_number(self, x, default=0.0):
        try:
            return float(x)
        except Exception:
            return float(default)

    def collect(self, market_slice: dict):
        out = {t: [] for t in market_slice.keys()}

        for ticker, df in market_slice.items():
            for edge_name, edge_mod in self.edges.items():
                try:
                    payload = edge_mod.generate(df)

                    # edge payload can override the configured weight; otherwise use config or module default
                    s = self._coerce_number(payload.get("signal", 0.0), 0.0)
                    w_cfg = self.edge_weights.get(edge_name, None)
                    w_mod = payload.get("weight", None)
                    w = self._coerce_number(w_cfg if w_cfg is not None else w_mod, 1.0)

                    if abs(s) > 0:  # keep zeros out to reduce noise
                        out[ticker].append({"signal": s, "weight": w, "edge": edge_name})
                except Exception as e:
                    if self.debug:
                        msg = "".join(traceback.format_exception_only(type(e), e)).strip()
                        print(f"[ALPHA][WARN] {edge_name} on {ticker} failed: {msg}")
                    continue

        return out