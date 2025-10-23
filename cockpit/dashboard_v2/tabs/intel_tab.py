

from dash import html, dcc

def create_intel_layout():
    try:
        from intelligence.news_summarizer import NewsSummarizer
        ns = NewsSummarizer()
        summary_text = ns.summarize()
    except Exception as e:
        summary_text = f"[INTEL] News summarizer unavailable or failed: {e}"

    return html.Div(
        [
            html.Div(
                [
                    html.H3("Market Intelligence", style={"color": "#e0e0e0", "marginBottom": "10px"}),
                    html.Button(
                        "🔄 Refresh Intel",
                        id="intel_refresh_button",
                        n_clicks=0,
                        style={
                            "backgroundColor": "#222",
                            "color": "#eee",
                            "border": "1px solid #555",
                            "borderRadius": "6px",
                            "padding": "6px 12px",
                            "marginBottom": "15px",
                            "cursor": "pointer",
                        },
                    ),
                    html.Pre(
                        summary_text,
                        id="intel_summary_box",
                        style={
                            "whiteSpace": "pre-wrap",
                            "fontSize": "17px",
                            "fontFamily": "Menlo, Consolas, monospace",
                            "padding": "20px",
                            "backgroundColor": "#0c0c0c",
                            "color": "#e0e0e0",
                            "borderRadius": "10px",
                            "border": "1px solid #333",
                            "lineHeight": "1.6",
                            "maxHeight": "80vh",
                            "overflowY": "auto",
                        },
                    ),
                ],
                style={
                    "padding": "18px",
                    "backgroundColor": "#161b22",
                    "borderRadius": "12px",
                    "width": "95%",
                    "margin": "auto",
                    "boxShadow": "0 0 12px rgba(0,0,0,0.4)",
                },
            ),
        ]
    )