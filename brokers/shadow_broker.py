
import pandas as pd
import numpy as np
import os
import datetime
from pathlib import Path
from typing import Dict, Optional

class ShadowBroker:
    """
    Simulated Broker for the 'Shadow Realm'.
    
    Mimics the AlpacaBroker interface but creates no real orders.
    Tracks 'Ghost Money' and positions in local CSVs.
    """
    
    DATA_DIR = Path("data/shadow")
    
    def __init__(self, initial_capital: float = 100000.0):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.initial_capital = initial_capital
        
        self.positions_file = self.DATA_DIR / "positions.csv"
        self.trades_file = self.DATA_DIR / "trades.csv"
        self.account_file = self.DATA_DIR / "account.csv"
        
        # Load or Initialize State
        self.cash = initial_capital
        self.positions: Dict[str, float] = {} # Symbol -> Qty
        self.avg_costs: Dict[str, float] = {} # Symbol -> AvgPrice
        self.last_equity = initial_capital
        
        self._load_state()

    def _load_state(self):
        # 1. Account Info (Cash)
        if self.account_file.exists():
            try:
                df = pd.read_csv(self.account_file)
                if not df.empty:
                    last_row = df.iloc[-1]
                    self.cash = float(last_row["cash"])
                    self.last_equity = float(last_row["equity"])
            except Exception as e:
                print(f"[SHADOW] Error loading account file: {e}")
        
        # 2. Positions
        if self.positions_file.exists():
            try:
                df = pd.read_csv(self.positions_file)
                for _, row in df.iterrows():
                    sym = row["symbol"]
                    qty = float(row["qty"])
                    if qty != 0:
                        self.positions[sym] = qty
                        self.avg_costs[sym] = float(row.get("avg_price", 0.0))
            except Exception as e:
                print(f"[SHADOW] Error loading positions: {e}")

    def _save_state(self):
        # Save Positions
        pos_data = []
        for sym, qty in self.positions.items():
            if qty != 0:
                pos_data.append({
                    "symbol": sym, 
                    "qty": qty, 
                    "avg_price": self.avg_costs.get(sym, 0.0)
                })
        pd.DataFrame(pos_data).to_csv(self.positions_file, index=False)
        
        # Save Account Snapshot
        acct_data = [{
            "timestamp": datetime.datetime.now().isoformat(),
            "cash": self.cash,
            "equity": self.last_equity
        }]
        # Append mode ideally, but for now overwrite to keep simple state or append to history?
        # Let's append if exists, else write
        df_acct = pd.DataFrame(acct_data)
        if self.account_file.exists():
            df_acct.to_csv(self.account_file, mode='a', header=False, index=False)
        else:
            df_acct.to_csv(self.account_file, index=False)

    def _log_trade(self, trade_record: dict):
        df = pd.DataFrame([trade_record])
        if self.trades_file.exists():
            df.to_csv(self.trades_file, mode='a', header=False, index=False)
        else:
            df.to_csv(self.trades_file, index=False)

    # --- Broker Interface ---

    def place_order(self, ticker: str, side: str, qty: float, order_type: str = "market", limit_price: float = None, price: float = None):
        """
        Execute a shadow trade.
        NOTE: 'price' argument is required for simulation (the execution price).
        In a real broker, price is determined by the market. Here, the Caller must provide current price.
        """
        if price is None:
            # Fallback if caller forgets price (shouldn't happen in shadow loop)
            print(f"[SHADOW][ERROR] Order rejected for {ticker}. Execution price required for simulation.")
            return None
            
        side = side.lower()
        qty = abs(float(qty))
        
        cost = price * qty
        
        # Validation
        if side == "buy":
            if cost > self.cash:
                print(f"[SHADOW][WARN] Insufficient ghost cash for {ticker}. Req: {cost}, Avail: {self.cash}")
                return None
            
            # Update Cash
            self.cash -= cost
            
            # Update Position
            current_qty = self.positions.get(ticker, 0.0)
            current_avg = self.avg_costs.get(ticker, 0.0)
            
            # Weighted Average Price
            new_qty = current_qty + qty
            new_avg = ((current_qty * current_avg) + (qty * price)) / new_qty
            
            self.positions[ticker] = new_qty
            self.avg_costs[ticker] = new_avg
            
        elif side == "sell":
            current_qty = self.positions.get(ticker, 0.0)
            if current_qty < qty:
                print(f"[SHADOW][WARN] Insufficient shares to sell {ticker}. Have: {current_qty}, Want: {qty}")
                # We interpret this as "close all" if close, but let's be strict
                return None
            
            # Update Cash
            self.cash += cost
            
            # Update Position
            self.positions[ticker] = current_qty - qty
            if self.positions[ticker] < 1e-9:
                self.positions[ticker] = 0.0
                self.avg_costs[ticker] = 0.0
        
        # Log
        trade = {
            "timestamp": datetime.datetime.now().isoformat(),
            "symbol": ticker,
            "side": side,
            "qty": qty,
            "price": price,
            "type": order_type
        }
        self._log_trade(trade)
        self._save_state()
        
        print(f"[SHADOW] {side.upper()} {qty} {ticker} @ ${price:.2f}")
        return {"id": "shadow_order_123", "status": "filled", "filled_avg_price": price}

    def get_positions(self) -> dict:
        return {k: v for k, v in self.positions.items() if v > 0}

    def get_equity(self) -> float:
        return self.last_equity

    def update_prices(self, price_map: Dict[str, float]):
        """
        Mark to Market. Updates equity calculation based on latest prices.
        """
        pos_val = 0.0
        for sym, qty in self.positions.items():
            if qty > 0:
                price = price_map.get(sym, self.avg_costs.get(sym, 0.0)) # Fallback to cost basis if no price
                pos_val += qty * price
        
        self.last_equity = self.cash + pos_val
        self._save_state()
        return self.last_equity
