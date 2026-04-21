# cockpit/dashboard_v2/callbacks/command_callbacks.py
"""Callbacks for the Command Center tab — run any system command, stream output."""
from __future__ import annotations

from dash import Input, Output, State, no_update, ctx
from ..utils.styles import status_badge
from ..utils import command_runner
from ..utils.command_runner import COMMANDS


def register_command_callbacks(app):

    # ---- Update description when command changes ----
    @app.callback(
        Output("cmd-description", "children"),
        Output("cmd-params-panel", "style"),
        Output("cmd-params-dates", "style"),
        Output("cmd-params-backtest-opts", "style"),
        Input("cmd-selector", "value"),
    )
    def update_command_info(cmd_key):
        from ..utils.styles import CARD_STYLE

        desc = COMMANDS.get(cmd_key, {}).get("description", "")

        # Show params panel for commands that accept date/capital args
        has_params = cmd_key in ("backtest", "benchmark", "update_data")
        has_bt_opts = cmd_key == "backtest"

        panel_style = {**CARD_STYLE, "marginBottom": "24px"}
        if not has_params and not has_bt_opts:
            panel_style["display"] = "none"

        dates_style = {} if has_params else {"display": "none"}
        bt_opts_style = {} if has_bt_opts else {"display": "none"}

        return desc, panel_style, dates_style, bt_opts_style

    # ---- Run command ----
    @app.callback(
        Output("cmd-process-id", "data"),
        Output("cmd-output", "children"),
        Output("cmd-output-offset", "data"),
        Output("cmd-poll", "disabled"),
        Output("cmd-run-btn", "disabled"),
        Output("cmd-stop-btn", "disabled"),
        Output("cmd-status-badge", "children"),
        Output("cmd-status-badge", "style"),
        Input("cmd-run-btn", "n_clicks"),
        State("cmd-selector", "value"),
        State("cmd-param-start", "value"),
        State("cmd-param-end", "value"),
        State("cmd-param-capital", "value"),
        State("cmd-param-bt-opts", "value"),
        State("cmd-param-extra", "value"),
        prevent_initial_call=True,
    )
    def run_command(n_clicks, cmd_key, start, end, capital, bt_opts, extra_args):
        if not cmd_key:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

        if command_runner.is_any_running():
            return no_update, no_update, no_update, no_update, no_update, no_update, "BUSY", status_badge("running")

        args = []

        # Add date/capital params for commands that support them
        if cmd_key in ("backtest", "benchmark"):
            if start:
                args.extend(["--start", str(start)])
            if end:
                args.extend(["--end", str(end)])
            if capital:
                args.extend(["--capital", str(capital)])

        # Backtest-specific options
        if cmd_key == "backtest":
            opts = bt_opts or []
            if "fresh" in opts:
                args.append("--fresh")
            if "discover" in opts:
                args.append("--discover")

        # Extra arguments (split on spaces)
        if extra_args and extra_args.strip():
            args.extend(extra_args.strip().split())

        process_id = command_runner.start_command(cmd_key, args)
        label = COMMANDS[cmd_key]["label"]

        return (
            process_id,
            f"Starting {label}...\n",
            0,
            False,       # enable polling
            True,        # disable run btn
            False,       # enable stop btn
            "RUNNING",
            status_badge("running"),
        )

    # ---- Poll output ----
    @app.callback(
        Output("cmd-output", "children", allow_duplicate=True),
        Output("cmd-output-offset", "data", allow_duplicate=True),
        Output("cmd-poll", "disabled", allow_duplicate=True),
        Output("cmd-run-btn", "disabled", allow_duplicate=True),
        Output("cmd-stop-btn", "disabled", allow_duplicate=True),
        Output("cmd-status-badge", "children", allow_duplicate=True),
        Output("cmd-status-badge", "style", allow_duplicate=True),
        Output("cmd-elapsed", "children"),
        Input("cmd-poll", "n_intervals"),
        State("cmd-process-id", "data"),
        State("cmd-output-offset", "data"),
        State("cmd-output", "children"),
        prevent_initial_call=True,
    )
    def poll_command(n, process_id, offset, current_output):
        if not process_id:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update, ""

        status = command_runner.get_status(process_id)
        output = command_runner.get_output(process_id, offset)

        elapsed_str = f"{status['elapsed']}s"
        text = (current_output or "") + output["text"]

        if output["done"]:
            final_status = "COMPLETE" if status["status"] == "complete" else "ERROR"
            badge_style = status_badge("complete") if status["status"] == "complete" else status_badge("error")
            return text, output["offset"], True, False, True, final_status, badge_style, elapsed_str
        else:
            return text, output["offset"], False, True, False, "RUNNING", status_badge("running"), elapsed_str

    # ---- Stop command ----
    @app.callback(
        Output("cmd-status-badge", "children", allow_duplicate=True),
        Output("cmd-status-badge", "style", allow_duplicate=True),
        Input("cmd-stop-btn", "n_clicks"),
        State("cmd-process-id", "data"),
        prevent_initial_call=True,
    )
    def stop_command(n, process_id):
        if process_id:
            command_runner.stop_command(process_id)
        return "STOPPED", status_badge("error")
