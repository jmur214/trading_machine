# cockpit/dashboard/tabs/governor_tab.py
from __future__ import annotations
from dash import dcc, html

def governor_layout():
    return html.Div(
        style={"backgroundColor": "#161b22", "padding": "16px 18px", "borderRadius": "12px"},
        children=[
            html.H3("Governor Intelligence", style={"marginTop": 0, "color": "#e0e0e0"}),
            html.Div([dcc.Graph(id="gov_weight_chart")], style={"margin": "12px 0"}),
            html.Div([dcc.Graph(id="gov_sr_weight_scatter")], style={"margin": "12px 0"}),
            html.Div([dcc.Graph(id="gov_recommendation_chart")], style={"margin": "12px 0"}),
            html.Div([dcc.Graph(id="gov_weight_evolution")], style={"margin": "12px 0"}),
        ],
    )
