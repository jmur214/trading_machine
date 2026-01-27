# cockpit/dashboard/tabs/intel_tab.py
"""Intel tab - Market intelligence and news summary."""
from __future__ import annotations
from dash import html, dcc

# ============================================
# DESIGN TOKENS
# ============================================
CARD_STYLE = {
    "background": "rgba(15, 20, 26, 0.85)",
    "backdropFilter": "blur(20px)",
    "border": "1px solid rgba(56, 68, 77, 0.4)",
    "borderRadius": "16px",
    "padding": "24px",
    "boxShadow": "0 4px 12px rgba(0, 0, 0, 0.4)",
}

SECTION_HEADER = {
    "display": "flex",
    "alignItems": "center",
    "gap": "12px",
    "marginBottom": "16px",
    "paddingBottom": "12px",
    "borderBottom": "1px solid rgba(56, 68, 77, 0.4)",
}


def create_intel_layout():
    """Intel tab with market news and intelligence summary."""
    try:
        from intelligence.news_summarizer import NewsSummarizer
        ns = NewsSummarizer()
        summary_text = ns.summarize()
    except Exception as e:
        summary_text = f"[INTEL] News summarizer unavailable: {e}"

    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Market Intelligence", style={"margin": "0", "color": "#f0f6fc"}),
                    html.Span("AI-Powered News Analysis", style={
                        "background": "rgba(163, 113, 247, 0.15)",
                        "color": "#a371f7",
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "padding": "4px 12px",
                        "borderRadius": "20px",
                    }),
                ]
            ),
            
            # Controls
            html.Div(
                style={"marginBottom": "24px"},
                children=[
                    html.Button(
                        "Refresh Intel",
                        id="intel_refresh_button",
                        n_clicks=0,
                    ),
                ],
            ),
            
            # Intel Summary Card
            html.Div(
                style=CARD_STYLE,
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("News Summary", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                    ]),
                    html.Pre(
                        summary_text,
                        id="intel_summary_box",
                        style={
                            "whiteSpace": "pre-wrap",
                            "fontSize": "14px",
                            "fontFamily": "'SF Mono', 'Fira Code', 'Consolas', monospace",
                            "padding": "20px",
                            "backgroundColor": "rgba(10, 14, 20, 0.6)",
                            "color": "#c9d1d9",
                            "borderRadius": "10px",
                            "border": "1px solid rgba(56, 68, 77, 0.3)",
                            "lineHeight": "1.6",
                            "maxHeight": "600px",
                            "overflowY": "auto",
                            "margin": "0",
                        },
                    ),
                ],
            ),
        ],
    )