from pathlib import Path
import csv

class CockpitLogger:
    def __init__(self, out_dir: str = "data/trade_logs/"):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.trades_path = self.out_dir / "trades.csv"
        self.snaps_path = self.out_dir / "portfolio_snapshots.csv"
        self._init_files()
        self.trades_log = []  # in-memory list of fills

    def _init_files(self):
        if not self.trades_path.exists():
            with self.trades_path.open("w", newline="") as f:
                w = csv.writer(f)
                # Correct header order: timestamp,ticker,side,qty,fill_price,commission
                w.writerow(["timestamp", "ticker", "side", "qty", "fill_price", "commission"])

        if not self.snaps_path.exists():
            with self.snaps_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["timestamp", "cash", "equity", "n_positions"])

    def log_fill(self, fill: dict, timestamp):
        """Logs a single trade fill correctly with proper column order."""
        qty = int(fill.get("qty", 0))
        price = float(fill.get("price", fill.get("fill_price", 0)))
        if price == 0 or qty == 0:
            print(f"[LOGGER][WARN] Missing price or qty for fill: {fill}")
            return

        row = [timestamp, fill.get("ticker"), fill.get("side"), qty, price, fill.get("commission", 0.0)]
        self.trades_log.append(row)
        with self.trades_path.open("a", newline="") as f:
            csv.writer(f).writerow(row)

        print(f"[LOGGER][DEBUG] Logged fill: {fill.get('side')} {fill.get('ticker')} qty={qty} @ {price:.2f}")

    def log_snapshot(self, snap: dict):
        """Logs a portfolio snapshot (cash, equity, open positions)."""
        with self.snaps_path.open("a", newline="") as f:
            csv.writer(f).writerow([
                snap.get("timestamp"),
                round(snap.get("cash", 0), 2),
                round(snap.get("equity", 0), 2),
                snap.get("n_positions", 0)
            ])
        print(
            f"[LOGGER][DEBUG] Logged portfolio snapshot: "
            f"equity={snap.get('equity'):.2f}, positions={snap.get('n_positions')}"
        )