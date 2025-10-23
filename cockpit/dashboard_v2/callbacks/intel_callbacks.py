from dash import Input, Output, html

def register_intel_callbacks(app):
    try:
        from intelligence.news_summarizer import NewsSummarizer
    except Exception:
        NewsSummarizer = None

    @app.callback(
        Output("intel_summary_box", "children"),
        Input("intel_refresh_button", "n_clicks"),
        prevent_initial_call=True,
    )
    def refresh_intel_summary(_n):
        if not NewsSummarizer:
            return html.Pre("[INTEL] NewsSummarizer unavailable.", style={"color": "#aaa"})
        try:
            ns = NewsSummarizer()
            summary_text = ns.summarize()
            return summary_text
        except Exception as e:
            return html.Pre(f"[INTEL] Refresh failed: {e}", style={"color": "#f55"})