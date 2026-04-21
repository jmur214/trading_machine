
# cockpit/dashboard_v2/callbacks/performance_callbacks.py
from __future__ import annotations
import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output
from pathlib import Path

from ..utils.datamanager import DataManager
from ..utils.chart_helpers import get_chart_layout, empty_chart, timeframe_filter

dataman = DataManager()

# --------------------- Callback ---------------------
def register_performance_callbacks(app):
    @app.callback(
        Output("rolling_sharpe_chart", "figure"),
        Output("rolling_maxdd_chart", "figure"),
        Output("pnl_decomp_chart", "figure"),
        Output("edge_corr_heatmap", "figure"),
        Output("perf_allocation_chart", "figure"),
        Output("equity_vs_bench_chart", "figure"),
        Output("analytics_trades_table", "data"),
        Input("timeframe_performance", "value"),
        Input("mode_state", "data"),
        Input("benchmark_selector", "value"),
        Input("pulse", "n_intervals"), 
        prevent_initial_call=False,
    )
    def update_performance_merged(tf_value, mode_value, bench_symbol, _n):
        # 1. Load Data
        try:
            if mode_value == "paper":
                df = dataman.get_equity_curve("paper")
                trades = dataman.get_trades("paper")
            else:
                df = dataman.get_equity_curve("backtest")
                trades = dataman.get_trades("backtest")
        except Exception:
            df, trades = None, None

        df_tf = timeframe_filter(df, tf_value) if df is not None else pd.DataFrame()
        trades_tf = timeframe_filter(trades, tf_value) if (trades is not None and not trades.empty) else pd.DataFrame()

        # 2. Rolling Sharpe
        if df_tf.empty:
            sharpe_fig = empty_chart("No equity data")
            maxdd_fig = empty_chart("No equity data")
        else:
            sharpe_fig = go.Figure()
            rets = df_tf["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
            if not rets.empty:
                win = 21
                roll_mean = rets.rolling(win).mean()
                roll_std = rets.rolling(win).std()
                roll_sharpe = (roll_mean / roll_std) * np.sqrt(252)
                sharpe_fig.add_trace(go.Scatter(x=df_tf["timestamp"], y=roll_sharpe, mode="lines", name="Sharpe", line=dict(color="#58a6ff")))
            sharpe_fig.update_layout(get_chart_layout(yaxis_title="Sharpe"))

            # Rolling Max Drawdown
            maxdd_fig = go.Figure()
            roll_max = df_tf["equity"].cummax()
            drawdown = (df_tf["equity"] - roll_max) / roll_max
            maxdd_fig.add_trace(go.Scatter(x=df_tf["timestamp"], y=drawdown.clip(-1, 0), fill="tozeroy", mode="lines", name="Drawdown", line=dict(color="#f85149")))
            maxdd_fig.update_layout(get_chart_layout(yaxis_title="Drawdown", yaxis_tickformat=".0%"))

        # 3. PnL Decomposition by Strategy
        if trades_tf.empty or "edge" not in trades_tf.columns or "pnl" not in trades_tf.columns:
            pnl_fig = empty_chart("No attribution data")
        else:
            pnl_by_edge = trades_tf.groupby("edge")["pnl"].sum().sort_values(ascending=True)
            pnl_fig = go.Figure()
            colors = ["#3fb950" if v >= 0 else "#f85149" for v in pnl_by_edge.values]
            pnl_fig.add_trace(go.Bar(
                y=pnl_by_edge.index, x=pnl_by_edge.values, orientation='h', 
                marker_color=colors, text=[f"${v:,.0f}" for v in pnl_by_edge.values], textposition="auto"
            ))
            pnl_fig.update_layout(get_chart_layout(xaxis_title="Net PnL ($)"))

        # 4. Correlation Heatmap
        if trades_tf.empty:
            corr_fig = empty_chart("Insufficient trade data")
        else:
            # Check edge/pnl existence
            if not {"edge", "timestamp", "pnl"}.issubset(trades_tf.columns):
                corr_fig = empty_chart("Missing columns")
            else:
                try:
                    tmp = trades_tf.copy()
                    tmp["date"] = pd.to_datetime(tmp["timestamp"]).dt.date
                    daily_edge = tmp.groupby(["date", "edge"])["pnl"].sum().unstack().fillna(0.0)
                    if daily_edge.shape[1] >= 2 and daily_edge.shape[0] > 1:
                        corr = daily_edge.corr().fillna(0.0)
                        corr_fig = go.Figure(data=go.Heatmap(
                            z=corr.values, x=corr.columns.astype(str), y=corr.index.astype(str), 
                            zmin=-1, zmax=1, colorscale="RdBu", colorbar=dict(title="Corr")
                        ))
                        corr_fig.update_layout(get_chart_layout())
                    else:
                        corr_fig = empty_chart("Need >1 strategy/day")
                except Exception:
                    corr_fig = empty_chart("Corr Calc Error")

        # 5. Current Allocation (Real Sector Exposure)
        gov_fig = go.Figure()
        try:
            # Load real positions
            if mode_value == "paper":
                pos_df = dataman.get_positions("paper")
            else:
                pos_df = dataman.get_positions("backtest")

            if not pos_df.empty:
                # Group by symbol and sum market value (qty * current_price or cost basis)
                # positions.csv usually has: symbol, qty, avg_entry_price, current_price, market_value...
                # If market_value missing, calc: qty * avg_entry_price (rough)
                
                # Check columns
                if "market_value" not in pos_df.columns:
                    if "qty" in pos_df.columns and "avg_entry_price" in pos_df.columns:
                        pos_df["market_value"] = pos_df["qty"] * pos_df["avg_entry_price"]
                    else:
                        pos_df["market_value"] = 0
                
                # Filter non-zero
                pos_df = pos_df[pos_df["market_value"] != 0].copy()
                
                if not pos_df.empty:
                    import yfinance as yf
                    # Simple in-memory cache for sector lookups to avoid rate limits
                    if not hasattr(update_performance_merged, "sector_cache"):
                        update_performance_merged.sector_cache = {}
                    
                    sectors_map = {}
                    for sym in pos_df["symbol"].unique():
                        # Normalize symbol (remove crypto USD suffix if needed, though yf needs it)
                        s_lookup = sym
                        if sym not in update_performance_merged.sector_cache:
                            try:
                                # Fetch sector
                                tick = yf.Ticker(s_lookup)
                                # Fast access to info
                                sec = tick.info.get("sector", "Unknown")
                                update_performance_merged.sector_cache[sym] = sec
                            except:
                                update_performance_merged.sector_cache[sym] = "Unknown"
                        sectors_map[sym] = update_performance_merged.sector_cache[sym]
                    
                    pos_df["sector"] = pos_df["symbol"].map(sectors_map)
                    
                    # Group by sector
                    sector_alloc = pos_df.groupby("sector")["market_value"].sum().abs()
                    
                    # Add Cash if available? dataman.get_summary() might have 'cash'
                    # For now, just invested allocation
                    
                    gov_fig.add_trace(go.Pie(
                        labels=sector_alloc.index, 
                        values=sector_alloc.values, 
                        hole=0.4,
                        textinfo="label+percent",
                        hoverinfo="label+value+percent",
                        showlegend=True
                    ))
                    gov_fig.update_layout(get_chart_layout(showlegend=True, margin=dict(l=20, r=20, t=20, b=20)))
                else:
                    gov_fig = empty_chart("No active positions")
            else:
                gov_fig = empty_chart("No active positions")

        except Exception as e:
            gov_fig = empty_chart(f"Sector Data Error: {str(e)[:20]}")

        # 6. Benchmark Comparison (Real Data via yfinance)
        if df_tf.empty:
            bench_fig = empty_chart("No equity data")
        else:
            bench_fig = go.Figure()
            # Equity normalized
            start_eq = df_tf["equity"].iloc[0]
            norm_eq = 100 * (df_tf["equity"] / start_eq)
            bench_fig.add_trace(go.Scatter(x=df_tf["timestamp"], y=norm_eq, mode="lines", name="Strategy", line=dict(color="#58a6ff")))
            
            try:
                import yfinance as yf
                s_date = df_tf["timestamp"].min().strftime("%Y-%m-%d")
                e_date = df_tf["timestamp"].max().strftime("%Y-%m-%d")
                
                b_df = yf.download(bench_symbol, start=s_date, end=e_date, progress=False)
                
                if not b_df.empty:
                    # Robust MultiIndex handling
                    if isinstance(b_df.columns, pd.MultiIndex):
                        if "Close" in b_df.columns.levels[0]:
                            b_df = b_df.xs("Close", level=0, axis=1)
                    elif "Close" in b_df.columns:
                        b_df = b_df[["Close"]]
                    
                    # Ensure single 'Close' column
                    if len(b_df.columns) == 1:
                        b_df.columns = ["Close"]
                    else:
                        # Fallback
                        if bench_symbol in b_df.columns:
                            b_df = b_df[[bench_symbol]].rename(columns={bench_symbol: "Close"})
                        else:
                            b_df = b_df.iloc[:, [0]]
                            b_df.columns = ["Close"]
                    
                    b_df = b_df.reset_index()
                    col_date = "Date" if "Date" in b_df.columns else b_df.columns[0]
                    # UTC alignment
                    b_df[col_date] = pd.to_datetime(b_df[col_date]).dt.tz_localize(None) 
                    
                    # Normalize
                    base_price = b_df["Close"].iloc[0] if not b_df.empty else 1.0
                    b_df["norm"] = 100 * (b_df["Close"] / base_price)
                    
                    bench_fig.add_trace(go.Scatter(
                        x=b_df[col_date], y=b_df["norm"], 
                        mode="lines", name=f"{bench_symbol}",
                        line=dict(color="#8b949e", dash="dot")
                    ))
                else:
                    # No data but don't show error, just standard message
                    bench_fig.add_annotation(text="No Benchmark Data", showarrow=False, font=dict(color="#6e7681"))
            except Exception:
                # No synthetic fallback
                pass
            
            bench_fig.update_layout(get_chart_layout(yaxis_title="Normalized (%)", legend=dict(x=0, y=1)))

        # 7. Trades Table Data
        table_data = []
        if not trades_tf.empty:
            t_copy = trades_tf.copy().sort_values("timestamp", ascending=False)
            cols = ["timestamp", "ticker", "edge", "side", "qty", "fill_price", "pnl"]
            for c in cols: 
                if c not in t_copy.columns: t_copy[c] = "-"
            
            for idx, row in t_copy.head(50).iterrows(): 
                rec = row.to_dict()
                try: rec["timestamp"] = pd.to_datetime(rec["timestamp"]).strftime("%Y-%m-%d %H:%M")
                except: pass
                for k in ["fill_price", "pnl"]:
                    if isinstance(rec.get(k), (int, float)): rec[k] = f"${rec[k]:.2f}"
                table_data.append(rec)

        return sharpe_fig, maxdd_fig, pnl_fig, corr_fig, gov_fig, bench_fig, table_data