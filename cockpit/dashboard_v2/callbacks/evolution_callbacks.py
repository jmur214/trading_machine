# cockpit/dashboard_v2/callbacks/evolution_callbacks.py
"""Callbacks for the Evolution tab - WFO results and genome registry visualization."""
from __future__ import annotations

import json
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, html, dash_table

# Paths - Adjusted to point to the actual output of the Evolution Controller
EDGE_RESULTS_JSON = Path("data/research/edge_results.json")
# We also check for the summary log or other artifacts since parquet might be missing
GENOME_REGISTRY_PATH = Path("data/governor/edges.yml") # Updated from genome_registry.json

# Design tokens
CARD_STYLE = {
    "background": "rgba(15, 20, 26, 0.85)",
    "backdropFilter": "blur(20px)",
    "border": "1px solid rgba(56, 68, 77, 0.4)",
    "borderRadius": "16px",
    "padding": "20px",
    "boxShadow": "0 4px 12px rgba(0, 0, 0, 0.4)",
    "textAlign": "center",
    "position": "relative",
    "overflow": "hidden",
}


def register_evolution_callbacks(app):
    """Register all Evolution tab callbacks."""

    @app.callback(
        Output("evo_stats_row", "children"),
        Input("analytics_sub_tab_selector", "value"),
    )
    def update_stats_row(sub_tab):
        """Generate stats cards from edge results."""
        if sub_tab != "evolution":
            return []

        genomes = _load_genome_registry()
        
        # Calculate statistics
        total_strategies = len(genomes)
        
        # Calculate validated vs rejected from registry status
        validated = len([g for g in genomes if g.get("status") == "active"])
        candidates = len([g for g in genomes if g.get("status") == "candidate"])
        rejected = len([g for g in genomes if g.get("status") == "failed"])
        
        # Determine average Sharpe (placeholder if not stored in registry)
        avg_sharpe = "N/A"
        
        return [
            _stat_card("Total Genomes", str(total_strategies), "#58a6ff"),
            _stat_card("Active Strategies", str(validated), "#3fb950"),
            _stat_card("Candidates Pending", str(candidates), "#a371f7"),
            _stat_card("Rejected", str(rejected), "#f85149"),
        ]

    # ... (Keep Heatmap and Dist logic similar, or stub if data missing)
    @app.callback(
        Output("evo_wfo_heatmap", "figure"),
        Input("analytics_sub_tab_selector", "value"),
    )
    def update_wfo_heatmap(sub_tab):
        if sub_tab != "evolution":
            return go.Figure()
        return _empty_chart("WFO Stability", "Data pipeline integrating...")

    @app.callback(
        Output("evo_performance_dist", "figure"),
        Input("analytics_sub_tab_selector", "value"),
    )
    def update_performance_distribution(sub_tab):
        if sub_tab != "evolution":
            return go.Figure()
        return _empty_chart("Performance Distribution", "Data pipeline integrating...")

    @app.callback(
        Output("evo_registry_container", "children"),
        Input("analytics_sub_tab_selector", "value"),
    )
    def update_genome_registry(sub_tab):
        """Load and display the genome registry table."""
        if sub_tab != "evolution":
            return html.Div()

        genomes = _load_genome_registry()
        
        if not genomes:
            return html.Div(
                style={"display": "flex", "alignItems": "center", "justifyContent": "center", "height": "200px", "color": "#6e7681", "fontSize": "14px"},
                children=["No genomes discovered yet. Run discovery engine to populate."],
            )

        records = []
        for g in genomes:
            # Flatten params for display
            params_str = ", ".join(f"{k}={v}" for k,v in g.get("params", {}).items() if k != "genes")
            if "genes" in g.get("params", {}):
                params_str = f"{len(g['params']['genes'])} genes"
                
            record = {
                "edge_id": g.get("edge_id", "unknown"),
                "category": g.get("category", "unknown"),
                "status": g.get("status", "unknown"),
                "params": params_str,
                "version": g.get("version", "1.0.0"),
            }
            records.append(record)
        
        df = pd.DataFrame(records)

        return dash_table.DataTable(
            data=df.to_dict("records"),
            columns=[
                {"name": "Edge ID", "id": "edge_id"},
                {"name": "Category", "id": "category"},
                {"name": "Status", "id": "status"},
                {"name": "Parameters", "id": "params"},
                {"name": "Version", "id": "version"},
            ],
            style_table={"overflowX": "auto"},
            style_header={
                "backgroundColor": "rgba(22, 27, 34, 0.9)",
                "color": "#c9d1d9",
                "fontWeight": "600",
                "fontSize": "11px",
                "textTransform": "uppercase",
                "letterSpacing": "0.05em",
                "border": "none",
                "borderBottom": "1px solid rgba(56, 68, 77, 0.6)",
                "padding": "12px 16px",
            },
            style_cell={
                "backgroundColor": "transparent",
                "color": "#c9d1d9",
                "fontSize": "13px",
                "border": "none",
                "borderBottom": "1px solid rgba(56, 68, 77, 0.3)",
                "padding": "12px 16px",
                "textAlign": "left",
            },
            style_data_conditional=[
                {"if": {"filter_query": "{status} = 'active'", "column_id": "status"}, "color": "#3fb950", "fontWeight": "600"},
                {"if": {"filter_query": "{status} = 'failed'", "column_id": "status"}, "color": "#f85149", "fontWeight": "600"},
                {"if": {"filter_query": "{status} = 'candidate'", "column_id": "status"}, "color": "#a371f7", "fontWeight": "600"},
            ],
            page_size=10,
            sort_action="native",
        )


def _load_genome_registry() -> list:
    """Load genome registry from YAML (edges.yml)."""
    try:
        import yaml
        if GENOME_REGISTRY_PATH.exists():
            with open(GENOME_REGISTRY_PATH, "r") as f:
                data = yaml.safe_load(f)
                return data.get("edges", [])
    except Exception as e:
        print(f"[Evolution] Error loading genome registry: {e}")
    return []


def _stat_card(label: str, value: str, color: str):
    """Create a mini stat card."""
    return html.Div(
        style={
            **CARD_STYLE,
        },
        children=[
            html.Div(style={
                "position": "absolute", "top": "0", "left": "0", "right": "0", "height": "3px",
                "background": f"linear-gradient(90deg, {color}, transparent)",
            }),
            html.Div(label, style={
                "fontSize": "11px", "fontWeight": "500", "color": "#6e7681",
                "textTransform": "uppercase", "letterSpacing": "0.05em", "marginBottom": "8px",
            }),
            html.Div(value, style={
                "fontSize": "24px", "fontWeight": "700", "color": color, "letterSpacing": "-0.02em",
            }),
        ],
    )


def _empty_chart(title: str, subtitle: str = "") -> go.Figure:
    """Create an empty placeholder chart with a message."""
    fig = go.Figure()
    fig.add_annotation(
        text=f"<b>{title}</b><br><span style='color:#6e7681;font-size:12px'>{subtitle}</span>",
        xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
        font=dict(size=14, color="#c9d1d9", family="Inter, sans-serif"), align="center",
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(l=20, r=20, t=20, b=20),
    )
    return fig
