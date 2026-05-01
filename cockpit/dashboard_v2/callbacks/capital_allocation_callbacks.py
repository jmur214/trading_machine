"""Callbacks for the Capital-Allocation Diagnostic tab.

Wires the run-uuid dropdown + cap input to the three panels (table, scatter,
binding time-series) plus the optional regime-breakdown bonus panel.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, html

from ..utils.chart_helpers import empty_chart, get_chart_layout
from ..utils.styles import COLORS, KPI_CARD_STYLE
from ..utils.capital_allocation_loader import (
    DEFAULT_FILL_SHARE_CAP,
    ROLLING_WINDOW_DAYS,
    cap_binding_summary,
    compute_edge_summary,
    compute_regime_breakdown,
    compute_rolling_fill_share,
    flag_rivalry,
    load_trades,
)


_STATUS_COLOR = {
    "active": COLORS["accent_green"],
    "paused": COLORS["accent_yellow"],
    "retired": COLORS["text_dim"],
    "archived": COLORS["text_dim"],
    "unknown": COLORS["text_muted"],
}


def _status_marker(status: str) -> str:
    return _STATUS_COLOR.get(status, COLORS["text_muted"])


def _kpi_card(label: str, value: str, accent: str) -> html.Div:
    return html.Div(
        style={
            **KPI_CARD_STYLE,
            "borderLeft": f"3px solid {accent}",
        },
        children=[
            html.Div(label, style={"color": COLORS["text_muted"], "fontSize": "11px", "textTransform": "uppercase", "letterSpacing": "0.05em"}),
            html.Div(value, style={"color": COLORS["text_primary"], "fontSize": "20px", "fontWeight": "700", "marginTop": "6px"}),
        ],
    )


def compute_capital_allocation_view(run_uuid, cap_value, window_value):
    """Pure-function callback body. Returns the 6-tuple of Dash outputs.

    Exposed at module level so tests can call it without going through the
    Dash callback wrapper.
    """
    cap = float(cap_value) if cap_value else DEFAULT_FILL_SHARE_CAP
    window = int(window_value) if window_value else ROLLING_WINDOW_DAYS

    if not run_uuid:
        empty_msg = "Select a run UUID."
        return [], empty_chart(empty_msg), empty_chart(empty_msg), "", empty_chart(empty_msg), html.Div()

    try:
        trades = load_trades(run_uuid)
    except Exception as exc:
        err = f"Load error: {exc}"
        return [], empty_chart(err), empty_chart(err), err, empty_chart(err), html.Div()

    if trades.empty:
        empty_msg = "No fills in this run."
        return [], empty_chart(empty_msg), empty_chart(empty_msg), empty_msg, empty_chart(empty_msg), html.Div()

    # ---- Panel 1: per-edge summary table ----
    summary = flag_rivalry(compute_edge_summary(trades))

    def _fmt_pct(v):
        return f"{v * 100:.2f}%"

    def _fmt_money(v):
        return f"${v:,.2f}"

    table_data = []
    for _, r in summary.iterrows():
        table_data.append({
            "edge": r["edge"],
            "status": r["status"],
            "fill_count": int(r["fill_count"]),
            "fill_pct_disp": _fmt_pct(r["fill_pct"]),
            "total_pnl_disp": _fmt_money(r["total_pnl"]),
            "pnl_pct_disp": _fmt_pct(r["pnl_pct"]),
            "mean_pnl_disp": _fmt_money(r["mean_pnl_per_fill"]),
            "tier": r["tier"],
            "rivalry_flag": bool(r["rivalry_flag"]),
        })

    # ---- Panel 2: fill-share vs PnL-share scatter ----
    scatter = go.Figure()
    if not summary.empty:
        x = summary["fill_pct"].values * 100.0
        y = summary["pnl_pct"].values * 100.0
        colors = [_status_marker(s) for s in summary["status"].values]
        sizes = (summary["fill_count"].clip(lower=4) ** 0.5).values + 6.0
        text = [
            f"{e}<br>status={s}<br>fills={n:,}<br>PnL=${p:,.0f}"
            for e, s, n, p in zip(summary["edge"], summary["status"], summary["fill_count"], summary["total_pnl"])
        ]
        scatter.add_trace(go.Scatter(
            x=x, y=y, mode="markers+text", text=summary["edge"],
            textposition="top center",
            hovertext=text, hoverinfo="text",
            marker=dict(color=colors, size=sizes, line=dict(width=1, color="rgba(255,255,255,0.4)")),
            showlegend=False,
            textfont=dict(size=9, color=COLORS["text_secondary"]),
        ))
        # diagonal y = x
        lim = max(x.max(), y.max(), 5.0) * 1.1
        llim = min(x.min(), y.min(), -5.0) * 1.1
        scatter.add_trace(go.Scatter(
            x=[llim, lim], y=[llim, lim], mode="lines",
            line=dict(color=COLORS["text_muted"], dash="dash", width=1),
            hoverinfo="skip", showlegend=False, name="y=x",
        ))
        # zero-PnL reference line
        scatter.add_trace(go.Scatter(
            x=[0, lim], y=[0, 0], mode="lines",
            line=dict(color=COLORS["accent_red"], dash="dot", width=1),
            hoverinfo="skip", showlegend=False, name="zero PnL",
        ))
    scatter.update_layout(get_chart_layout(
        xaxis_title="Fill share (%)",
        yaxis_title="PnL contribution (%)",
        hovermode="closest",
    ))

    # ---- Panel 3: rolling fill share + cap line ----
    rolling = compute_rolling_fill_share(trades, window_days=window)
    binding_fig = go.Figure()
    binding_text = ""
    if not rolling.empty:
        # Only plot top edges by total fills to avoid line spaghetti
        top_edges = (
            rolling.sum(axis=0).sort_values(ascending=False).head(8).index.tolist()
        )
        palette = ["#58a6ff", "#a371f7", "#d29922", "#f85149", "#3fb950",
                   "#79c0ff", "#ff7b72", "#56d364"]
        for i, edge in enumerate(top_edges):
            color = palette[i % len(palette)]
            binding_fig.add_trace(go.Scatter(
                x=rolling.index, y=rolling[edge].values * 100.0,
                mode="lines", name=edge,
                line=dict(width=2, color=color),
                hovertemplate=f"<b>{edge}</b><br>%{{x}}<br>share=%{{y:.1f}}%<extra></extra>",
            ))
        # cap line
        binding_fig.add_hline(
            y=cap * 100.0, line_dash="dash", line_color=COLORS["accent_red"],
            annotation_text=f"cap = {cap:.2f}",
            annotation_position="top right",
            annotation_font_color=COLORS["accent_red"],
        )

        binding = cap_binding_summary(rolling, cap=cap)
        n_days = len(binding)
        n_binding = int(binding["binding"].sum())
        top_binders = binding[binding["binding"]]["max_edge"].value_counts().head(3)
        top_str = ", ".join(f"{e} ({n} days)" for e, n in top_binders.items()) or "none"
        binding_text = (
            f"Cap-binding days: {n_binding} / {n_days} "
            f"({(n_binding / n_days * 100.0) if n_days else 0:.1f}% of trading days). "
            f"Top binders: {top_str}. "
            f"Rolling window: {window} days. Slack: 0.5pp."
        )
    binding_fig.update_layout(get_chart_layout(
        xaxis_title="",
        yaxis_title="Rolling fill share (%)",
        legend=dict(orientation="h", y=-0.18, yanchor="top", x=0, xanchor="left", font=dict(size=10)),
    ))

    # ---- Panel 4 (bonus): per-regime PnL by edge ----
    regime_df = compute_regime_breakdown(trades)
    regime_fig = go.Figure()
    if regime_df.empty:
        regime_fig = empty_chart("No regime_label column in this trade log.")
    else:
        pivot = regime_df.pivot(index="edge", columns="regime_label", values="total_pnl").fillna(0.0)
        edge_order = summary["edge"].tolist() if not summary.empty else pivot.index.tolist()
        pivot = pivot.reindex(edge_order).fillna(0.0)
        regime_palette = {
            "robust_expansion": "#3fb950",
            "emerging_expansion": "#56d364",
            "cautious_decline": "#d29922",
            "market_turmoil": "#f85149",
            "transitional": "#a371f7",
        }
        for col in pivot.columns:
            regime_fig.add_trace(go.Bar(
                y=pivot.index, x=pivot[col].values, name=col,
                orientation="h",
                marker_color=regime_palette.get(col, "#58a6ff"),
                hovertemplate=f"<b>%{{y}}</b><br>{col}: $%{{x:,.0f}}<extra></extra>",
            ))
        regime_fig.update_layout(get_chart_layout(
            barmode="relative",
            xaxis_title="Realised PnL ($)",
            legend=dict(orientation="h", y=-0.18, yanchor="top", x=0, xanchor="left", font=dict(size=10)),
        ))

    # ---- Headline KPI strip ----
    rivalry_n = int(summary["rivalry_flag"].sum())
    bottom3 = summary.head(3)["fill_pct"].sum() * 100.0 if len(summary) >= 3 else summary["fill_pct"].sum() * 100.0
    bottom3_pnl = summary.head(3)["total_pnl"].sum() if len(summary) >= 3 else summary["total_pnl"].sum()
    binding_pct = (
        cap_binding_summary(rolling, cap=cap)["binding"].mean() * 100.0
        if not rolling.empty else 0.0
    )
    headline = html.Div(
        style={"display": "grid", "gridTemplateColumns": "repeat(4, minmax(0, 1fr))", "gap": "16px"},
        children=[
            _kpi_card(
                "Rivalry-flagged edges",
                f"{rivalry_n}",
                COLORS["accent_red"] if rivalry_n > 0 else COLORS["accent_green"],
            ),
            _kpi_card(
                "Top-3-by-fills share",
                f"{bottom3:.1f}%",
                COLORS["accent_yellow"] if bottom3 > 70.0 else COLORS["accent_blue"],
            ),
            _kpi_card(
                "Top-3-by-fills PnL",
                f"${bottom3_pnl:,.0f}",
                COLORS["accent_red"] if bottom3_pnl < 0 else COLORS["accent_green"],
            ),
            _kpi_card(
                f"Cap-binding days @ cap={cap:.2f}",
                f"{binding_pct:.1f}%",
                COLORS["accent_red"] if binding_pct > 50.0 else COLORS["accent_blue"],
            ),
        ],
    )

    return table_data, scatter, binding_fig, binding_text, regime_fig, headline


def register_capital_allocation_callbacks(app):
    """Register the capital-allocation callback against a Dash app."""
    @app.callback(
        Output("capalloc_table", "data"),
        Output("capalloc_scatter", "figure"),
        Output("capalloc_binding_chart", "figure"),
        Output("capalloc_binding_summary", "children"),
        Output("capalloc_regime", "figure"),
        Output("capalloc_headline", "children"),
        Input("capalloc_run_uuid", "value"),
        Input("capalloc_cap", "value"),
        Input("capalloc_window", "value"),
        prevent_initial_call=False,
    )
    def _update(run_uuid, cap_value, window_value):
        return compute_capital_allocation_view(run_uuid, cap_value, window_value)
