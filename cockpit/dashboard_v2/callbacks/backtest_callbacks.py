# cockpit/dashboard_v2/callbacks/backtest_callbacks.py
"""Callbacks for the Backtest tab — run backtests/benchmarks, stream output."""
from __future__ import annotations

import json
from pathlib import Path

from dash import Input, Output, State, html, no_update, ctx
from ..utils.styles import CARD_STYLE, COLORS, KPI_CARD_STYLE, accent_line, status_badge
from ..utils import command_runner


def register_backtest_callbacks(app):

    # ---- Run Backtest or Benchmark ----
    @app.callback(
        Output("bt-process-id", "data"),
        Output("bt-output", "children"),
        Output("bt-output-offset", "data"),
        Output("bt-poll", "disabled"),
        Output("bt-run-btn", "disabled"),
        Output("bt-bench-btn", "disabled"),
        Output("bt-stop-btn", "disabled"),
        Output("bt-status-badge", "children"),
        Output("bt-status-badge", "style"),
        Input("bt-run-btn", "n_clicks"),
        Input("bt-bench-btn", "n_clicks"),
        State("bt-start-date", "value"),
        State("bt-end-date", "value"),
        State("bt-capital", "value"),
        State("bt-env", "value"),
        State("bt-options", "value"),
        prevent_initial_call=True,
    )
    def run_backtest_or_benchmark(run_clicks, bench_clicks, start, end, capital, env, options):
        triggered = ctx.triggered_id
        if triggered not in ("bt-run-btn", "bt-bench-btn"):
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

        if command_runner.is_any_running():
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update, "BUSY", status_badge("running")

        is_benchmark = (triggered == "bt-bench-btn")
        cmd_key = "benchmark" if is_benchmark else "backtest"
        args = []

        if start:
            args.extend(["--start", str(start)])
        if end:
            args.extend(["--end", str(end)])
        if capital:
            args.extend(["--capital", str(capital)])

        if not is_benchmark:
            if env:
                args.extend(["--env", str(env)])
            opts = options or []
            if "fresh" in opts:
                args.append("--fresh")
            if "discover" in opts:
                args.append("--discover")

        process_id = command_runner.start_command(cmd_key, args)
        label = "BENCHMARK" if is_benchmark else "BACKTEST"

        return (
            process_id,
            f"Starting {label}...\n",
            0,
            False,       # enable polling
            True,        # disable run btn
            True,        # disable bench btn
            False,       # enable stop btn
            "RUNNING",
            status_badge("running"),
        )

    # ---- Poll output ----
    @app.callback(
        Output("bt-output", "children", allow_duplicate=True),
        Output("bt-output-offset", "data", allow_duplicate=True),
        Output("bt-poll", "disabled", allow_duplicate=True),
        Output("bt-run-btn", "disabled", allow_duplicate=True),
        Output("bt-bench-btn", "disabled", allow_duplicate=True),
        Output("bt-stop-btn", "disabled", allow_duplicate=True),
        Output("bt-status-badge", "children", allow_duplicate=True),
        Output("bt-status-badge", "style", allow_duplicate=True),
        Output("bt-elapsed", "children"),
        Input("bt-poll", "n_intervals"),
        State("bt-process-id", "data"),
        State("bt-output-offset", "data"),
        State("bt-output", "children"),
        prevent_initial_call=True,
    )
    def poll_backtest(n, process_id, offset, current_output):
        if not process_id:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, ""

        status = command_runner.get_status(process_id)
        output = command_runner.get_output(process_id, offset)

        elapsed_str = f"{status['elapsed']}s"
        text = (current_output or "") + output["text"]

        if output["done"]:
            final_status = "COMPLETE" if status["status"] == "complete" else "ERROR"
            badge_style = status_badge("complete") if status["status"] == "complete" else status_badge("error")
            return text, output["offset"], True, False, False, True, final_status, badge_style, elapsed_str
        else:
            return text, output["offset"], False, True, True, False, "RUNNING", status_badge("running"), elapsed_str

    # ---- Stop ----
    @app.callback(
        Output("bt-status-badge", "children", allow_duplicate=True),
        Output("bt-status-badge", "style", allow_duplicate=True),
        Input("bt-stop-btn", "n_clicks"),
        State("bt-process-id", "data"),
        prevent_initial_call=True,
    )
    def stop_backtest(n, process_id):
        if process_id:
            command_runner.stop_command(process_id)
        return "STOPPED", status_badge("error")

    # ---- Last benchmark results ----
    @app.callback(
        Output("bt-last-results", "children"),
        Input("bt-poll", "disabled"),
        prevent_initial_call=False,
    )
    def load_last_results(_disabled):
        report_path = Path("data/research/benchmark_report.json")
        if not report_path.exists():
            return html.Div()

        try:
            with open(report_path) as f:
                report = json.load(f)
        except Exception:
            return html.Div()

        portfolio = report.get("portfolio", {})
        if not portfolio:
            return html.Div()

        kpi_items = [
            ("Total Return (%)", COLORS["accent_blue"]),
            ("CAGR (%)", COLORS["accent_purple"]),
            ("Sharpe Ratio", COLORS["accent_green"]),
            ("Max Drawdown (%)", COLORS["accent_red"]),
            ("Win Rate (%)", COLORS["accent_green"]),
            ("Profit Factor", COLORS["accent_yellow"]),
            ("Trades", COLORS["text_muted"]),
        ]

        cards = []
        for key, color in kpi_items:
            val = portfolio.get(key, "N/A")
            if val is None:
                val = "N/A"
            elif isinstance(val, float):
                val = f"{val:.2f}" if "Ratio" not in key and "Factor" not in key else f"{val:.3f}"

            cards.append(
                html.Div(
                    style={**KPI_CARD_STYLE, "position": "relative", "overflow": "hidden"},
                    children=[
                        html.Div(style=accent_line(color)),
                        html.Div(str(key), style={
                            "fontSize": "11px", "fontWeight": "500", "color": COLORS["text_dim"],
                            "textTransform": "uppercase", "letterSpacing": "0.05em", "marginBottom": "6px",
                        }),
                        html.Div(str(val), style={
                            "fontSize": "18px", "fontWeight": "700", "color": COLORS["text_secondary"],
                        }),
                    ],
                )
            )

        ts = report.get("timestamp", "")
        return html.Div(
            style=CARD_STYLE,
            children=[
                html.Div(style={"display": "flex", "alignItems": "center", "gap": "12px", "marginBottom": "16px"}, children=[
                    html.H4("Last Benchmark Results", style={"margin": "0", "color": COLORS["text_primary"], "fontSize": "14px"}),
                    html.Span(ts[:19] if ts else "", style={"fontSize": "12px", "color": COLORS["text_dim"]}),
                ]),
                html.Div(cards, style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(auto-fit, minmax(130px, 1fr))",
                    "gap": "12px",
                }),
            ],
        )
