# cockpit/dashboard_v2/utils/chart_helpers.py
"""Shared chart utilities — single source of truth for Plotly styling and data filtering."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def get_chart_layout(title: str = "", **kwargs) -> dict:
    """Return consistent Plotly chart layout settings."""
    base = {
        "template": "plotly_dark",
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "Inter, sans-serif", "color": "#c9d1d9"},
        "title": {"text": title, "font": {"size": 14, "color": "#f0f6fc"}} if title else None,
        "margin": {"l": 40, "r": 20, "t": 40 if title else 20, "b": 40},
        "xaxis": {
            "gridcolor": "rgba(56, 68, 77, 0.3)",
            "zerolinecolor": "rgba(56, 68, 77, 0.5)",
        },
        "yaxis": {
            "gridcolor": "rgba(56, 68, 77, 0.3)",
            "zerolinecolor": "rgba(56, 68, 77, 0.5)",
        },
        "hovermode": "x unified",
    }
    base.update(kwargs)
    return base


def empty_chart(message: str = "No data available") -> go.Figure:
    """Create an empty chart with a centered message."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font={"size": 14, "color": "#6e7681", "family": "Inter, sans-serif"},
        align="center",
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"visible": False},
        yaxis={"visible": False},
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
    )
    return fig


def timeframe_filter(df: pd.DataFrame, tf_value: str) -> pd.DataFrame:
    """Filter DataFrame by timeframe value (all, 1y, 6m, 3m, 1m)."""
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
