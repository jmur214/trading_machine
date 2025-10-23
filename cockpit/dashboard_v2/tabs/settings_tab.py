# cockpit/dashboard/tabs/settings_tab.py
from __future__ import annotations
from dash import html

def settings_layout():
    return html.Div(
        children=[
            html.H3("Settings"),
            html.P("Strategy and dashboard settings will appear here."),
        ]
    )
