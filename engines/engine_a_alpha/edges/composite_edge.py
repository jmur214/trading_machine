import pandas as pd
import numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edge_template import EdgeTemplate
from engines.data_manager.data_manager import DataManager

class CompositeEdge(EdgeBase, EdgeTemplate):
    """
    The 'Genome' of the Trading Machine.
    It holds a list of 'Conditions' (Genes) that must ALL be true to trigger a signal.
    
    Genes are dictionaries:
    {
       "type": "technical" | "fundamental",
       "indicator": "rsi" | "pe_ratio" | "sma_cross" ...,
       "params": { ... },
       "operator": "<" | ">",
       "threshold": 15.0
    }
    
    This allows the DiscoveryEngine to arbitrarily combine:
    - Tech + Tech
    - Fund + Fund
    - Tech + Fund
    """
    
    EDGE_ID = "composite_v1"
    EDGE_GROUP = "composite"
    EDGE_CATEGORY = "evolutionary"

    @classmethod
    def get_hyperparameter_space(cls):
        # The 'space' here is actually the Meta-Space of possible Genes.
        # DiscoveryEngine will handle the structural mutation (adding/removing genes).
        # This generic space helps with basic parameter mutations.
        return {} 

    def __init__(self, params=None):
        super().__init__()
        self.set_params(params) 
        self.dm = DataManager()
        self.fundamental_cache = {} 
        self.genes = self.params.get("genes", [])
        self.direction = self.params.get("direction", "long") # long | short
        
    def compute_signals(self, data_map, as_of):
        scores = {}

        # Store data_map reference for inter-market gene evaluation
        self._current_data_map = data_map

        # 1. Regime context (provided by AlphaEngine via regime_meta attribute)
        current_regime = self.regime_meta or {"trend": "unknown", "volatility": "unknown"}

        # 2. Calculation Phase: Collect all raw values
        # ticker_gene_vals[ticker] = {gene_idx: raw_value}
        ticker_gene_vals = {}
        # gene_all_vals[gene_idx] = [v1, v2, v3...] for ranking
        gene_all_vals = {i: [] for i in range(len(self.genes))}

        for t, df in data_map.items():
            if len(df) < 50 or "Close" not in df:
                continue
                
            ticker_gene_vals[t] = {}
            
            for i, gene in enumerate(self.genes):
                # Calculate Raw Value (Technical / Fundamental / Regime=None)
                try:
                    val = self._calc_raw_value(t, df, as_of, gene, current_regime)
                    if val is not None:
                        ticker_gene_vals[t][i] = val
                        # Only collect for ranking if it's numeric
                        if isinstance(val, (int, float)):
                            gene_all_vals[i].append(val)
                except Exception:
                    pass

        # 3. Evaluation Phase (Ranking & Boolean Logic)
        for t in ticker_gene_vals:
            all_genes_pass = True
            
            for i, gene in enumerate(self.genes):
                val = ticker_gene_vals[t].get(i)
                operator = gene.get("operator", "<")
                threshold = gene.get("threshold", 0.0)
                
                # Handling Regime Genes (Val is True/False already)
                if gene.get("type") == "regime":
                    if not val: 
                        all_genes_pass = False
                        break
                    continue
                
                if val is None:
                    all_genes_pass = False
                    break
                    
                # Cross-Sectional Operators
                if operator == "top_percentile":
                    # threshold is percentile (e.g. 90)
                    all_vals = gene_all_vals.get(i, [])
                    if not all_vals:
                        all_genes_pass = False; break
                    cutoff = np.percentile(all_vals, threshold)
                    if val < cutoff:
                        all_genes_pass = False; break
                        
                elif operator == "bottom_percentile":
                    # threshold is percentile (e.g. 10)
                    all_vals = gene_all_vals.get(i, [])
                    if not all_vals:
                        all_genes_pass = False; break
                    cutoff = np.percentile(all_vals, threshold)
                    if val > cutoff:
                        all_genes_pass = False; break

                # Standard Operators
                elif operator == "less":
                    if not (val < threshold): all_genes_pass = False; break
                elif operator == "greater":
                    if not (val > threshold): all_genes_pass = False; break
            
            if all_genes_pass and len(self.genes) > 0:
                scores[t] = 1.0 if self.direction == "long" else -1.0
            else:
                scores[t] = 0.0
                
        return scores

    def _calc_raw_value(self, ticker, df, as_of, gene, regime_ctx):
        """Calculates the raw numeric value or boolean (for regime)"""
        g_type = gene.get("type")

        if g_type == "regime":
            target = gene.get("is")
            trend = regime_ctx.get("trend", "unknown")
            vol = regime_ctx.get("volatility", "unknown")
            op = gene.get("operator", "is")

            match = (target in [trend, vol])
            if op == "is_not":
                return not match
            return match

        if g_type == "technical":
            return self._calc_technical_val(df, gene)
        elif g_type == "fundamental":
            return self._calc_fundamental_val(ticker, as_of, gene)
        elif g_type == "calendar":
            return self._calc_calendar_val(df, as_of, gene)
        elif g_type == "microstructure":
            return self._calc_microstructure_val(df, gene)
        elif g_type == "intermarket":
            return self._calc_intermarket_val(df, as_of, gene)

        return None

    def _calc_technical_val(self, df, gene):
        indicator = gene.get("indicator")
        window = gene.get("window", 14)
        
        # Price Series
        close = df["Close"]
        
        if indicator == "rsi":
            delta = close.diff()
            up, down = delta.clip(lower=0), -delta.clip(upper=0)
            rs = up.rolling(window).mean() / (down.rolling(window).mean() + 1e-9)
            rsi = 100 - (100 / (1 + rs))
            return float(rsi.iloc[-1])
            
        elif indicator == "sma_dist_pct":
            # (Price - SMA) / SMA
            sma = close.rolling(window).mean().iloc[-1]
            price = close.iloc[-1]
            return (price - sma) / sma
            
        elif indicator == "volatility":
             # std of returns
             return float(close.pct_change().rolling(window).std().iloc[-1])
             
        elif indicator == "donchian_breakout":
            # 1.0 if High >= Max(High, N-1), else 0.0
            # Strategy 3.15
            highs = df["High"]
            recent_high = highs.iloc[-2:-1].max() # Prior N usually excludes today for signal
            # Standard Donchian: Max of LAST N days (excluding today potentially)
            # Let's say window=20.
            # If Today's Close > Max(High of last 20 days excluding today), Breakout.
            # We return distance ratio: (Close - ChannelHigh) / Close
            # Positive = Breakout.
            
            # Use rolling max shifted by 1
            roll_max = highs.rolling(window).max().shift(1).iloc[-1]
            curr_close = close.iloc[-1]
            return (curr_close - roll_max) / roll_max

        elif indicator == "pivot_position":
            # Strategy 3.14 (Pivot Points)
            # (Price - Pivot) / Pivot. Positive = Above Pivot (Bullish).
            # Pivot = (H+L+C)/3 of YESTERDAY
            if len(df) < 2: return None
            prev = df.iloc[-2]
            pivot = (prev["High"] + prev["Low"] + prev["Close"]) / 3
            curr = close.iloc[-1]
            return (curr - pivot) / pivot
            
        elif indicator == "momentum_roc":
            # Strategy 3.1 (Price Momentum)
            # ROC = (Price / Price_N_ago) - 1
            if len(df) <= window: return None
            curr = close.iloc[-1]
            past = close.iloc[-1 - window]
            return (curr / past) - 1.0

        elif indicator == "sma_cross":
            # Strategy 3.12 (Two Moving Averages)
            # Returns 1.0 if Fast > Slow (Bullish), -1.0 if Fast < Slow
            # Params: window_fast, window_slow
            fast_win = gene.get("window_fast", 10)
            slow_win = gene.get("window_slow", 50)
            
            fast_ma = close.rolling(fast_win).mean().iloc[-1]
            slow_ma = close.rolling(slow_win).mean().iloc[-1]
            
            return 1.0 if fast_ma > slow_ma else -1.0

        elif indicator == "residual_momentum":
            # Strategy 3.7 (Residual Momentum)
            # Epsilon = R_stock - Beta * R_market
            spy_df = self.regime_cache.get("spy_df_ref") # Need access to SPY
            if spy_df is None: return None # Can't calc without benchmark
            
            # Align timestamps
            stock_rets = close.pct_change().dropna()[-window:]
            spy_rets = spy_df["Close"].pct_change().dropna().reindex(stock_rets.index)
            
            if len(stock_rets) < window or len(spy_rets) < window: return None
            
            # Simple Regression: Beta = Cov(s,m)/Var(m)
            cov = np.cov(stock_rets, spy_rets)[0][1]
            var_m = np.var(spy_rets)
            beta = cov / (var_m + 1e-9)
            
            # Residual Return (Last period or Cumulative?) 
            # Usually Cumulative Residual over window
            stock_cum = (1 + stock_rets).prod() - 1
            spy_cum = (1 + spy_rets).prod() - 1
            
            epsilon = stock_cum - (beta * spy_cum)
            return float(epsilon)

        elif indicator == "volatility_diff":
            # Strategy 3.5 Proxy (IV Change -> Realized Vol Change)
            # Current Vol - Past Vol
            curr_vol = close.pct_change().tail(10).std()
            past_vol = close.pct_change().shift(10).tail(10).std()
            return float(curr_vol - past_vol)

        return None

    def _calc_fundamental_val(self, ticker, as_of, gene):
        metric = gene.get("metric")

        if ticker not in self.fundamental_cache:
             self.fundamental_cache[ticker] = self.dm.fetch_historical_fundamentals(ticker)

        fund_df = self.fundamental_cache[ticker]
        if fund_df.empty or metric not in fund_df.columns:
            return None

        try:
            idx_loc = fund_df.index.get_indexer([as_of], method='pad')[0]
            if idx_loc == -1:
                return None
            return fund_df.iloc[idx_loc][metric]
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Calendar gene evaluation
    # ------------------------------------------------------------------

    def _calc_calendar_val(self, df, as_of, gene):
        """Evaluate calendar/seasonality gene conditions."""
        indicator = gene.get("indicator")

        if not isinstance(as_of, pd.Timestamp):
            return None

        if indicator == "day_of_week_sin":
            # Cyclical encoding: sin(2*pi*dow/5)
            return float(np.sin(2 * np.pi * as_of.dayofweek / 5.0))

        elif indicator == "month_sin":
            return float(np.sin(2 * np.pi * as_of.month / 12.0))

        elif indicator == "quarter_end_proximity":
            # Trading days until quarter end
            q_month = ((as_of.month - 1) // 3 + 1) * 3
            q_year = as_of.year
            if q_month > 12:
                q_month = 3
                q_year += 1
            q_end = pd.Timestamp(year=q_year, month=q_month, day=1) + pd.offsets.MonthEnd(0)
            delta = np.busday_count(as_of.date(), q_end.date())
            return float(max(delta, 0))

        elif indicator == "opex_proximity":
            # Trading days until next options expiration (third Friday)
            year, month = as_of.year, as_of.month
            first = pd.Timestamp(year=year, month=month, day=1)
            days_to_friday = (4 - first.dayofweek) % 7
            third_friday = first + pd.Timedelta(days=days_to_friday + 14)
            if as_of.date() > third_friday.date():
                if month == 12:
                    year, month = year + 1, 1
                else:
                    month += 1
                first = pd.Timestamp(year=year, month=month, day=1)
                days_to_friday = (4 - first.dayofweek) % 7
                third_friday = first + pd.Timedelta(days=days_to_friday + 14)
            delta = np.busday_count(as_of.date(), third_friday.date())
            return float(max(delta, 0))

        return None

    # ------------------------------------------------------------------
    # Microstructure gene evaluation
    # ------------------------------------------------------------------

    def _calc_microstructure_val(self, df, gene):
        """Evaluate price-action microstructure gene conditions."""
        indicator = gene.get("indicator")

        if len(df) < 2:
            return None

        close = df["Close"]

        if indicator == "overnight_gap":
            if "Open" not in df.columns:
                return None
            # (Open_today - Close_yesterday) / Close_yesterday
            prev_close = close.iloc[-2]
            curr_open = df["Open"].iloc[-1]
            return float((curr_open - prev_close) / (prev_close + 1e-9))

        elif indicator == "close_location":
            if not all(c in df.columns for c in ["High", "Low"]):
                return None
            # Where in the bar did the close occur? 0=low, 1=high
            h, l, c = df["High"].iloc[-1], df["Low"].iloc[-1], close.iloc[-1]
            bar_range = h - l
            if bar_range < 1e-9:
                return 0.5
            return float(np.clip((c - l) / bar_range, 0.0, 1.0))

        elif indicator == "intraday_range":
            if not all(c in df.columns for c in ["High", "Low"]):
                return None
            h, l, c = df["High"].iloc[-1], df["Low"].iloc[-1], close.iloc[-1]
            return float((h - l) / (c + 1e-9))

        return None

    # ------------------------------------------------------------------
    # Inter-market gene evaluation
    # ------------------------------------------------------------------

    def _calc_intermarket_val(self, df, as_of, gene):
        """Evaluate inter-market gene conditions using data_map context."""
        indicator = gene.get("indicator")
        window = gene.get("window", 5)

        # Access the full data_map via the edge's context
        # CompositeEdge receives data_map in compute_signals, but individual
        # gene evaluation only gets per-ticker df. We store a reference to
        # data_map during compute_signals for inter-market lookups.
        data_map = getattr(self, "_current_data_map", None)
        if data_map is None:
            return None

        if indicator == "spy_return_5d":
            return self._get_asset_return(data_map, "SPY", df.index, window)

        elif indicator == "tlt_return_5d":
            return self._get_asset_return(data_map, "TLT", df.index, window)

        elif indicator == "gld_return_5d":
            return self._get_asset_return(data_map, "GLD", df.index, window)

        elif indicator == "spy_tlt_corr":
            spy_df = data_map.get("SPY")
            tlt_df = data_map.get("TLT")
            if spy_df is None or tlt_df is None:
                return None
            try:
                spy_ret = spy_df["Close"].reindex(df.index).ffill().pct_change()
                tlt_ret = tlt_df["Close"].reindex(df.index).ffill().pct_change()
                corr = spy_ret.rolling(60).corr(tlt_ret)
                val = corr.iloc[-1]
                return float(val) if not pd.isna(val) else None
            except Exception:
                return None

        return None

    def _get_asset_return(self, data_map, ticker, index, window):
        """Helper: get rolling return of an asset aligned to the current index."""
        asset_df = data_map.get(ticker)
        if asset_df is None or "Close" not in asset_df.columns:
            return None
        try:
            aligned = asset_df["Close"].reindex(index).ffill()
            ret = aligned.pct_change(window)
            val = ret.iloc[-1]
            return float(val) if not pd.isna(val) else None
        except Exception:
            return None
