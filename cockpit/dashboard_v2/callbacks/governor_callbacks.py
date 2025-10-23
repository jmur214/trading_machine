from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output

from ..utils.datamanager import DataManager


def register_governor_callbacks(app):
    dm = DataManager()

    @app.callback(
        Output("gov_weight_chart", "figure"),
        Output("gov_sr_weight_scatter", "figure"),
        Output("gov_recommendation_chart", "figure"),
        Output("gov_weight_evolution", "figure"),
        Input("pulse", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_governor_tab(_n):  # noqa: ANN001
        # ---- Load state ----
        weights = dm.get_weights()  # dict[str, float]
        metrics = dm.get_metrics()  # dict[str, dict]
        recs = dm.get_recommendations()  # dict[str, Any]
        last_ts = dm.get_last_update()

        # ---- 1) Weights bar chart ----
        w_fig = go.Figure()
        if weights:
            edges = list(weights.keys())
            wvals = [weights[e] for e in edges]
            w_fig.add_trace(go.Bar(x=edges, y=wvals, name="Weight"))
        w_fig.update_layout(
            title=f"Edge Weights" + (f" — Updated {last_ts}" if last_ts else ""),
            template="plotly_dark",
            xaxis_title="Edge",
            yaxis_title="Weight",
        )

        # ---- 2) SR vs Weight scatter ----
        sr_fig = go.Figure()
        if metrics and weights:
            xs, ys, labels = [], [], []
            for edge, w in weights.items():
                sr = None
                m = metrics.get(edge, {})
                if isinstance(m, dict):
                    sr = m.get("sr")
                try:
                    xs.append(float(sr) if sr is not None else np.nan)
                except Exception:
                    xs.append(np.nan)
                ys.append(float(w))
                labels.append(edge)
            sr_fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text", text=labels, textposition="top center"))
        sr_fig.update_layout(
            title="Sharpe vs Weight",
            template="plotly_dark",
            xaxis_title="Sharpe (SR)",
            yaxis_title="Weight",
        )

        # ---- 3) Recommendations chart ----
        rec_fig = go.Figure()
        if recs:
            edges = []
            vals = []
            for k, v in recs.items():
                if isinstance(v, dict):
                    num = None
                    for key in ("weight", "value", "score", "suggested", "confidence"):
                        if key in v and isinstance(v[key], (int, float)):
                            num = v[key]
                            break
                    if num is None:
                        for vv in v.values():
                            if isinstance(vv, (int, float)):
                                num = vv
                                break
                    val = float(num) if num is not None else np.nan
                else:
                    try:
                        val = float(v)
                    except Exception:
                        val = np.nan
                edges.append(k)
                vals.append(val)
            colors = ["limegreen" if (isinstance(v, (int, float)) and v >= 0.5) else "firebrick" for v in vals]
            rec_fig.add_trace(go.Bar(x=edges, y=vals, marker_color=colors))
        rec_fig.update_layout(
            title="Governor Recommendations",
            template="plotly_dark",
            xaxis_title="Edge",
            yaxis_title="Suggested Weight",
        )

        # ---- 4) Weight evolution from history ----
        hist = dm.get_weight_history()
        ew_fig = go.Figure()
        if not hist.empty:
            for edge, g in hist.groupby("edge"):
                ew_fig.add_trace(go.Scatter(x=g["timestamp"], y=g["weight"], mode="lines", name=str(edge)))
        ew_fig.update_layout(
            title="Weight Evolution",
            template="plotly_dark",
            xaxis_title="Time",
            yaxis_title="Weight",
        )

        return w_fig, sr_fig, rec_fig, ew_fig