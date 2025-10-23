from __future__ import annotations
# Alpaca WebSocket streaming support for Paper Mode
import asyncio
import threading
from queue import Queue
try:
    from alpaca.trading.stream import TradingStream
except Exception:
    TradingStream = None
# cockpit/dashboard.py
import argparse
from pathlib import Path
from functools import lru_cache

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import numpy as np
import dash
from dash import dcc, html, Input, Output, State
import plotly.graph_objects as go

from dash import dash_table

try:
    from cockpit.metrics import PerformanceMetrics  # repo-local
except Exception:  # pragma: no cover
    try:
        from metrics import PerformanceMetrics  # project root fallback
    except Exception:
        PerformanceMetrics = None  # dashboard will use CSV fallback


# Alpaca benchmark fetch (graceful if unavailable/offline)
import os
try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
except Exception:
    StockHistoricalDataClient = None
    StockBarsRequest = None
    TimeFrame = None

# Load Alpaca keys from environment variables
ALPACA_API_KEY = os.environ.get("APCA_API_KEY_ID", "")
ALPACA_API_SECRET = os.environ.get("APCA_API_SECRET_KEY", "")


# ---------------------------- DataManager (Unified Data Layer) ---------------------------- #
class DataManager:
    """
    Unified data loader for backtest, paper, and benchmark data.
    """
    def __init__(self):
        self.metrics_cls = PerformanceMetrics
        self.base_paths = {
            "backtest": {
                "snapshots": "data/trade_logs/portfolio_snapshots.csv",
                "trades": "data/trade_logs/trades.csv",
                "positions": "data/trade_logs/positions.csv",
            },
            "paper": {
                "snapshots": "data/trade_logs/paper/portfolio_snapshots.csv",
                "trades": "data/trade_logs/paper/trades.csv",
                "positions": "data/trade_logs/paper/positions.csv",
            },
            "benchmark": {},
        }

    def get_equity_curve(self, mode: str):
        """
        Returns a DataFrame with columns ['timestamp', 'equity'] for the given mode.
        In paper mode, attempts Alpaca API `/v2/account/portfolio/history`.
        """
        if mode == "paper":
            # Try to fetch from Alpaca API (if available)
            try:
                import requests
                import json
                headers = {
                    "APCA-API-KEY-ID": ALPACA_API_KEY,
                    "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
                }
                url = "https://paper-api.alpaca.markets/v2/account/portfolio/history"
                params = {
                    "period": "1M",  # 1 month; can expand to 'all' if needed
                    "timeframe": "1D",
                    "extended_hours": "false",
                }
                resp = requests.get(url, headers=headers, params=params, timeout=6)
                if resp.status_code == 200:
                    data = resp.json()
                    if "equity" in data and "timestamp" in data:
                        ts = [pd.to_datetime(t, unit="s") for t in data["timestamp"]]
                        eq = data["equity"]
                        df = pd.DataFrame({"timestamp": ts, "equity": eq})
                        df = df.dropna(subset=["timestamp", "equity"])
                        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
                        return df
            except Exception:
                pass
        # Fallback: load from CSV
        path = self.base_paths.get(mode, {}).get("snapshots")
        if path:
            df = safe_read_csv(path)
            if not df.empty and "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.tz_localize(None)
            return df
        return pd.DataFrame()

    def get_trades(self, mode: str):
        """
        Returns trades DataFrame for the given mode.
        """
        path = self.base_paths.get(mode, {}).get("trades")
        if path:
            df = safe_read_csv(path)
            if not df.empty and "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.tz_localize(None)
            return df
        return pd.DataFrame()

    def get_positions(self, mode: str):
        """
        Returns positions DataFrame for the given mode.
        """
        path = self.base_paths.get(mode, {}).get("positions")
        if path:
            df = safe_read_csv(path)
            if not df.empty and "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.tz_localize(None)
            return df
        return pd.DataFrame()

    def get_benchmark(self, symbol: str, start, end):
        """
        Loads benchmark index for given symbol and date range.
        """
        return load_benchmark(symbol, start, end)


# ---------------- Alpaca WebSocket Stream Manager ---------------- #
class AlpacaStreamManager:
    """
    Handles live Alpaca WebSocket streaming for paper account updates.
    Pushes account equity and position data into a thread-safe queue.
    """
    def __init__(self, api_key: str, api_secret: str, paper: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper = paper
        self.queue = Queue()
        self.thread = None
        self.running = False
        self.stream = None

    def start(self):
        if TradingStream is None:
            print("[WS] Alpaca TradingStream unavailable (alpaca-py missing or outdated).")
            return
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.stream:
            try:
                asyncio.run_coroutine_threadsafe(self.stream.stop(), asyncio.get_event_loop())
            except Exception:
                pass

    def _run_loop(self):
        asyncio.run(self._main())

    async def _main(self):
        try:
            if TradingStream is None:
                print("[WS] Alpaca TradingStream unavailable (alpaca-py missing or outdated).")
                return
            self.stream = TradingStream(self.api_key, self.api_secret, paper=self.paper)
            print("[WS] Connecting to Alpaca TradingStream...")

            async def on_account(data):
                self.queue.put({"type": "account", "data": data})
            async def on_trade(data):
                self.queue.put({"type": "trade", "data": data})

            self.stream.subscribe_trade_updates(on_trade)
            self.stream.subscribe_account_updates(on_account)
            await self.stream.run()
        except Exception as e:
            print(f"[WS] Stream error: {e}")


# ---------------------------- Utilities ---------------------------- #

def safe_read_csv(path: str | Path, parse_ts: bool = True) -> pd.DataFrame:
    """
    Load CSV if present; return empty DataFrame on any issue.
    Ensures timestamp column is parsed and sorted if present.
    """
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            return pd.DataFrame()
        df = pd.read_csv(p)
        if parse_ts and "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df
    except Exception:
        return pd.DataFrame()


def compute_trade_pnl_fifo(trades: pd.DataFrame) -> pd.DataFrame:
    """
    FIFO realized PnL matcher supporting long/short, exits, and flips.
    Leaves open legs with NaN PnL. Commission is not netted here (to keep parity
    with logger snapshots); can be added later if desired.
    """
    if trades is None or trades.empty:
        return pd.DataFrame(columns=["timestamp", "ticker", "side", "qty", "fill_price", "commission", "pnl", "edge"])

    df = trades.copy()

    # Normalize core types
    for col in ("qty", "fill_price", "commission"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "commission" not in df.columns:
        df["commission"] = 0.0

    # Ensure edge column for attribution charts
    if "edge" not in df.columns:
        df["edge"] = "Unknown"

    # Ensure timestamp order per ticker
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values(["ticker", "timestamp"])
    if "pnl" not in df.columns:
        df["pnl"] = np.nan

    stacks: dict[str, list[dict]] = {}

    def sign_for(side: str) -> int:
        s = str(side).lower()
        return +1 if s == "long" else (-1 if s == "short" else 0)

    def closes_position(prev_sign: int, now_side: str) -> bool:
        s = str(now_side).lower()
        if s in ("exit", "cover"):
            return True
        now_sign = sign_for(s)
        return prev_sign != 0 and now_sign != 0 and np.sign(prev_sign) != np.sign(now_sign)

    for tkr, tdf in df.groupby("ticker", sort=False):
        stack = stacks.setdefault(tkr, [])  # elements: {"sign": +1/-1, "price": float, "qty": int}

        def current_net_sign() -> int:
            if not stack:
                return 0
            net = sum(leg["sign"] * leg["qty"] for leg in stack)
            return int(np.sign(net)) if net != 0 else 0

        prev_net_sign = 0
        for idx, row in tdf.iterrows():
            side = str(row.get("side", "")).lower()
            qty = int(row.get("qty", 0))
            px = float(row.get("fill_price", np.nan))
            if qty <= 0 or not np.isfinite(px):
                continue

            if side in ("long", "short"):
                now_sign = sign_for(side)
                if prev_net_sign == 0 or prev_net_sign == now_sign:
                    stack.append({"sign": now_sign, "price": px, "qty": qty})
                else:
                    # flip: close FIFO then open remainder
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
                # exit or cover: close against FIFO until qty is consumed
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


def timeframe_filter(df: pd.DataFrame, tf_value: str) -> pd.DataFrame:
    """Filter dataframe by timeframe code ('all', '1y', '6m', '3m', '1m')."""
    if df is None or df.empty:
        return df
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
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


def summarize_period(df_snap: pd.DataFrame, df_trades: pd.DataFrame) -> dict:
    """
    Summary with sane caps and NaN-aware calculations.
    Max Drawdown is capped to [-100%, 0%]; Win Rate computed only on realized rows.
    """
    if df_snap is None or df_snap.empty:
        return {
            "Starting Equity": "-",
            "Ending Equity": "-",
            "Net Profit": "-",
            "Total Return (%)": "-",
            "CAGR (%)": "-",
            "Max Drawdown (%)": "-",
            "Sharpe Ratio": "-",
            "Volatility (%)": "-",
            "Win Rate (%)": "-",
        }

    start_eq = float(df_snap["equity"].iloc[0])
    end_eq = float(df_snap["equity"].iloc[-1])

    total_ret = np.nan if start_eq <= 0 else (end_eq - start_eq) / start_eq
    days = (df_snap["timestamp"].iloc[-1] - df_snap["timestamp"].iloc[0]).days
    cagr = (1 + total_ret) ** (365.0 / days) - 1 if (days > 0 and not np.isnan(total_ret)) else np.nan

    roll_max = df_snap["equity"].cummax()
    dd = (df_snap["equity"] - roll_max) / roll_max
    dd = dd.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=-1, upper=0)
    max_dd = dd.min() * 100.0

    rets = (
        df_snap["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        if "equity" in df_snap.columns else pd.Series(dtype=float)
    )
    vol = rets.std() * np.sqrt(252) * 100.0 if not rets.empty else np.nan
    sharpe = (rets.mean() / rets.std()) * np.sqrt(252) if (not rets.empty and rets.std() > 0) else np.nan

    win_rate = np.nan
    if df_trades is not None and not df_trades.empty and "pnl" in df_trades.columns:
        realized = df_trades.dropna(subset=["pnl"])
        if not realized.empty:
            win_rate = 100.0 * (realized["pnl"] > 0).sum() / len(realized)

    return {
        "Starting Equity": round(start_eq, 2),
        "Ending Equity": round(end_eq, 2),
        "Net Profit": round(end_eq - start_eq, 2),
        "Total Return (%)": None if np.isnan(total_ret) else round(total_ret * 100.0, 2),
        "CAGR (%)": None if np.isnan(cagr) else round(cagr * 100.0, 2),
        "Max Drawdown (%)": None if np.isnan(max_dd) else round(max_dd, 2),
        "Sharpe Ratio": None if np.isnan(sharpe) else round(sharpe, 3),
        "Volatility (%)": None if np.isnan(vol) else round(vol, 2),
        "Win Rate (%)": None if np.isnan(win_rate) else round(win_rate, 2),
    }


# ---------------------------- KPI Cards Helper ---------------------------- #
def _summary_kpi_cards(summary: dict):
    """
    Render summary dict as a row of KPI cards with dark theme.
    """
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
        "Starting Equity",
        "Ending Equity",
        "Net Profit",
        "Total Return (%)",
        "CAGR (%)",
        "Sharpe Ratio",
        "Max Drawdown (%)",
        "Volatility (%)",
        "Win Rate (%)",
    ]
    def fmt(val, k):
        if val == "-" or val is None:
            return "-"
        if "Return" in k or "Drawdown" in k or "Volatility" in k or "CAGR" in k or "Win Rate" in k:
            return f"{val:.2f}%"
        if "Sharpe" in k:
            return f"{val:.3f}"
        return f"${val:,.2f}" if isinstance(val, (int, float)) else str(val)
    cards = []
    for k in kpi_order:
        v = summary.get(k, "-")
        cards.append(
            html.Div(
                [
                    html.Div(str(k), style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                    html.Div(fmt(v, k), style={"fontSize": "22px", "fontWeight": 600}),
                ],
                style=card_style,
            )
        )
    return html.Div(cards, style={"display": "flex", "flexWrap": "wrap", "gap": "0.5rem"})


# ------- Benchmark loader (cached) ------- #


@lru_cache(maxsize=8)
def load_benchmark(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """
    Download benchmark (e.g., SPY) between start/end using Alpaca API.
    Returns empty DF on any failure or if Alpaca unavailable.
    """
    # Only support SPY and QQQ and BTC-USD for now
    symbol_map = {
        "^GSPC": "SPY",
        "^NDX": "QQQ",
        "BTC-USD": "BTC-USD",
    }
    alpaca_symbol = symbol_map.get(symbol, symbol)
    if StockHistoricalDataClient is None or StockBarsRequest is None or TimeFrame is None:
        return pd.DataFrame()
    if not ALPACA_API_KEY or not ALPACA_API_SECRET:
        return pd.DataFrame()
    try:
        client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
        req = StockBarsRequest(
            symbol_or_symbols=[alpaca_symbol],
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )
        bars = client.get_stock_bars(req)
        df = bars.df
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            # Alpaca returns columns like ('SPY', 'close'), ('SPY', 'timestamp'), etc.
            # Collapse to single symbol if only one symbol requested
            df = df[alpaca_symbol]
        df = df.reset_index()
        if "timestamp" not in df.columns:
            df["timestamp"] = pd.to_datetime(df["t"], errors="coerce")
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.tz_localize(None)
        px = pd.to_numeric(df["close"], errors="coerce")
        if px.isna().all():
            return pd.DataFrame()
        df["index"] = 100.0 * (px / px.iloc[0])
        return df[["timestamp", "index"]]
    except Exception:
        return pd.DataFrame()


# ---------------------------- App Runner ---------------------------- #

def run_dashboard(live: bool = False,
                  snapshots_csv: str = "data/trade_logs/portfolio_snapshots.csv",
                  trades_csv: str = "data/trade_logs/trades.csv"):

    # Prefer PerformanceMetrics loader; fall back to direct CSVs
    use_metrics_loader = PerformanceMetrics is not None
    if use_metrics_loader:
        try:
            metrics = PerformanceMetrics(snapshots_path=snapshots_csv, trades_path=trades_csv)
            base_snapshots = metrics.snapshots.copy()
            base_trades = metrics.trades.copy() if metrics.trades is not None else pd.DataFrame()
        except Exception as e:
            print(f"[DASH] Falling back to direct CSV load: {e}")
            use_metrics_loader = False
            base_snapshots = safe_read_csv(snapshots_csv)
            base_trades = safe_read_csv(trades_csv)
    else:
        base_snapshots = safe_read_csv(snapshots_csv)
        base_trades = safe_read_csv(trades_csv)

    def reload_frames():
        """Reload frames from disk (for live mode)."""
        if use_metrics_loader:
            try:
                m = PerformanceMetrics(snapshots_path=snapshots_csv, trades_path=trades_csv)
                snaps = m.snapshots.copy()
                trs = m.trades.copy() if m.trades is not None else pd.DataFrame()
                return snaps, trs
            except Exception:
                pass
        return safe_read_csv(snapshots_csv), safe_read_csv(trades_csv)

    app = dash.Dash(
        __name__,
        suppress_callback_exceptions=True,
        prevent_initial_callbacks="initial_duplicate",  # optional safeguard
    )
    app.config.suppress_callback_exceptions = True
    app.title = "Trading Cockpit"

    # ---------------------------- Layout ---------------------------- #
    app.layout = html.Div(
        style={"backgroundColor": "#123", "color": "#EEE", "padding": "18px"},
        children=[
            html.H1("Trading Dashboard", style={"textAlign": "center"}),
            dcc.Store(id="mode_state", data="backtest"),
            dcc.Tabs(
                id="tabs",
                value="tab-mode",
                parent_style={"color": "#000"},
                children=[
                    dcc.Tab(label="Mode", value="tab-mode", selected_style={"background": "#222"}),
                    dcc.Tab(label="Dashboard", value="tab-dashboard", selected_style={"background": "#222"}),
                    dcc.Tab(label="Performance", value="tab-performance", selected_style={"background": "#222"}),
                    dcc.Tab(label="Analytics", value="tab-analytics", selected_style={"background": "#222"}),
                    dcc.Tab(label="Governor", value="tab-governor", selected_style={"background": "#222"}),
                    dcc.Tab(label="Intel", value="tab-intel", selected_style={"background": "#222"}),
                    dcc.Tab(label="Settings", value="tab-settings", selected_style={"background": "#222"}),
                ],
            ),
            html.Div(id="tab-content"),
            dcc.Interval(id="pulse", interval=2000, n_intervals=0, disabled=not live),
        ],
    )

    # ---------------------------- Tab Content ---------------------------- #
    @app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"),
    )
    def render_tab(tab_value):
        if tab_value == "tab-mode":
            return _mode_layout()
        elif tab_value == "tab-dashboard":
            return _dashboard_layout()
        elif tab_value == "tab-performance":
            return _performance_layout()
        elif tab_value == "tab-analytics":
            return _analytics_layout()
        elif tab_value == "tab-governor":
            return _governor_layout()
        elif tab_value == "tab-intel":
            from intelligence.news_summarizer import NewsSummarizer
            ns = NewsSummarizer()
            summary_text = ns.summarize()
            return html.Pre(
                summary_text,
                style={
                    "whiteSpace": "pre-wrap",
                    "fontSize": "17px",
                    "fontFamily": "Menlo, Consolas, monospace",
                    "padding": "30px",
                    "backgroundColor": "#0c0c0c",
                    "color": "#e0e0e0",
                    "borderRadius": "10px",
                    "border": "1px solid #333",
                    "lineHeight": "1.7",
                },
            )
        else:
            return _settings_layout()
    # ---------- Performance tab (NEW) ---------- #
    def _performance_layout():
        return html.Div(
            style={"backgroundColor": "#161b22", "padding": "20px", "borderRadius": "12px"},
            children=[
                html.H3("Performance Overview", style={"marginTop": 0, "color": "#e0e0e0"}),
                html.Div(
                    [
                        html.Label("Timeframe", style={"color": "#ddd", "marginRight": "8px"}),
                        dcc.Dropdown(
                            id="timeframe_performance",
                            options=[
                                {"label": "All", "value": "all"},
                                {"label": "1Y", "value": "1y"},
                                {"label": "6M", "value": "6m"},
                                {"label": "3M", "value": "3m"},
                                {"label": "1M", "value": "1m"},
                            ],
                            value="all",
                            clearable=False,
                            style={"width": 220, "color": "#000"},
                        ),
                    ],
                    style={"marginBottom": "14px"},
                ),
                html.Div([
                    dcc.Graph(id="rolling_sharpe_chart", style={"height": "320px"}),
                ], style={"margin": "12px 0"}),
                html.Div([
                    dcc.Graph(id="rolling_maxdd_chart", style={"height": "320px"}),
                ], style={"margin": "12px 0"}),
                html.Div([
                    dcc.Graph(id="pnl_decomp_chart", style={"height": "320px"}),
                ], style={"margin": "12px 0"}),
                html.Div([
                    dcc.Graph(id="edge_corr_heatmap", style={"height": "320px"}),
                ], style={"margin": "12px 0"}),
                html.Div([
                    dcc.Graph(id="edge_weight_evolution_chart", style={"height": "320px"}),
                ], style={"margin": "12px 0"}),
            ]
        )
        # ---------- Mode tab ---------- #
    def _mode_layout():
        return html.Div(
            # full-width/height feel with dark gradient and centered content
            style={
                "minHeight": "78vh",
                "background": "linear-gradient(180deg,#121212,#101010,#0c0c0c)",
                "borderRadius": "12px",
                "padding": "28px 28px 40px 28px",
                "boxShadow": "0 0 12px rgba(0,0,0,0.55)",
            },
            children=[
                html.Div(
                    style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "alignItems": "flex-start",
                        "gap": "24px",
                        "flexWrap": "wrap",
                    },
                    children=[
                        # Left: mode controls card
                        html.Div(
                            style={
                                "flex": "0 0 320px",
                                "backgroundColor": "#171717",
                                "border": "1px solid #2a2a2a",
                                "borderRadius": "10px",
                                "padding": "18px 20px",
                            },
                            children=[
                                html.H3("Select Trading Mode", style={"marginTop": 0}),
                                dcc.RadioItems(
                                    id="mode_selector_radio",
                                    options=[
                                        {"label": "Backtest", "value": "backtest"},
                                        {"label": "Paper Trading", "value": "paper"},
                                    ],
                                    value="backtest",
                                    labelStyle={"display": "block", "margin": "10px 0"},
                                    style={"fontSize": "16px"},
                                ),
                                html.Button(
                                    "INITIATE LIVE",
                                    id="go_live_button",
                                    n_clicks=0,
                                    style={
                                        "backgroundColor": "red",
                                        "color": "white",
                                        "padding": "10px 20px",
                                        "border": "none",
                                        "cursor": "not-allowed",
                                        "opacity": 0.6,
                                        "marginTop": "10px",
                                    },
                                    disabled=True,
                                ),
                                html.Div(id="mode_status", style={"marginTop": "12px", "fontSize": "16px"}),
                            ],
                        ),
                        # Right: performance summary card (mode-aware)
                        html.Div(
                            id="mode_summary_box",
                            style={
                                "flex": "1 1 480px",
                                "minWidth": "420px",
                                "backgroundColor": "#171717",
                                "border": "1px solid #2a2a2a",
                                "borderRadius": "10px",
                                "padding": "18px 22px",
                            },
                        ),
                    ],
                ),
            ],
        )
    # ---- Mode selector (radio) updates global mode_state ----
    @app.callback(
        Output("mode_state", "data"),
        Input("mode_selector_radio", "value"),
        prevent_initial_call=False,
    )
    def update_mode_state(selected_mode):
        return selected_mode

    # ---- Mode status display uses global mode_state ----
    @app.callback(
        Output("mode_status", "children"),
        Input("mode_state", "data"),
        prevent_initial_call=False,
    )
    def update_mode(mode_value):
        return f"Active Mode: {mode_value.capitalize()}"

    # New: mode-aware summary content inside the Mode tab (uses mode_state)
    @app.callback(
        Output("mode_summary_box", "children"),
        Input("mode_state", "data"),
        prevent_initial_call=False,
    )
    def _update_mode_summary(mode_value):
        if mode_value == "paper":
            try:
                from alpaca.trading.client import TradingClient
                from alpaca.trading.requests import GetAssetsRequest
            except Exception:
                TradingClient = None
            if TradingClient is None or not ALPACA_API_KEY or not ALPACA_API_SECRET:
                print("[PAPER] Alpaca TradingClient unavailable or keys missing.")
                return html.Div(
                    [
                        html.H3("(Paper) Account Summary", style={"marginTop": 0}),
                        html.Div("No paper account connected.", style={"color": "#ffb300", "fontSize": "22px", "padding": "18px 0"}),
                    ],
                    style={
                        "backgroundColor": "#1b1b1b",
                        "padding": "18px 20px",
                        "borderRadius": "8px",
                        "boxShadow": "0 0 8px rgba(0,0,0,0.5)",
                    },
                )
            try:
                client = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=True)
                account = client.get_account()
                positions = client.get_all_positions()
                print("[PAPER] Connected to Alpaca paper account")
                # Defensive: check for required account keys
                equity = float(getattr(account, "equity", None) or 0)
                buying_power = float(getattr(account, "buying_power", None) or 0)
                cash = float(getattr(account, "cash", None) or 0)
                unrealized_pl = float(getattr(account, "unrealized_pl", None) or 0)
                # Render KPIs for equity, buying power, cash, unrealized PnL
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
                def fmt(val, prefix="$"):
                    try:
                        return f"{prefix}{float(val):,.2f}"
                    except Exception:
                        return "-"
                kpis = [
                    html.Div([html.Div("Equity", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                              html.Div(fmt(equity), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                    html.Div([html.Div("Buying Power", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                              html.Div(fmt(buying_power), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                    html.Div([html.Div("Cash", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                              html.Div(fmt(cash), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                    html.Div([html.Div("Unrealized PnL", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                              html.Div(fmt(unrealized_pl), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                ]
                # List open positions
                pos_list = []
                if positions:
                    for pos in positions:
                        try:
                            symbol = getattr(pos, "symbol", "-")
                            qty = getattr(pos, "qty", "-")
                            unreal = getattr(pos, "unrealized_pl", "-")
                            side = getattr(pos, "side", "-")
                            pos_list.append(f"{symbol} ({side}) | Qty: {qty} | Unr. PnL: ${float(unreal):,.2f}")
                        except Exception:
                            continue
                return html.Div(
                    [
                        html.H3("(Paper) Account Summary", style={"marginTop": 0}),
                        html.Div(kpis, style={"display": "flex", "flexWrap": "wrap", "gap": "0.5rem", "marginBottom": "10px"}),
                        html.Div(
                            [
                                html.Div("Open Positions:", style={"fontWeight": 600, "fontSize": "16px", "marginBottom": "4px"}),
                                html.Div("\n".join(pos_list) if pos_list else "No open positions.", style={"whiteSpace": "pre-line", "fontSize": "15px"}),
                            ],
                            style={"backgroundColor": "#181c22", "padding": "10px 12px", "borderRadius": "8px", "marginTop": "8px"},
                        ),
                    ],
                    style={
                        "backgroundColor": "#1b1b1b",
                        "padding": "18px 20px",
                        "borderRadius": "8px",
                        "boxShadow": "0 0 8px rgba(0,0,0,0.5)",
                    },
                )
            except Exception as e:
                print(f"[PAPER] Paper account connection failed: {e}")
                return html.Div(
                    [
                        html.H3("(Paper) Account Summary", style={"marginTop": 0}),
                        html.Div("No paper account connected.", style={"color": "#ffb300", "fontSize": "22px", "padding": "18px 0"}),
                    ],
                    style={
                        "backgroundColor": "#1b1b1b",
                        "padding": "18px 20px",
                        "borderRadius": "8px",
                        "boxShadow": "0 0 8px rgba(0,0,0,0.5)",
                    },
                )
        # --- Default: Backtest mode as before ---
        snapshots_path = f"data/trade_logs/{mode_value}/portfolio_snapshots.csv"
        trades_path = f"data/trade_logs/{mode_value}/trades.csv"
        default_snapshots = "data/trade_logs/portfolio_snapshots.csv"
        default_trades = "data/trade_logs/trades.csv"
        def file_exists(path):
            return Path(path).exists() and Path(path).stat().st_size > 0
        if not file_exists(snapshots_path):
            snapshots_path = default_snapshots
        if not file_exists(trades_path):
            trades_path = default_trades
        # load frames (use PerformanceMetrics if available, else direct CSVs)
        if PerformanceMetrics is not None:
            try:
                m = PerformanceMetrics(snapshots_path=snapshots_path, trades_path=trades_path)
                df_snap = m.snapshots.copy()
                df_tr = m.trades.copy() if m.trades is not None else pd.DataFrame()
            except Exception:
                df_snap = safe_read_csv(snapshots_path)
                df_tr = safe_read_csv(trades_path)
        else:
            df_snap = safe_read_csv(snapshots_path)
            df_tr = safe_read_csv(trades_path)
        # Ensure FIFO PnL exists when needed (for Win Rate correctness)
        if df_tr is not None and not df_tr.empty:
            if ("pnl" not in df_tr.columns) or (df_tr["pnl"].isna().all()):
                df_tr = compute_trade_pnl_fifo(df_tr)
        summary = summarize_period(df_snap, df_tr)
        return html.Div(
            [
                html.H3(f"({mode_value.capitalize()}) Performance Summary", style={"marginTop": 0}),
                html.Div(_summary_kpi_cards(summary)),
            ],
            style={
                "backgroundColor": "#1b1b1b",
                "padding": "18px 20px",
                "borderRadius": "8px",
                "boxShadow": "0 0 8px rgba(0,0,0,0.5)",
            },
        )

    # ---------- Dashboard tab components ---------- #
    def _dashboard_layout():
        return html.Div(
            style={"backgroundColor": "#161b22", "padding": "16px 18px", "borderRadius": "12px"},
            children=[
                # --- Mode summary row (global mode label + top-level indicator) ---
                html.Div(
                    [
                        html.H4(id="mode_label", style={"margin": "0 0 6px 0"}),
                        html.Div(id="mode_top_indicator", style={"fontSize": "18px", "fontWeight": "bold", "marginLeft": "10px", "display": "inline-block"}),
                    ],
                    style={"margin": "0 0 10px 0", "padding": "8px 12px", "background": "#171717", "border": "1px solid #222", "borderRadius": "8px", "display": "flex", "alignItems": "center"},
                ),
                # --- Performance summary and controls row ---
                html.Div(
                    [
                        html.Div(
                            [
                                html.H4("Performance Summary"),
                                html.Div(id="summary_box"),
                                html.Br(),
                                html.Div(
                                    style={"display": "flex", "alignItems": "center", "gap": "10px"},
                                    children=[
                                        html.Label("Timeframe", style={"marginBottom": 0}),
                                        dcc.Dropdown(
                                            id="timeframe",
                                            options=[
                                                {"label": "All", "value": "all"},
                                                {"label": "1Y", "value": "1y"},
                                                {"label": "6M", "value": "6m"},
                                                {"label": "3M", "value": "3m"},
                                                {"label": "1M", "value": "1m"},
                                            ],
                                            value="all",
                                            clearable=False,
                                            style={"width": 120, "color": "#000", "marginRight": "10px"},
                                        ),
                                        html.Button(
                                            "Refresh Data",
                                            id="refresh_button",
                                            n_clicks=0,
                                            style={
                                                "backgroundColor": "#2d8cff",
                                                "color": "#fff",
                                                "padding": "5px 18px",
                                                "border": "none",
                                                "borderRadius": "5px",
                                                "fontSize": "15px",
                                                "fontWeight": "bold",
                                                "boxShadow": "0 1px 4px #0003",
                                                "cursor": "pointer",
                                            },
                                        ),
                                    ],
                                ),
                            ],
                            style={
                                "width": "32%",
                                "display": "inline-block",
                                "verticalAlign": "top",
                                "backgroundColor": "#1b1b1b",
                                "borderRadius": "10px",
                                "border": "1px solid #232323",
                                "padding": "18px 18px 10px 18px",
                                "boxShadow": "0 0 8px #0004",
                                "minHeight": "320px",
                            },
                        ),
                        html.Div(
                            [dcc.Graph(id="equity_chart")],
                            style={
                                "width": "66%",
                                "display": "inline-block",
                                "backgroundColor": "#1b1b1b",
                                "borderRadius": "10px",
                                "border": "1px solid #232323",
                                "padding": "12px 8px 10px 8px",
                                "boxShadow": "0 0 8px #0004",
                                "minHeight": "320px",
                                "verticalAlign": "top",
                            },
                        ),
                    ],
                    style={"margin": "12px 0", "display": "flex", "gap": "18px"},
                ),
                html.Div([dcc.Graph(id="drawdown_chart")], style={"margin": "12px 0", "backgroundColor": "#1b1b1b", "borderRadius": "10px", "padding": "10px 8px", "boxShadow": "0 0 8px #0004"}),
                html.H4("Profit / Loss by Edge"),
                html.Div([dcc.Graph(id="edge_pnl_chart")], style={"margin": "12px 0", "backgroundColor": "#1b1b1b", "borderRadius": "10px", "padding": "10px 8px", "boxShadow": "0 0 8px #0004"}),
                html.H4("Recent Trades"),
                html.Pre(id="recent_trades_box", style={"backgroundColor": "#181818", "borderRadius": "8px", "padding": "12px", "fontSize": "14px", "color": "#e0e0e0", "border": "1px solid #232323"}),
            ]
        )

    # ---------- Analytics tab components ---------- #
    def _analytics_layout():
        return html.Div(
            children=[
                html.Div(
                    [
                        html.Label("Timeframe"),
                        dcc.Dropdown(
                            id="timeframe_analytics",
                            options=[
                                {"label": "All", "value": "all"},
                                {"label": "1Y", "value": "1y"},
                                {"label": "6M", "value": "6m"},
                                {"label": "3M", "value": "3m"},
                                {"label": "1M", "value": "1m"},
                            ],
                            value="all",
                            clearable=False,
                            style={"width": 220, "color": "#000"},
                        ),
                        html.Br(),
                        html.Label("Benchmark"),
                        dcc.Dropdown(
                            id="benchmark_selector",
                            options=[
                                {"label": "S&P 500 (^GSPC)", "value": "^GSPC"},
                                {"label": "NASDAQ 100 (^NDX)", "value": "^NDX"},
                                {"label": "Bitcoin (BTC-USD)", "value": "BTC-USD"},
                            ],
                            value="^GSPC",
                            clearable=False,
                            style={"width": 240, "color": "#000"},
                        ),
                    ],
                    style={"margin": "6px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="edge_cum_pnl_chart"),  # Cumulative PnL by Edge Over Time
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="equity_vs_bench_chart"),  # Equity vs SPY / S&P
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="rolling_outperformance_chart"),  # Rolling Outperformance vs Benchmark
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="pnl_heatmap_chart"),  # Daily PnL Heatmap
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        html.H4("Interactive Playback (coming soon)"),
                        html.Div("A timeline slider to step through trades & equity."),
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        html.H4("Trades Table"),
                        dash_table.DataTable(
                            id="trades_table",
                            data=[],
                            columns=[],
                            page_size=15,
                            sort_action="native",
                            filter_action="native",
                            row_deletable=False,
                            style_table={"overflowX": "auto", "border": "1px solid #333"},
                            style_cell={
                                "backgroundColor": "#0f1116",
                                "color": "#e0e0e0",
                                "border": "1px solid #222",
                                "fontFamily": "Menlo, Consolas, monospace",
                                "fontSize": "12px",
                                "padding": "6px",
                            },
                            style_header={
                                "backgroundColor": "#171a21",
                                "fontWeight": "bold",
                                "border": "1px solid #333",
                            },
                            style_data_conditional=[
                                {
                                    "if": {"filter_query": "{pnl} > 0"},
                                    "backgroundColor": "#0f1b12",
                                    "color": "#a8ff9e",
                                },
                                {
                                    "if": {"filter_query": "{pnl} < 0"},
                                    "backgroundColor": "#231214",
                                    "color": "#ff9ea8",
                                },
                            ],
                        ),
                    ],
                    style={"margin": "12px 0"},
                ),
            ],
            style={"padding": "16px", "backgroundColor": "#161b22", "borderRadius": "12px"},
        )

    # ---------- Governor tab components ---------- #
    def _governor_layout():
        return html.Div(
            style={"backgroundColor": "#161b22", "padding": "16px 18px", "borderRadius": "12px"},
            children=[
                html.H3("Governor Intelligence", style={"marginTop": 0, "color": "#e0e0e0"}),
                html.Div([
                    dcc.Graph(id="gov_weight_chart"),
                ], style={"margin": "12px 0"}),
                html.Div([
                    dcc.Graph(id="gov_sr_weight_scatter"),
                ], style={"margin": "12px 0"}),
                html.Div([
                    dcc.Graph(id="gov_recommendation_chart"),
                ], style={"margin": "12px 0"}),
                html.Div([
                    dcc.Graph(id="gov_weight_evolution"),
                ], style={"margin": "12px 0"}),
            ]
        )
        return html.Div(
            children=[
                html.Div(
                    [
                        html.Label("Timeframe"),
                        dcc.Dropdown(
                            id="timeframe_analytics",
                            options=[
                                {"label": "All", "value": "all"},
                                {"label": "1Y", "value": "1y"},
                                {"label": "6M", "value": "6m"},
                                {"label": "3M", "value": "3m"},
                                {"label": "1M", "value": "1m"},
                            ],
                            value="all",
                            clearable=False,
                            style={"width": 220, "color": "#000"},
                        ),
                        html.Br(),
                        html.Label("Benchmark"),
                        dcc.Dropdown(
                            id="benchmark_selector",
                            options=[
                                {"label": "S&P 500 (^GSPC)", "value": "^GSPC"},
                                {"label": "NASDAQ 100 (^NDX)", "value": "^NDX"},
                                {"label": "Bitcoin (BTC-USD)", "value": "BTC-USD"},
                            ],
                            value="^GSPC",
                            clearable=False,
                            style={"width": 240, "color": "#000"},
                        ),
                    ],
                    style={"margin": "6px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="edge_cum_pnl_chart"),     # Cumulative PnL by Edge Over Time
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="equity_vs_bench_chart"),  # Equity vs SPY / S&P
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="rolling_outperformance_chart"),  # Rolling Outperformance vs Benchmark
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="pnl_heatmap_chart"),  # Daily PnL Heatmap
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        html.H4("Interactive Playback (coming soon)"),
                        html.Div("A timeline slider to step through trades & equity."),
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        html.H4("Trades Table"),
                        dash_table.DataTable(
                            id="trades_table",
                            data=[],
                            columns=[],
                            page_size=15,
                            sort_action="native",
                            filter_action="native",
                            row_deletable=False,
                            style_table={"overflowX": "auto", "border": "1px solid #333"},
                            style_cell={
                                "backgroundColor": "#0f1116",
                                "color": "#e0e0e0",
                                "border": "1px solid #222",
                                "fontFamily": "Menlo, Consolas, monospace",
                                "fontSize": "12px",
                                "padding": "6px",
                            },
                            style_header={
                                "backgroundColor": "#171a21",
                                "fontWeight": "bold",
                                "border": "1px solid #333",
                            },
                            style_data_conditional=[
                                {
                                    "if": {"filter_query": "{pnl} > 0"},
                                    "backgroundColor": "#0f1b12",
                                    "color": "#a8ff9e",
                                },
                                {
                                    "if": {"filter_query": "{pnl} < 0"},
                                    "backgroundColor": "#231214",
                                    "color": "#ff9ea8",
                                },
                            ],
                        ),
                    ],
                    style={"margin": "12px 0"},
                ),
            ]
        )

    # ---------- Settings tab (placeholder) ---------- #
    def _settings_layout():
        return html.Div(
            children=[
                html.H3("Settings"),
                html.P("Strategy and dashboard settings will appear here."),
            ]
        )

    # ---------------------------- Dashboard Callbacks ---------------------------- #

    # --- Use DataManager as unified loader ---
    dataman = DataManager()
    # Instantiate Alpaca WebSocket manager for Paper Mode
    alpaca_ws = AlpacaStreamManager(ALPACA_API_KEY, ALPACA_API_SECRET, paper=True)
    alpaca_ws.start()

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
        # Live mode placeholder (unchanged)
        if mode_value == "live":
            empty_fig = go.Figure()
            empty_fig.update_layout(
                template="plotly_dark",
                annotations=[
                    dict(
                        text="LIVE MODE (Coming Soon)",
                        xref="paper", yref="paper", x=0.5, y=0.5,
                        showarrow=False, font=dict(color="orange", size=32)
                    )
                ]
            )
            summary_cards = html.Div(
                [
                    html.Div("⚪ LIVE MODE is not yet enabled.", style={"fontSize": "22px", "color": "orange", "padding": "30px 0", "textAlign": "center"}),
                ]
            )
            recent_txt = "Live trading is not yet enabled."
            return empty_fig, empty_fig, empty_fig, summary_cards, recent_txt

        # PAPER MODE: auto-refresh, fetch equity curve from Alpaca, update KPIs, open positions, save logs
        if mode_value == "paper":
            # Try equity curve from Alpaca portfolio history
            eq_df = dataman.get_equity_curve("paper")
            trades_df = dataman.get_trades("paper")
            positions_df = dataman.get_positions("paper")
            # Save logs if available
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
            # Check for WebSocket messages (real-time updates)
            latest_equity = None
            latest_positions = []
            try:
                while not alpaca_ws.queue.empty():
                    msg = alpaca_ws.queue.get_nowait()
                    if msg["type"] == "account":
                        data = msg["data"]
                        latest_equity = float(data.get("equity", 0)) if isinstance(data, dict) else None
                    elif msg["type"] == "trade":
                        trade_data = msg["data"]
                        if isinstance(trade_data, dict):
                            latest_positions.append(trade_data)
            except Exception:
                pass
            # KPIs from Alpaca
            try:
                from alpaca.trading.client import TradingClient
            except Exception:
                TradingClient = None
            if TradingClient is not None and ALPACA_API_KEY and ALPACA_API_SECRET:
                try:
                    client = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=True)
                    account = client.get_account()
                    positions = client.get_all_positions()
                    # Use WebSocket equity if present
                    equity = latest_equity if latest_equity is not None else float(getattr(account, "equity", None) or 0)
                    buying_power = float(getattr(account, "buying_power", None) or 0)
                    cash = float(getattr(account, "cash", None) or 0)
                    unrealized_pl = float(getattr(account, "unrealized_pl", None) or 0)
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
                    def fmt(val, prefix="$"):
                        try:
                            return f"{prefix}{float(val):,.2f}"
                        except Exception:
                            return "-"
                    kpis = [
                        html.Div([html.Div("Equity", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                                  html.Div(fmt(equity), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                        html.Div([html.Div("Buying Power", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                                  html.Div(fmt(buying_power), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                        html.Div([html.Div("Cash", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                                  html.Div(fmt(cash), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                        html.Div([html.Div("Unrealized PnL", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                                  html.Div(fmt(unrealized_pl), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                    ]
                    # Equity chart (real curve if available)
                    eq_fig = go.Figure()
                    if not eq_df.empty:
                        eq_fig.add_trace(
                            go.Scatter(
                                x=eq_df["timestamp"],
                                y=eq_df["equity"],
                                mode="lines+markers",
                                name="Equity",
                                line=dict(color="deepskyblue", width=2),
                            )
                        )
                    else:
                        eq_fig.add_trace(
                            go.Scatter(
                                x=["Now"],
                                y=[equity],
                                mode="markers+text",
                                marker=dict(color="deepskyblue", size=22),
                                name="Equity",
                                text=[f"${equity:,.2f}"],
                                textposition="top center",
                            )
                        )
                    eq_fig.update_layout(
                        title="Account Equity (Paper)",
                        xaxis_title="",
                        yaxis_title="Equity ($)",
                        template="plotly_dark",
                        showlegend=False,
                    )
                    # Drawdown chart (from curve)
                    dd_fig = go.Figure()
                    if not eq_df.empty:
                        roll_max = eq_df["equity"].cummax()
                        drawdown = (eq_df["equity"] - roll_max) / roll_max
                        drawdown = drawdown.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=-1, upper=0)
                        dd_fig.add_trace(
                            go.Scatter(
                                x=eq_df["timestamp"],
                                y=drawdown,
                                fill="tozeroy",
                                mode="lines",
                                name="Drawdown",
                                line=dict(color="firebrick"),
                            )
                        )
                    dd_fig.update_layout(
                        title="Drawdown Over Time",
                        xaxis_title="Date",
                        yaxis_title="Drawdown",
                        yaxis_tickformat=".0%",
                        template="plotly_dark",
                    )
                    # Edge PnL bar
                    edge_fig = go.Figure()
                    if trades_df is not None and not trades_df.empty and {"edge", "pnl"}.issubset(set(trades_df.columns)):
                        pnl_by_edge = (
                            trades_df.groupby("edge", dropna=False)["pnl"]
                            .sum()
                            .sort_values(ascending=False)
                            .reset_index()
                        )
                        if not pnl_by_edge.empty:
                            colors = ["limegreen" if v >= 0 else "firebrick" for v in pnl_by_edge["pnl"]]
                            edge_fig.add_trace(
                                go.Bar(
                                    x=pnl_by_edge["edge"].astype(str),
                                    y=pnl_by_edge["pnl"],
                                    marker_color=colors,
                                    text=[f"${v:,.2f}" for v in pnl_by_edge["pnl"]],
                                    textposition="auto",
                                    name="PnL",
                                )
                            )
                    edge_fig.update_layout(
                        title="Profit / Loss by Edge",
                        xaxis_title="Edge",
                        yaxis_title="PnL ($)",
                        template="plotly_dark",
                    )
                    # Open positions
                    pos_list = []
                    if positions:
                        for pos in positions:
                            try:
                                symbol = getattr(pos, "symbol", "-")
                                qty = getattr(pos, "qty", "-")
                                unreal = getattr(pos, "unrealized_pl", "-")
                                side = getattr(pos, "side", "-")
                                pos_list.append(f"{symbol} ({side}) | Qty: {qty} | Unr. PnL: ${float(unreal):,.2f}")
                            except Exception:
                                continue
                    # Optionally, append latest_positions from WebSocket
                    if latest_positions:
                        pos_list.extend([str(p) for p in latest_positions])
                    recent_txt = "\n".join(pos_list) if pos_list else "No open positions."
                    summary_cards = html.Div([
                        html.Div(kpis, style={"display": "flex", "flexWrap": "wrap", "gap": "0.5rem", "marginBottom": "10px"}),
                    ])
                    return eq_fig, dd_fig, edge_fig, summary_cards, recent_txt
                except Exception as e:
                    print(f"[PAPER] Paper account connection failed: {e}")
            # Fallback if no API
            empty_fig = go.Figure()
            empty_fig.update_layout(
                template="plotly_dark",
                annotations=[dict(
                    text="No paper account connected.",
                    xref="paper", yref="paper", x=0.5, y=0.5,
                    showarrow=False, font=dict(color="orange", size=26)
                )]
            )
            summary_cards = html.Div(
                html.Div("No paper account connected.", style={"color": "#ffb300", "fontSize": "22px", "padding": "18px 0"}),
            )
            return empty_fig, empty_fig, empty_fig, summary_cards, "No paper account connected."

        # BACKTEST mode: as before (use CSVs/metrics)
        snapshots_path = f"data/trade_logs/{mode_value}/portfolio_snapshots.csv"
        trades_path = f"data/trade_logs/{mode_value}/trades.csv"
        default_snapshots = "data/trade_logs/portfolio_snapshots.csv"
        default_trades = "data/trade_logs/trades.csv"
        def file_exists(path):
            return Path(path).exists() and Path(path).stat().st_size > 0
        if not file_exists(snapshots_path):
            snapshots_path = default_snapshots
        if not file_exists(trades_path):
            trades_path = default_trades
        reload_from_disk = True if _refresh_clicks else False
        if not hasattr(update_dashboard, "_last_snapshots"):
            update_dashboard._last_snapshots = None
            update_dashboard._last_trades = None
            update_dashboard._last_mode = None
            update_dashboard._last_tf = None
            update_dashboard._last_refresh_clicks = None
            update_dashboard._last_n_pulse = None
        need_reload = False
        if update_dashboard._last_mode != mode_value or update_dashboard._last_tf != tf_value:
            need_reload = True
        elif update_dashboard._last_refresh_clicks != _refresh_clicks:
            need_reload = True
        if reload_from_disk and need_reload:
            if PerformanceMetrics is not None:
                try:
                    m = PerformanceMetrics(snapshots_path=snapshots_path, trades_path=trades_path)
                    df = m.snapshots.copy()
                    trades = m.trades.copy() if m.trades is not None else pd.DataFrame()
                except Exception:
                    df = safe_read_csv(snapshots_path)
                    trades = safe_read_csv(trades_path)
            else:
                df = safe_read_csv(snapshots_path)
                trades = safe_read_csv(trades_path)
            update_dashboard._last_snapshots = df
            update_dashboard._last_trades = trades
        else:
            df = update_dashboard._last_snapshots
            trades = update_dashboard._last_trades
            if df is None or trades is None:
                if PerformanceMetrics is not None:
                    try:
                        m = PerformanceMetrics(snapshots_path=snapshots_path, trades_path=trades_path)
                        df = m.snapshots.copy()
                        trades = m.trades.copy() if m.trades is not None else pd.DataFrame()
                    except Exception:
                        df = safe_read_csv(snapshots_path)
                        trades = safe_read_csv(trades_path)
                else:
                    df = safe_read_csv(snapshots_path)
                    trades = safe_read_csv(trades_path)
                update_dashboard._last_snapshots = df
                update_dashboard._last_trades = trades
        update_dashboard._last_mode = mode_value
        update_dashboard._last_tf = tf_value
        update_dashboard._last_refresh_clicks = _refresh_clicks
        update_dashboard._last_n_pulse = n_pulse
        # Ensure PnL attribution and types
        if trades is not None and not trades.empty:
            if ("pnl" not in trades.columns) or (trades["pnl"].isna().all()):
                trades = compute_trade_pnl_fifo(trades)
            if "edge" not in trades.columns:
                trades["edge"] = "Unknown"
            for col in ("qty", "fill_price", "pnl"):
                if col in trades.columns:
                    trades[col] = pd.to_numeric(trades[col], errors="coerce")
            trades["timestamp"] = pd.to_datetime(trades["timestamp"], errors="coerce")
            trades = trades.dropna(subset=["timestamp"]).sort_values("timestamp")
        df_tf = timeframe_filter(df, tf_value) if df is not None else pd.DataFrame()
        trades_tf = timeframe_filter(trades, tf_value) if (trades is not None and not trades.empty) else pd.DataFrame()
        summary = summarize_period(df_tf, trades_tf)
        summary_cards = html.Div(_summary_kpi_cards(summary))
        # --- Equity Chart ---
        eq_fig = go.Figure()
        if not df_tf.empty:
            eq_fig.add_trace(
                go.Scatter(
                    x=df_tf["timestamp"],
                    y=df_tf["equity"],
                    mode="lines",
                    name="Equity",
                    line=dict(color="deepskyblue", width=2),
                )
            )
        if not df_tf.empty and not trades_tf.empty and "pnl" in trades_tf.columns:
            wins = trades_tf[trades_tf["pnl"] > 0]
            losses = trades_tf[trades_tf["pnl"] <= 0]
            eq_series = df_tf.set_index("timestamp")["equity"]
            def equity_at(ts):
                try:
                    return float(eq_series.loc[:ts].iloc[-1])
                except Exception:
                    return np.nan
            if not wins.empty:
                eq_fig.add_trace(
                    go.Scatter(
                        x=wins["timestamp"],
                        y=[equity_at(ts) for ts in wins["timestamp"]],
                        mode="markers",
                        name="Winning Trades",
                        marker=dict(color="limegreen", size=9, symbol="circle"),
                        hovertext=[
                            f"{r.ticker} | {getattr(r, 'edge', 'Unknown')} | {r.side} | PnL:{float(r.pnl) if pd.notna(r.pnl) else 0:.2f}"
                            for _, r in wins.iterrows()
                        ],
                        hoverinfo="text",
                    )
                )
            if not losses.empty:
                eq_fig.add_trace(
                    go.Scatter(
                        x=losses["timestamp"],
                        y=[equity_at(ts) for ts in losses["timestamp"]],
                        mode="markers",
                        name="Losing Trades",
                        marker=dict(color="red", size=9, symbol="x"),
                        hovertext=[
                            f"{r.ticker} | {getattr(r, 'edge', 'Unknown')} | {r.side} | PnL:{float(r.pnl) if pd.notna(r.pnl) else 0:.2f}"
                            for _, r in losses.iterrows()
                        ],
                        hoverinfo="text",
                    )
                )
        eq_fig.update_layout(
            title="Equity Curve",
            xaxis_title="Date",
            yaxis_title="Equity ($)",
            hovermode="x unified",
            template="plotly_dark",
            legend=dict(x=0, y=1),
        )
        # --- Drawdown Chart (capped to [-100%, 0%]) ---
        dd_fig = go.Figure()
        if not df_tf.empty:
            roll_max = df_tf["equity"].cummax()
            drawdown = (df_tf["equity"] - roll_max) / roll_max
            drawdown = drawdown.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=-1, upper=0)
            dd_fig.add_trace(
                go.Scatter(
                    x=df_tf["timestamp"],
                    y=drawdown,
                    fill="tozeroy",
                    mode="lines",
                    name="Drawdown",
                    line=dict(color="firebrick"),
                )
            )
        dd_fig.update_layout(
            title="Drawdown Over Time",
            xaxis_title="Date",
            yaxis_title="Drawdown",
            yaxis_tickformat=".0%",
            template="plotly_dark",
        )
        # --- PnL by Edge (bar) ---
        edge_fig = go.Figure()
        if trades_tf is not None and not trades_tf.empty and {"edge", "pnl"}.issubset(set(trades_tf.columns)):
            pnl_by_edge = (
                trades_tf.groupby("edge", dropna=False)["pnl"]
                .sum()
                .sort_values(ascending=False)
                .reset_index()
            )
            if not pnl_by_edge.empty:
                colors = ["limegreen" if v >= 0 else "firebrick" for v in pnl_by_edge["pnl"]]
                edge_fig.add_trace(
                    go.Bar(
                        x=pnl_by_edge["edge"].astype(str),
                        y=pnl_by_edge["pnl"],
                        marker_color=colors,
                        text=[f"${v:,.2f}" for v in pnl_by_edge["pnl"]],
                        textposition="auto",
                        name="PnL",
                    )
                )
        edge_fig.update_layout(
            title="Profit / Loss by Edge",
            xaxis_title="Edge",
            yaxis_title="PnL ($)",
            template="plotly_dark",
        )
        recent_txt = (
            trades_tf.tail(10).to_string(index=False)
            if not trades_tf.empty
            else "No trades found."
        )
        return eq_fig, dd_fig, edge_fig, summary_cards, recent_txt
    # ---------- Mode Label Callback (new, lightweight) ----------
    @app.callback(
        Output("mode_label", "children"),
        Input("mode_state", "data"),
        prevent_initial_call=False,
    )
    def _show_mode_label(mode_value):
        label = "Backtest" if mode_value == "backtest" else ("Paper" if mode_value == "paper" else "Live")
        return f"Active Mode: {label}"

    # Top-level mode indicator for dashboard (paper/live/backtest)
    @app.callback(
        Output("mode_top_indicator", "children"),
        Input("mode_state", "data"),
        Input("pulse", "n_intervals"),
        prevent_initial_call=False,
    )
    def _show_mode_top_indicator(mode_value, n_pulse):
        if mode_value == "paper":
            return html.Span("🟢 PAPER MODE — Auto-refreshing", style={"color": "#12ff8c"})
        elif mode_value == "live":
            return html.Span("⚪ LIVE MODE (Coming Soon)", style={"color": "#ffb300"})
        else:
            return html.Span("🟣 BACKTEST MODE", style={"color": "#8c6bff"})
    
    # ---------------------------- Analytics Callbacks ---------------------------- #

    @app.callback(
        Output("edge_cum_pnl_chart", "figure"),
        Output("equity_vs_bench_chart", "figure"),
        Output("pnl_heatmap_chart", "figure"),
        Output("rolling_outperformance_chart", "figure"),
        Output("trades_table", "data"),
        Output("trades_table", "columns"),
        Input("timeframe_analytics", "value"),
        Input("benchmark_selector", "value"),
        Input("pulse", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_analytics(tf_value, benchmark_symbol, _n):
        df, trades = base_snapshots, base_trades
        if live:
            df, trades = reload_frames()

        if trades is not None and not trades.empty:
            if ("pnl" not in trades.columns) or (trades["pnl"].isna().all()):
                trades = compute_trade_pnl_fifo(trades)
            if "edge" not in trades.columns:
                trades["edge"] = "Unknown"
            trades["timestamp"] = pd.to_datetime(trades["timestamp"], errors="coerce")
            trades = trades.dropna(subset=["timestamp"]).sort_values("timestamp")

        df_tf = timeframe_filter(df, tf_value)
        trades_tf = timeframe_filter(trades, tf_value) if (trades is not None and not trades.empty) else pd.DataFrame()

        # Build DataTable payload (last 200 trades)
        table_data, table_columns = [], []
        if trades_tf is not None and not trades_tf.empty:
            show_cols = ["timestamp", "ticker", "side", "qty", "fill_price", "commission", "pnl", "edge", "trigger"]
            for c in show_cols:
                if c not in trades_tf.columns:
                    trades_tf[c] = np.nan
            tdf = trades_tf.copy()
            tdf["timestamp"] = pd.to_datetime(tdf["timestamp"], errors="coerce").dt.tz_localize(None)
            tdf = tdf.sort_values("timestamp", ascending=False).head(200)
            table_columns = [{"name": c, "id": c} for c in show_cols]
            # Format numeric fields
            def fmt_float(x):
                try:
                    return round(float(x), 4)
                except Exception:
                    return x
            tdf["fill_price"] = tdf["fill_price"].apply(fmt_float)
            tdf["commission"] = tdf["commission"].apply(fmt_float)
            tdf["pnl"] = tdf["pnl"].apply(fmt_float)
            table_data = tdf[show_cols].to_dict("records")

        # --- Cumulative PnL by Edge Over Time (monthly) ---
        edge_cum_fig = go.Figure()
        if not trades_tf.empty and {"edge", "pnl", "timestamp"}.issubset(set(trades_tf.columns)):
            tmp = trades_tf.copy()
            tmp["month"] = tmp["timestamp"].dt.to_period("M").dt.to_timestamp()
            monthly = tmp.groupby(["edge", "month"], dropna=False)["pnl"].sum().reset_index()
            monthly = monthly.sort_values("month")
            wide = monthly.pivot(index="month", columns="edge", values="pnl").fillna(0.0)
            cum = wide.cumsum()
            if not cum.empty:
                for col in cum.columns:
                    edge_cum_fig.add_trace(
                        go.Scatter(
                            x=cum.index,
                            y=cum[col],
                            mode="lines",
                            name=str(col),
                        )
                    )
        edge_cum_fig.update_layout(
            title="Cumulative PnL by Edge Over Time (Monthly)",
            xaxis_title="Month",
            yaxis_title="Cumulative PnL ($)",
            hovermode="x unified",
            template="plotly_dark",
            legend=dict(x=0, y=1),
        )

        # --- Equity vs Benchmark (S&P 500) ---
        eq_vs_fig = go.Figure()
        if not df_tf.empty:
            eq_series = df_tf[["timestamp", "equity"]].copy()
            eq_series = eq_series.dropna()
            if not eq_series.empty:
                eq_series["index"] = 100.0 * (eq_series["equity"] / eq_series["equity"].iloc[0])
                eq_vs_fig.add_trace(
                    go.Scatter(
                        x=eq_series["timestamp"],
                        y=eq_series["index"],
                        mode="lines",
                        name="Strategy",
                    )
                )
                # benchmark
                start = pd.to_datetime(eq_series["timestamp"].min())
                end = pd.to_datetime(eq_series["timestamp"].max())
                bench = load_benchmark(benchmark_symbol, start, end)
                if bench.empty and benchmark_symbol == "^GSPC":
                    bench = load_benchmark("SPY", start, end)
                if not bench.empty:
                    bench = bench[(bench["timestamp"] >= start) & (bench["timestamp"] <= end)]
                    eq_vs_fig.add_trace(
                        go.Scatter(
                            x=bench["timestamp"],
                            y=bench["index"],
                            mode="lines",
                            name="Benchmark",
                        )
                    )
                else:
                    eq_vs_fig.add_annotation(
                        text="Benchmark download failed (offline?). Showing strategy only.",
                        xref="paper", yref="paper", x=0.01, y=0.95, showarrow=False, font=dict(color="orange")
                    )

        eq_vs_fig.update_layout(
            title=f"Equity (Indexed) vs. {benchmark_symbol}",
            xaxis_title="Date",
            yaxis_title="Index (100 = start)",
            hovermode="x unified",
            template="plotly_dark",
            legend=dict(x=0, y=1),
        )
                # --- Daily PnL Heatmap ---
        heatmap_fig = go.Figure()
        if not trades_tf.empty and "pnl" in trades_tf.columns:
            tmp = trades_tf.copy()
            tmp["date"] = tmp["timestamp"].dt.date
            daily = tmp.groupby("date")["pnl"].sum().reset_index()
            daily["month"] = pd.to_datetime(daily["date"]).dt.to_period("M").astype(str)
            daily["day"] = pd.to_datetime(daily["date"]).dt.day

            # Pivot to month/day grid
            pivot = daily.pivot(index="day", columns="month", values="pnl").fillna(0.0)
            heatmap_fig.add_trace(
                go.Heatmap(
                    z=pivot.values,
                    x=pivot.columns,
                    y=pivot.index,
                    colorscale=[
                        [0, "rgb(178,34,34)"],   # deep red for losses
                        [0.5, "rgb(64,64,64)"],  # neutral grey
                        [1, "rgb(0,255,128)"],   # bright green for profits
                    ],
                    colorbar=dict(title="PnL ($)"),
                    hoverongaps=False,
                )
            )

        heatmap_fig.update_layout(
            title="PnL Heatmap by Day",
            xaxis_title="Month",
            yaxis_title="Day of Month",
            template="plotly_dark",
            yaxis_autorange="reversed",
        )
                # --- Rolling Outperformance vs Benchmark (30-day) ---
        outperf_fig = go.Figure()
        if not df_tf.empty:
            eq_series = df_tf[["timestamp", "equity"]].dropna().copy()
            eq_series["return"] = eq_series["equity"].pct_change().fillna(0.0)

            # Benchmark alignment
            start = pd.to_datetime(eq_series["timestamp"].min())
            end = pd.to_datetime(eq_series["timestamp"].max())
            bench = load_benchmark(benchmark_symbol, start, end)
            if bench.empty and benchmark_symbol == "^GSPC":
                bench = load_benchmark("SPY", start, end)
            if not bench.empty:
                bench["return"] = bench["index"].pct_change().fillna(0.0)
                merged = pd.merge_asof(
                    eq_series.sort_values("timestamp"),
                    bench.sort_values("timestamp")[["timestamp", "return"]],
                    on="timestamp",
                    direction="backward",
                    suffixes=("_strategy", "_benchmark"),
                )

                merged["diff"] = merged["return_strategy"] - merged["return_benchmark"]
                merged["rolling_diff"] = merged["diff"].rolling(window=30).mean() * 100.0

                outperf_fig.add_trace(
                    go.Scatter(
                        x=merged["timestamp"],
                        y=merged["rolling_diff"],
                        mode="lines",
                        name="Rolling Outperformance (30D, %)",
                        line=dict(color="limegreen"),
                    )
                )

                # Highlight underperformance (negative rolling diff)
                under = merged[merged["rolling_diff"] < 0]
                if not under.empty:
                    outperf_fig.add_trace(
                        go.Scatter(
                            x=under["timestamp"],
                            y=under["rolling_diff"],
                            mode="lines",
                            name="Underperformance",
                            line=dict(color="firebrick", width=1),
                        )
                    )
            else:
                outperf_fig.add_annotation(
                    text="Benchmark data unavailable (offline?).",
                    xref="paper", yref="paper", x=0.01, y=0.95, showarrow=False, font=dict(color="orange")
                )

        outperf_fig.update_layout(
            title=f"Rolling Outperformance vs {benchmark_symbol} (30-Day Average)",
            xaxis_title="Date",
            yaxis_title="Excess Return (%)",
            hovermode="x unified",
            template="plotly_dark",
            legend=dict(x=0, y=1),
        )

        return edge_cum_fig, eq_vs_fig, heatmap_fig, outperf_fig, table_data, table_columns

    app.run(debug=True)


# ---------------------------- CLI Entry ---------------------------- #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run trading cockpit dashboard.")
    parser.add_argument("--live", action="store_true", help="Auto-refresh from CSVs every 2s.")
    parser.add_argument("--snapshots", default="data/trade_logs/portfolio_snapshots.csv")
    parser.add_argument("--trades", default="data/trade_logs/trades.csv")
    args = parser.parse_args()

    run_dashboard(live=args.live, snapshots_csv=args.snapshots, trades_csv=args.trades)
    # ---------------------------- KPI Cards for Summary ---------------------------- #
    def _summary_kpi_cards(summary: dict):
        """Display summary dict as styled KPI cards in a grid."""
        # Choose a subset of key metrics for prominent display
        kpi_keys = [
            ("Ending Equity", "Equity"),
            ("Total Return (%)", "Return"),
            ("Sharpe Ratio", "Sharpe"),
            ("Max Drawdown (%)", "Drawdown"),
        ]
        # Fallback to all keys if not found
        kpis = []
        for key, short in kpi_keys:
            val = summary.get(key, "-")
            if val is None:
                val = "-"
            kpis.append(
                html.Div(
                    [
                        html.Div(short, style={"fontSize": "16px", "color": "#9bb1ff", "fontWeight": "bold", "marginBottom": "3px"}),
                        html.Div(str(val), style={"fontSize": "27px", "fontWeight": "bold", "color": "#e0e0e0"}),
                    ],
                    style={
                        "background": "#20253a",
                        "margin": "4px 8px 4px 0",
                        "borderRadius": "10px",
                        "padding": "14px 18px",
                        "display": "inline-block",
                        "minWidth": "120px",
                        "boxShadow": "0 1px 6px #0004",
                        "textAlign": "center",
                        "border": "1px solid #2c2c3a",
                    }
                )
            )
        # Add the rest of the metrics in a secondary grid
        secondary_keys = [k for k in summary.keys() if k not in [k for k, _ in kpi_keys]]
        secondary = []
        for k in secondary_keys:
            v = summary[k]
            if v is None:
                v = "-"
            secondary.append(
                html.Div(
                    [
                        html.Div(k, style={"fontSize": "13px", "color": "#b3b3c7"}),
                        html.Div(str(v), style={"fontSize": "16px", "fontWeight": "bold", "color": "#e0e0e0"}),
                    ],
                    style={
                        "background": "#181b28",
                        "margin": "3px 8px 3px 0",
                        "borderRadius": "8px",
                        "padding": "8px 12px",
                        "display": "inline-block",
                        "minWidth": "100px",
                        "boxShadow": "0 1px 4px #0002",
                        "textAlign": "center",
                        "border": "1px solid #232336",
                    }
                )
            )
        return [
            html.Div(kpis, style={"display": "flex", "gap": "10px", "marginBottom": "10px"}),
            html.Div(secondary, style={"display": "flex", "gap": "8px", "flexWrap": "wrap"}),
        ]
    # --------- Performance Tab Callbacks (Rolling Sharpe, MaxDD, PnL Decomp, Edge Correlation) --------- #
    @app.callback(
        Output("rolling_sharpe_chart", "figure"),
        Output("rolling_maxdd_chart", "figure"),
        Output("pnl_decomp_chart", "figure"),
        Output("edge_corr_heatmap", "figure"),
        Output("edge_weight_evolution_chart", "figure"),
        Input("timeframe_performance", "value"),
        Input("mode_state", "data"),
        Input("pulse", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_performance_tab(tf_value, mode_value, n_pulse):
        eq_df = dataman.get_equity_curve(mode_value)
        trades_df = dataman.get_trades(mode_value)
        if not eq_df.empty:
            eq_df["timestamp"] = pd.to_datetime(eq_df["timestamp"]).dt.tz_localize(None)
        if not trades_df.empty:
            trades_df["timestamp"] = pd.to_datetime(trades_df["timestamp"]).dt.tz_localize(None)
        eq_df = timeframe_filter(eq_df, tf_value)
        trades_df = timeframe_filter(trades_df, tf_value)
        # Rolling Sharpe
        sharpe_fig = go.Figure()
        if not eq_df.empty and "equity" in eq_df.columns:
            rets = eq_df["equity"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
            window = 21
            rolling_sharpe = rets.rolling(window=window).mean() / rets.rolling(window=window).std()
            rolling_sharpe = rolling_sharpe * np.sqrt(252)
            sharpe_fig.add_trace(
                go.Scatter(
                    x=eq_df["timestamp"],
                    y=rolling_sharpe,
                    mode="lines",
                    name="Rolling Sharpe",
                    line=dict(color="deepskyblue"),
                )
            )
        sharpe_fig.update_layout(
            title=f"Rolling Sharpe Ratio ({window}D Window)",
            xaxis_title="Date",
            yaxis_title="Sharpe Ratio",
            template="plotly_dark",
        )
        # Rolling Max Drawdown
        maxdd_fig = go.Figure()
        if not eq_df.empty and "equity" in eq_df.columns:
            eq = eq_df["equity"]
            roll_max = eq.rolling(window=30, min_periods=1).max()
            dd = (eq - roll_max) / roll_max
            dd = dd.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=-1, upper=0)
            maxdd_rolling = dd.rolling(window=30, min_periods=1).min()
            maxdd_fig.add_trace(
                go.Scatter(
                    x=eq_df["timestamp"],
                    y=maxdd_rolling,
                    mode="lines",
                    name="Rolling Max Drawdown",
                    line=dict(color="firebrick"),
                )
            )
        maxdd_fig.update_layout(
            title="Rolling Max Drawdown (30D Window)",
            xaxis_title="Date",
            yaxis_title="Drawdown",
            yaxis_tickformat=".0%",
            template="plotly_dark",
        )
        # PnL Decomposition (Realized vs Unrealized)
        pnl_decomp_fig = go.Figure()
        realized, unrealized = 0.0, 0.0
        if not trades_df.empty and "pnl" in trades_df.columns:
            realized = trades_df["pnl"].dropna().sum()
        if not eq_df.empty and realized is not None:
            total = eq_df["equity"].iloc[-1] - eq_df["equity"].iloc[0]
            unrealized = total - realized
        pnl_decomp_fig.add_trace(go.Bar(name="Realized", x=["PnL"], y=[realized]))
        pnl_decomp_fig.add_trace(go.Bar(name="Unrealized", x=["PnL"], y=[unrealized]))
        pnl_decomp_fig.update_layout(
            barmode="stack",
            title="PnL Decomposition (Realized vs Unrealized)",
            template="plotly_dark",
            yaxis_title="PnL ($)",
        )

        # Edge correlation heatmap (daily PnL by edge)
        corr_fig = go.Figure()
        if not trades_df.empty and {"edge", "timestamp", "pnl"}.issubset(trades_df.columns):
            tmp = trades_df.copy()
            tmp["date"] = pd.to_datetime(tmp["timestamp"], errors="coerce").dt.date
            daily_edge = tmp.groupby(["date", "edge"])["pnl"].sum().unstack().fillna(0.0)
            if daily_edge.shape[1] >= 2:
                corr = daily_edge.corr().fillna(0.0)
                corr_fig.add_trace(
                    go.Heatmap(
                        z=corr.values,
                        x=corr.columns.astype(str),
                        y=corr.index.astype(str),
                        zmin=-1, zmax=1,
                        colorscale="RdBu",
                        colorbar=dict(title="Corr"),
                    )
                )
        corr_fig.update_layout(
            title="Edge Correlation (Daily PnL)",
            template="plotly_dark",
        )

        # Edge weight evolution (from governor history if available)
        def load_edge_weight_history_df():
            candidates = [
                Path("data/governor/edge_weights_history.csv"),
                Path("data/governor/feedback_history.log"),
            ]
            for p in candidates:
                if p.exists() and p.stat().st_size > 0:
                    try:
                        if p.suffix == ".csv":
                            dfh = pd.read_csv(p)
                            if "timestamp" in dfh.columns:
                                dfh["timestamp"] = pd.to_datetime(dfh["timestamp"], errors="coerce").dt.tz_localize(None)
                            return dfh
                        else:
                            rows = []
                            with p.open("r") as fh:
                                for line in fh:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    try:
                                        import json
                                        obj = json.loads(line)
                                        ts = pd.to_datetime(obj.get("timestamp") or obj.get("time") or pd.Timestamp.utcnow(), errors="coerce")
                                        weights = obj.get("weights") or obj.get("edge_weights") or {}
                                        for edge, w in weights.items():
                                            rows.append({"timestamp": ts, "edge": edge, "weight": w})
                                    except Exception:
                                        continue
                            if rows:
                                dfh = pd.DataFrame(rows)
                                dfh["timestamp"] = pd.to_datetime(dfh["timestamp"], errors="coerce").dt.tz_localize(None)
                                return dfh
                    except Exception:
                        pass
            try:
                import json
                p = Path("data/governor/edge_weights.json")
                if p.exists():
                    obj = json.loads(p.read_text())
                    weights = obj.get("weights", {})
                    now = pd.Timestamp.utcnow().tz_localize(None)
                    return pd.DataFrame(
                        [{"timestamp": now, "edge": k, "weight": v} for k, v in weights.items()]
                    )
            except Exception:
                pass
            return pd.DataFrame()

        ew_df = load_edge_weight_history_df()
        ew_fig = go.Figure()
        if not ew_df.empty:
            ew_df = ew_df.dropna(subset=["timestamp", "edge", "weight"])
            ew_df = ew_df.sort_values("timestamp")
            for edge_name, edf in ew_df.groupby("edge"):
                ew_fig.add_trace(
                    go.Scatter(
                        x=edf["timestamp"],
                        y=edf["weight"],
                        mode="lines",
                        name=str(edge_name),
                    )
                )
        ew_fig.update_layout(
            title="Edge Weight Evolution",
            xaxis_title="Date",
            yaxis_title="Weight",
            template="plotly_dark",
            legend=dict(x=0, y=1),
        )

        return sharpe_fig, maxdd_fig, pnl_decomp_fig, corr_fig, ew_fig
    # ---------------- Governor Tab Callbacks ---------------- #
    @app.callback(
        Output("gov_weight_chart", "figure"),
        Output("gov_sr_weight_scatter", "figure"),
        Output("gov_recommendation_chart", "figure"),
        Output("gov_weight_evolution", "figure"),
        Input("pulse", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_governor_tab(_n):
        import json
        from pathlib import Path
        # Load governor data
        # --- Load governor data (robust path handling) ---
        from pathlib import Path
        import json

        # Try both correct and fallback directories (to fix "gvernor" typo)
        base_dirs = [Path("data/governor"), Path("data/gvernor")]

        def find_existing_file(filename):
            for d in base_dirs:
                p = d / filename
                if p.exists():
                    return p
            return None

        weights_path = find_existing_file("edge_weights.json")
        metrics_path = find_existing_file("edge_metrics.json")
        rec_path = Path("data/research/edge_recommendations.json")
        history_path = find_existing_file("edge_weights_history.csv") or Path("data/governor/edge_weights_history.csv")

        weights, metrics, recs = {}, {}, {}
        try:
            if weights_path and weights_path.exists():
                weights = json.loads(weights_path.read_text()).get("weights", {})
            else:
                print("[GOVERNOR] edge_weights.json not found.")
            if metrics_path and metrics_path.exists():
                metrics = json.loads(metrics_path.read_text()).get("metrics", {})
            else:
                print("[GOVERNOR] edge_metrics.json not found.")
            if rec_path.exists():
                recs = json.loads(rec_path.read_text())
            else:
                print("[GOVERNOR] edge_recommendations.json not found (optional).")
        except Exception as e:
            print(f"[GOVERNOR] Error loading governor files: {e}")

        weights = {}
        metrics = {}
        recs = {}
        try:
            if weights_path.exists():
                weights = json.loads(weights_path.read_text()).get("weights", {})
            if metrics_path.exists():
                metrics = json.loads(metrics_path.read_text()).get("metrics", {})
            if rec_path.exists():
                recs = json.loads(rec_path.read_text())
        except Exception:
            pass

        # --- Chart 1: Edge Weights Bar ---
        weight_fig = go.Figure()
        if weights:
            edges = list(weights.keys())
            vals = list(weights.values())
            colors = ["limegreen" if v >= np.mean(vals) else "deepskyblue" for v in vals]
            weight_fig.add_trace(go.Bar(x=edges, y=vals, marker_color=colors))
        weight_fig.update_layout(
            title="Current Edge Weights",
            xaxis_title="Edge",
            yaxis_title="Weight",
            template="plotly_dark",
        )

        # --- Chart 2: SR vs Weight Scatter ---
        scatter_fig = go.Figure()
        if metrics and weights:
            data = []
            for edge, vals in metrics.items():
                sr = vals.get("sr", np.nan)
                w = weights.get(edge, np.nan)
                mdd = vals.get("mdd", np.nan)
                data.append((edge, sr, w, mdd))
            df = pd.DataFrame(data, columns=["edge", "sr", "weight", "mdd"]).dropna()
            scatter_fig.add_trace(
                go.Scatter(
                    x=df["sr"],
                    y=df["weight"],
                    mode="markers+text",
                    text=df["edge"],
                    textposition="top center",
                    marker=dict(size=12, color=df["mdd"], colorscale="Viridis", showscale=True, colorbar=dict(title="MDD")),
                )
            )
        scatter_fig.update_layout(
            title="Sharpe Ratio vs Weight (color = MDD)",
            xaxis_title="Sharpe Ratio",
            yaxis_title="Weight",
            template="plotly_dark",
        )

        # --- Chart 3: Recommendations ---
        rec_fig = go.Figure()
        if recs:
            edges = list(recs.keys())
            vals = list(recs.values())
            colors = ["limegreen" if v >= 0.5 else "firebrick" for v in vals]
            rec_fig.add_trace(go.Bar(x=edges, y=vals, marker_color=colors))
        rec_fig.update_layout(
            title="Governor Recommendations",
            xaxis_title="Edge",
            yaxis_title="Suggested Weight",
            template="plotly_dark",
        )

        # --- Chart 4: Weight Evolution ---
        ew_fig = go.Figure()
        if history_path.exists():
            try:
                dfh = pd.read_csv(history_path)
                if not dfh.empty and {"timestamp", "edge", "weight"}.issubset(dfh.columns):
                    dfh["timestamp"] = pd.to_datetime(dfh["timestamp"], errors="coerce").dt.tz_localize(None)
                    for edge, edf in dfh.groupby("edge"):
                        ew_fig.add_trace(go.Scatter(x=edf["timestamp"], y=edf["weight"], mode="lines", name=edge))
            except Exception:
                pass
        ew_fig.update_layout(
            title="Edge Weight Evolution",
            xaxis_title="Date",
            yaxis_title="Weight",
            template="plotly_dark",
            legend=dict(x=0, y=1),
        )

        return weight_fig, scatter_fig, rec_fig, ew_fig03
    # --- Performance Tab Callback (modernized) ---
    @app.callback(
        Output("rolling_sharpe_chart", "figure"),
        Output("rolling_maxdd_chart", "figure"),
        Output("pnl_decomp_chart", "figure"),
        Output("edge_corr_heatmap", "figure"),
        Output("edge_weight_evolution_chart", "figure"),
        Input("timeframe_performance", "value"),
        Input("pulse", "n_intervals"),
        Input("mode_state", "data"),
        prevent_initial_call=False,
    )
    def update_performance_tab(tf_value, n_pulse, mode_value):
        # Load data for selected mode
        snapshots_path = f"data/trade_logs/{mode_value}/portfolio_snapshots.csv"
        trades_path = f"data/trade_logs/{mode_value}/trades.csv"
        default_snapshots = "data/trade_logs/portfolio_snapshots.csv"
        default_trades = "data/trade_logs/trades.csv"
        def file_exists(path):
            return Path(path).exists() and Path(path).stat().st_size > 0
        if not file_exists(snapshots_path):
            snapshots_path = default_snapshots
        if not file_exists(trades_path):
            trades_path = default_trades
        if PerformanceMetrics is not None:
            try:
                m = PerformanceMetrics(snapshots_path=snapshots_path, trades_path=trades_path)
                df_snap = m.snapshots.copy()
                df_tr = m.trades.copy() if m.trades is not None else pd.DataFrame()
            except Exception:
                df_snap = safe_read_csv(snapshots_path)
                df_tr = safe_read_csv(trades_path)
        else:
            df_snap = safe_read_csv(snapshots_path)
            df_tr = safe_read_csv(trades_path)
        # Filter by timeframe
        df_snap = timeframe_filter(df_snap, tf_value)
        df_tr = timeframe_filter(df_tr, tf_value) if (df_tr is not None and not df_tr.empty) else pd.DataFrame()
        # Ensure PnL attribution and types
        if df_tr is not None and not df_tr.empty:
            if ("pnl" not in df_tr.columns) or (df_tr["pnl"].isna().all()):
                df_tr = compute_trade_pnl_fifo(df_tr)
            if "edge" not in df_tr.columns:
                df_tr["edge"] = "Unknown"
            for col in ("qty", "fill_price", "pnl"):
                if col in df_tr.columns:
                    df_tr[col] = pd.to_numeric(df_tr[col], errors="coerce")
            df_tr["timestamp"] = pd.to_datetime(df_tr["timestamp"], errors="coerce")
            df_tr = df_tr.dropna(subset=["timestamp"]).sort_values("timestamp")
        # --- Rolling Sharpe Chart ---
        sharpe_fig = go.Figure()
        # --- Rolling MaxDD Chart ---
        maxdd_fig = go.Figure()
        # --- PnL Decomposition Chart ---
        pnl_decomp_fig = go.Figure()
        # --- Edge Correlation Heatmap ---
        corr_fig = go.Figure()
        # --- Edge Weight Evolution Chart ---
        ew_fig = go.Figure()
        # Empty state handling
        if df_snap is None or df_snap.empty:
            for fig in [sharpe_fig, maxdd_fig, pnl_decomp_fig, corr_fig, ew_fig]:
                fig.add_annotation(text="No data available", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(color="gray", size=20))
                fig.update_layout(template="plotly_dark")
            return sharpe_fig, maxdd_fig, pnl_decomp_fig, corr_fig, ew_fig
        # Rolling Sharpe (window=21d)
        if not df_snap.empty and "equity" in df_snap.columns:
            df_snap = df_snap.copy()
            df_snap["ret"] = df_snap["equity"].pct_change()
            window = 21
            rolling_sharpe = df_snap["ret"].rolling(window).mean() / df_snap["ret"].rolling(window).std()
            rolling_sharpe = rolling_sharpe * np.sqrt(252)
            sharpe_fig.add_trace(
                go.Scatter(
                    x=df_snap["timestamp"],
                    y=rolling_sharpe,
                    mode="lines",
                    name=f"Rolling Sharpe ({window}d)",
                    line=dict(color="deepskyblue", width=2),
                )
            )
            sharpe_fig.update_layout(
                title=f"Rolling Sharpe Ratio ({window}d)",
                xaxis_title="Date",
                yaxis_title="Sharpe Ratio",
                template="plotly_dark",
            )
        # Rolling Max Drawdown (window=90d)
        if not df_snap.empty and "equity" in df_snap.columns:
            window = 90
            roll_max = df_snap["equity"].rolling(window, min_periods=1).max()
            roll_drawdown = (df_snap["equity"] - roll_max) / roll_max
            roll_drawdown = roll_drawdown.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=-1, upper=0)
            maxdd_fig.add_trace(
                go.Scatter(
                    x=df_snap["timestamp"],
                    y=roll_drawdown,
                    mode="lines",
                    name=f"Rolling MaxDD ({window}d)",
                    line=dict(color="firebrick", width=2),
                )
            )
            maxdd_fig.update_layout(
                title=f"Rolling Max Drawdown ({window}d)",
                xaxis_title="Date",
                yaxis_title="Drawdown",
                yaxis_tickformat=".0%",
                template="plotly_dark",
            )
        # PnL Decomposition (by edge, cumulative)
        if df_tr is not None and not df_tr.empty and {"edge", "pnl", "timestamp"}.issubset(set(df_tr.columns)):
            tmp = df_tr.copy()
            tmp = tmp.sort_values("timestamp")
            tmp["pnl"] = pd.to_numeric(tmp["pnl"], errors="coerce").fillna(0.0)
            edges = tmp["edge"].unique()
            for edge in edges:
                edge_df = tmp[tmp["edge"] == edge]
                edge_df = edge_df.sort_values("timestamp")
                cum_pnl = edge_df["pnl"].cumsum()
                pnl_decomp_fig.add_trace(
                    go.Scatter(
                        x=edge_df["timestamp"],
                        y=cum_pnl,
                        mode="lines",
                        name=str(edge),
                    )
                )
            pnl_decomp_fig.update_layout(
                title="Cumulative PnL by Edge",
                xaxis_title="Date",
                yaxis_title="Cumulative PnL ($)",
                template="plotly_dark",
                legend=dict(x=0, y=1),
            )
        # Edge Correlation Heatmap (PnL by edge, daily)
        if df_tr is not None and not df_tr.empty and {"edge", "pnl", "timestamp"}.issubset(set(df_tr.columns)):
            tmp = df_tr.copy()
            tmp["date"] = pd.to_datetime(tmp["timestamp"]).dt.date
            daily = tmp.groupby(["date", "edge"], dropna=False)["pnl"].sum().unstack(fill_value=0.0)
            if daily.shape[1] >= 2:
                corr = daily.corr()
                corr_fig.add_trace(
                    go.Heatmap(
                        z=corr.values,
                        x=corr.columns.astype(str),
                        y=corr.index.astype(str),
                        colorscale="bluered",
                        colorbar=dict(title="Correlation"),
                    )
                )
                corr_fig.update_layout(
                    title="Edge PnL Correlation Heatmap",
                    xaxis_title="Edge",
                    yaxis_title="Edge",
                    template="plotly_dark",
                )
            else:
                corr_fig.add_annotation(text="Not enough edges for correlation", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(color="gray", size=20))
                corr_fig.update_layout(template="plotly_dark")
        else:
            corr_fig.add_annotation(text="No data available", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(color="gray", size=20))
            corr_fig.update_layout(template="plotly_dark")
        # Edge Weight Evolution (if available)
        if "edge_weight" in df_snap.columns:
            ew = df_snap.copy()
            ew = ew.sort_values("timestamp")
            for edge in [c for c in ew.columns if c.startswith("edge_weight_")]:
                ew_fig.add_trace(
                    go.Scatter(
                        x=ew["timestamp"],
                        y=ew[edge],
                        mode="lines",
                        name=edge.replace("edge_weight_", ""),
                    )
                )
            ew_fig.update_layout(
                title="Edge Weight Evolution",
                xaxis_title="Date",
                yaxis_title="Weight",
                template="plotly_dark",
            )
        else:
            ew_fig.add_annotation(text="No edge weights available", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(color="gray", size=20))
            ew_fig.update_layout(template="plotly_dark")
        return sharpe_fig, maxdd_fig, pnl_decomp_fig, corr_fig, ew_fig