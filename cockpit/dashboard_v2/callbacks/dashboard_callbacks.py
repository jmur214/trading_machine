# cockpit/dashboard/callbacks/dashboard_callbacks.py
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from dash import Input, Output, html
import plotly.graph_objects as go

from ..utils.datamanager import DataManager
from ..utils.websocket_manager import AlpacaStreamManager

# --------------------- Helper functions for timeframe filtering, FIFO PnL, summary ---------------------
def timeframe_filter(df: pd.DataFrame, tf_value: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce", utc=True)
    out = out.dropna(subset=["timestamp"]).sort_values("timestamp")
    if tf_value == "all" or out["timestamp"].empty:
        return out
    end_date = out["timestamp"].max()
    offsets = {
        "1y": pd.DateOffset(years=1),
        "6m": pd.DateOffset(months=6),
        "3m": pd.DateOffset(months=3),
        "1m": pd.DateOffset(months=1),
    }
    if tf_value in offsets:
        start = end_date - offsets[tf_value]
        return out[out["timestamp"] >= start]
    return out

def compute_trade_pnl_fifo(trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame(columns=["timestamp","ticker","side","qty","fill_price","commission","pnl","edge"])
    df = trades.copy()
    for col in ("qty","fill_price","commission"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "commission" not in df.columns:
        df["commission"] = 0.0
    if "edge" not in df.columns:
        df["edge"] = "Unknown"
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"]).sort_values(["ticker","timestamp"])
    if "pnl" not in df.columns:
        df["pnl"] = np.nan

    def sign_for(side: str) -> int:
        s = str(side).lower()
        return +1 if s == "long" else (-1 if s == "short" else 0)

    def closes_position(prev_sign: int, now_side: str) -> bool:
        s = str(now_side).lower()
        if s in ("exit","cover"):
            return True
        now_sign = sign_for(s)
        return prev_sign != 0 and now_sign != 0 and np.sign(prev_sign) != np.sign(now_sign)

    stacks: dict[str, list[dict]] = {}
    for tkr, tdf in df.groupby("ticker", sort=False):
        stack = stacks.setdefault(tkr, [])
        def current_net_sign() -> int:
            if not stack:
                return 0
            net = sum(leg["sign"] * leg["qty"] for leg in stack)
            return int(np.sign(net)) if net != 0 else 0
        prev_net_sign = 0
        for idx, row in tdf.iterrows():
            side = str(row.get("side","")).lower()
            qty = int(row.get("qty",0))
            px = float(row.get("fill_price", np.nan))
            if qty <= 0 or not np.isfinite(px):
                continue
            if side in ("long","short"):
                now_sign = sign_for(side)
                if prev_net_sign == 0 or prev_net_sign == now_sign:
                    stack.append({"sign": now_sign, "price": px, "qty": qty})
                else:
                    remaining = qty
                    realized = 0.0
                    while remaining > 0 and stack and np.sign(stack[0]["sign"]) != np.sign(now_sign):
                        leg = stack[0]
                        m = min(remaining, leg["qty"])
                        direction = leg["sign"]
                        realized += (px - leg["price"]) * (m * direction)
                        leg["qty"] -= m
                        remaining -= m
                        if leg["qty"] == 0:
                            stack.pop(0)
                    if remaining > 0:
                        stack.append({"sign": now_sign, "price": px, "qty": remaining})
                    df.loc[idx, "pnl"] = round(realized, 2)
            elif closes_position(prev_net_sign, side):
                remaining = qty
                realized = 0.0
                while remaining > 0 and stack:
                    leg = stack[0]
                    m = min(remaining, leg["qty"])
                    direction = leg["sign"]
                    realized += (px - leg["price"]) * (m * direction)
                    leg["qty"] -= m
                    remaining -= m
                    if leg["qty"] == 0:
                        stack.pop(0)
                df.loc[idx, "pnl"] = round(realized, 2)
            prev_net_sign = current_net_sign()
    return df

def summarize_period(df_snap: pd.DataFrame, df_trades: pd.DataFrame) -> dict:
    if df_snap is None or df_snap.empty:
        return {
            "Starting Equity": "-","Ending Equity":"-","Net Profit":"-",
            "Total Return (%)":"-","CAGR (%)":"-","Max Drawdown (%)":"-",
            "Sharpe Ratio":"-","Volatility (%)":"-","Win Rate (%)":"-",
        }
    start_eq = float(df_snap["equity"].iloc[0])
    end_eq = float(df_snap["equity"].iloc[-1])
    total_ret = np.nan if start_eq <= 0 else (end_eq - start_eq)/start_eq
    days = (df_snap["timestamp"].iloc[-1] - df_snap["timestamp"].iloc[0]).days
    cagr = (1+total_ret)**(365.0/days)-1 if (days>0 and not np.isnan(total_ret)) else np.nan
    roll_max = df_snap["equity"].cummax()
    dd = (df_snap["equity"] - roll_max)/roll_max
    dd = dd.replace([np.inf,-np.inf], np.nan).fillna(0.0).clip(lower=-1, upper=0)
    max_dd = dd.min()*100.0
    rets = df_snap["equity"].pct_change().replace([np.inf,-np.inf], np.nan).dropna() if "equity" in df_snap.columns else pd.Series(dtype=float)
    vol = rets.std()*np.sqrt(252)*100.0 if not rets.empty else np.nan
    sharpe = (rets.mean()/rets.std())*np.sqrt(252) if (not rets.empty and rets.std()>0) else np.nan
    win_rate = np.nan
    if df_trades is not None and not df_trades.empty and "pnl" in df_trades.columns:
        realized = df_trades.dropna(subset=["pnl"])
        if not realized.empty:
            win_rate = 100.0 * (realized["pnl"] > 0).sum() / len(realized)
    return {
        "Starting Equity": round(start_eq,2),
        "Ending Equity": round(end_eq,2),
        "Net Profit": round(end_eq-start_eq,2),
        "Total Return (%)": None if np.isnan(total_ret) else round(total_ret*100.0,2),
        "CAGR (%)": None if np.isnan(cagr) else round(cagr*100.0,2),
        "Max Drawdown (%)": None if np.isnan(max_dd) else round(max_dd,2),
        "Sharpe Ratio": None if np.isnan(sharpe) else round(sharpe,3),
        "Volatility (%)": None if np.isnan(vol) else round(vol,2),
        "Win Rate (%)": None if np.isnan(win_rate) else round(win_rate,2),
    }

import os
ALPACA_API_KEY = os.environ.get("APCA_API_KEY_ID", "")
ALPACA_API_SECRET = os.environ.get("APCA_API_SECRET_KEY", "")

dataman = DataManager()
alpaca_ws = AlpacaStreamManager(ALPACA_API_KEY, ALPACA_API_SECRET, paper=True)
alpaca_ws.start()

def register_dashboard_callbacks(app):
    @app.callback(
        Output("equity_chart", "figure"),
        Output("drawdown_chart", "figure"),
        Output("edge_pnl_chart", "figure"),
        Output("summary_box", "children"),
        Output("recent_trades_box", "children"),
        Input("timeframe", "value"),
        Input("pulse", "n_intervals"),
        Input("mode_state", "data"),
        Input("refresh_button", "n_clicks"),
        prevent_initial_call=False,
    )
    def update_dashboard(tf_value, n_pulse, mode_value, _refresh_clicks):
        # LIVE placeholder
        if mode_value == "live":
            empty_fig = go.Figure()
            empty_fig.update_layout(
                template="plotly_dark",
                annotations=[dict(text="LIVE MODE (Coming Soon)", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font=dict(color="orange", size=32))]
            )
            return empty_fig, empty_fig, empty_fig, html.Div("Live mode disabled."), "Live mode disabled."

        # PAPER MODE
        if mode_value == "paper":
            eq_df = dataman.get_equity_curve("paper")
            trades_df = dataman.get_trades("paper")
            positions_df = dataman.get_positions("paper")

            # Persist paper logs (optional)
            try:
                Path("data/trade_logs/paper/").mkdir(parents=True, exist_ok=True)
                if not eq_df.empty:
                    eq_df.to_csv("data/trade_logs/paper/portfolio_snapshots.csv", index=False)
                if trades_df is not None and not trades_df.empty:
                    trades_df.to_csv("data/trade_logs/paper/trades.csv", index=False)
                if positions_df is not None and not positions_df.empty:
                    positions_df.to_csv("data/trade_logs/paper/positions.csv", index=False)
            except Exception:
                pass

            latest_equity = None
            latest_positions = []
            try:
                while not alpaca_ws.queue.empty():
                    msg = alpaca_ws.queue.get_nowait()
                    if msg["type"] == "account":
                        data = msg["data"]
                        latest_equity = float(getattr(data, "equity", None) or getattr(data, "cash", 0) or 0) if not isinstance(data, dict) else float(data.get("equity", 0))
                    elif msg["type"] == "trade":
                        latest_positions.append(str(msg["data"]))
            except Exception:
                pass

            try:
                from alpaca.trading.client import TradingClient
            except Exception:
                TradingClient = None

            if TradingClient is not None and ALPACA_API_KEY and ALPACA_API_SECRET:
                try:
                    client = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=True)
                    account = client.get_account()
                    positions = client.get_all_positions()
                    equity = latest_equity if latest_equity is not None else float(getattr(account, "equity", None) or 0)
                    buying_power = float(getattr(account, "buying_power", None) or 0)
                    cash = float(getattr(account, "cash", None) or 0)
                    unrealized_pl = float(getattr(account, "unrealized_pl", None) or 0)

                    def kpi(label, value):
                        return html.Div(
                            [
                                html.Div(label, style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                                html.Div(f"${value:,.2f}", style={"fontSize": "22px", "fontWeight": 600}),
                            ],
                            style={
                                "backgroundColor": "#181c22", "color": "#e0e0e0", "padding": "16px 18px",
                                "borderRadius": "10px", "boxShadow": "0 2px 12px rgba(0,0,0,0.21)", "margin": "0 10px 12px 0",
                                "minWidth": "140px", "textAlign": "center", "display": "inline-block",
                            },
                        )

                    summary_cards = html.Div(
                        [
                            kpi("Equity", equity),
                            kpi("Buying Power", buying_power),
                            kpi("Cash", cash),
                            kpi("Unrealized PnL", unrealized_pl),
                        ],
                        style={"display": "flex", "flexWrap": "wrap", "gap": "0.5rem", "marginBottom": "10px"},
                    )

                    # Equity chart
                    eq_fig = go.Figure()
                    if not eq_df.empty:
                        eq_fig.add_trace(go.Scatter(x=eq_df["timestamp"], y=eq_df["equity"], mode="lines", name="Equity", line=dict(color="deepskyblue", width=2)))
                    else:
                        eq_fig.add_trace(go.Scatter(x=["Now"], y=[equity], mode="markers+text", text=[f"${equity:,.2f}"], textposition="top center"))
                    eq_fig.update_layout(title="Account Equity (Paper)", yaxis_title="Equity ($)", template="plotly_dark", showlegend=False)

                    # Drawdown chart
                    dd_fig = go.Figure()
                    if not eq_df.empty:
                        roll_max = eq_df["equity"].cummax()
                        drawdown = (eq_df["equity"] - roll_max) / roll_max
                        dd_fig.add_trace(go.Scatter(x=eq_df["timestamp"], y=drawdown.clip(-1, 0), fill="tozeroy", mode="lines", name="Drawdown", line=dict(color="firebrick")))
                    dd_fig.update_layout(title="Drawdown Over Time", xaxis_title="Date", yaxis_title="Drawdown", yaxis_tickformat=".0%", template="plotly_dark")

                    # Edge PnL bar
                    edge_fig = go.Figure()
                    if trades_df is not None and not trades_df.empty and {"edge", "pnl"}.issubset(set(trades_df.columns)):
                        pnl_by_edge = trades_df.groupby("edge", dropna=False)["pnl"].sum().sort_values(ascending=False).reset_index()
                        if not pnl_by_edge.empty:
                            colors = ["limegreen" if v >= 0 else "firebrick" for v in pnl_by_edge["pnl"]]
                            edge_fig.add_trace(
                                go.Bar(x=pnl_by_edge["edge"].astype(str), y=pnl_by_edge["pnl"], marker_color=colors, text=[f"${v:,.2f}" for v in pnl_by_edge["pnl"]], textposition="auto", name="PnL")
                            )
                    edge_fig.update_layout(title="Profit / Loss by Edge", xaxis_title="Edge", yaxis_title="PnL ($)", template="plotly_dark")

                    # Positions text
                    pos_list = []
                    if positions:
                        for pos in positions:
                            try:
                                symbol = getattr(pos, "symbol", "-")
                                qty = getattr(pos, "qty", "-")
                                unreal = float(getattr(pos, "unrealized_pl", 0) or 0)
                                side = getattr(pos, "side", "-")
                                pos_list.append(f"{symbol} ({side}) | Qty: {qty} | Unr. PnL: ${unreal:,.2f}")
                            except Exception:
                                continue
                    if latest_positions:
                        pos_list.extend(latest_positions)
                    recent_txt = "\n".join(pos_list) if pos_list else "No open positions."
                    return eq_fig, dd_fig, edge_fig, summary_cards, recent_txt
                except Exception as e:
                    pass

            # Fallback if TradingClient missing/unavailable
            empty = go.Figure(); empty.update_layout(template="plotly_dark")
            notice = html.Div(html.Div("No paper account connected.", style={"color": "#ffb300", "fontSize": "22px", "padding": "18px 0"}))
            return empty, empty, empty, notice, "No paper account connected."

        # BACKTEST mode
        snapshots_path = "data/trade_logs/portfolio_snapshots.csv"
        trades_path = "data/trade_logs/trades.csv"
        df = dataman._safe_read_csv(Path(snapshots_path))
        trades = dataman._safe_read_csv(Path(trades_path))

        if trades is not None and not trades.empty:
            if ("pnl" not in trades.columns) or (trades["pnl"].isna().all()):
                trades = compute_trade_pnl_fifo(trades)
            if "edge" not in trades.columns:
                trades["edge"] = "Unknown"
            trades["timestamp"] = pd.to_datetime(trades["timestamp"], errors="coerce")
            trades = trades.dropna(subset=["timestamp"]).sort_values("timestamp")

        df_tf = timeframe_filter(df, tf_value) if df is not None else pd.DataFrame()
        trades_tf = timeframe_filter(trades, tf_value) if (trades is not None and not trades.empty) else pd.DataFrame()
        summary = summarize_period(df_tf, trades_tf)
        summary_cards = html.Div(_summary_kpi_cards(summary))

        eq_fig = go.Figure()
        if not df_tf.empty:
            eq_fig.add_trace(go.Scatter(x=df_tf["timestamp"], y=df_tf["equity"], mode="lines", name="Equity", line=dict(color="deepskyblue", width=2)))
        eq_fig.update_layout(title="Equity Curve", xaxis_title="Date", yaxis_title="Equity ($)", hovermode="x unified", template="plotly_dark", legend=dict(x=0, y=1))

        dd_fig = go.Figure()
        if not df_tf.empty:
            roll_max = df_tf["equity"].cummax()
            drawdown = (df_tf["equity"] - roll_max) / roll_max
            dd_fig.add_trace(go.Scatter(x=df_tf["timestamp"], y=drawdown.clip(-1, 0), fill="tozeroy", mode="lines", name="Drawdown", line=dict(color="firebrick")))
        dd_fig.update_layout(title="Drawdown Over Time", xaxis_title="Date", yaxis_title="Drawdown", yaxis_tickformat=".0%", template="plotly_dark")

        edge_fig = go.Figure()
        if not trades_tf.empty and {"edge", "pnl"}.issubset(set(trades_tf.columns)):
            pnl_by_edge = trades_tf.groupby("edge", dropna=False)["pnl"].sum().sort_values(ascending=False).reset_index()
            if not pnl_by_edge.empty:
                colors = ["limegreen" if v >= 0 else "firebrick" for v in pnl_by_edge["pnl"]]
                edge_fig.add_trace(go.Bar(x=pnl_by_edge["edge"].astype(str), y=pnl_by_edge["pnl"], marker_color=colors, text=[f"${v:,.2f}" for v in pnl_by_edge["pnl"]], textposition="auto"))
        edge_fig.update_layout(title="Profit / Loss by Edge", xaxis_title="Edge", yaxis_title="PnL ($)", template="plotly_dark")

        recent_txt = trades_tf.tail(10).to_string(index=False) if not trades_tf.empty else "No trades found."
        return eq_fig, dd_fig, edge_fig, summary_cards, recent_txt


def _summary_kpi_cards(summary: dict):
    card_style = {
        "backgroundColor": "#181c22",
        "color": "#e0e0e0",
        "padding": "16px 18px",
        "borderRadius": "10px",
        "boxShadow": "0 2px 12px rgba(0,0,0,0.21)",
        "margin": "0 10px 12px 0",
        "minWidth": "140px",
        "textAlign": "center",
        "display": "inline-block",
    }
    kpi_order = [
        "Starting Equity", "Ending Equity", "Net Profit", "Total Return (%)",
        "CAGR (%)", "Sharpe Ratio", "Max Drawdown (%)", "Volatility (%)", "Win Rate (%)",
    ]
    def fmt(val, k):
        if val == "-" or val is None: return "-"
        if any(x in k for x in ("Return", "Drawdown", "Volatility", "CAGR", "Win Rate")): return f"{val:.2f}%"
        if "Sharpe" in k: return f"{val:.3f}"
        return f"${val:,.2f}" if isinstance(val, (int, float)) else str(val)
    cards = []
    for k in kpi_order:
        v = summary.get(k, "-")
        cards.append(
            html.Div(
                [html.Div(str(k), style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                 html.Div(fmt(v, k), style={"fontSize": "22px", "fontWeight": 600})],
                style=card_style,
            )
        )
    return html.Div(cards, style={"display": "flex", "flexWrap": "wrap", "gap": "0.5rem"})