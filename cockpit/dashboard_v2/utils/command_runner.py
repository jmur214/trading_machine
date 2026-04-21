# cockpit/dashboard_v2/utils/command_runner.py
"""Subprocess process manager for running system commands from the dashboard.

Architecture:
- Module-level dict `_processes` tracks running/completed processes.
- Each command spawns via subprocess.Popen, stdout+stderr redirected to a temp log file.
- Dashboard callbacks poll `get_status()` and `get_output()` via dcc.Interval.
- GIL provides sufficient thread safety for simple dict reads/writes.
"""
from __future__ import annotations

import os
import sys
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Project root — three levels up from utils/command_runner.py
PROJECT_ROOT = str(Path(__file__).resolve().parents[3])

# ============================================
# COMMAND REGISTRY
# ============================================
COMMANDS: dict[str, dict[str, Any]] = {
    "backtest": {
        "label": "Run Backtest",
        "base_cmd": [sys.executable, "-m", "scripts.run_backtest"],
        "description": "Run full historical backtest with active strategies.",
    },
    "benchmark": {
        "label": "Run Benchmark",
        "base_cmd": [sys.executable, "-m", "scripts.run_benchmark"],
        "description": "Run standardized performance benchmark with SPY comparison.",
    },
    "update_data": {
        "label": "Update Data",
        "base_cmd": [sys.executable, "-m", "scripts.update_data"],
        "description": "Fetch latest market data for all universe symbols.",
    },
    "discovery": {
        "label": "Run Discovery",
        "base_cmd": [sys.executable, "-m", "scripts.run_evolution_cycle"],
        "description": "Run autonomous strategy discovery and evolution cycle.",
    },
    "autonomous": {
        "label": "Autonomous Cycle",
        "base_cmd": [sys.executable, "-m", "scripts.run_autonomous_cycle"],
        "description": "Full cycle: data > hunt > validate > learn > execute.",
    },
    "healthcheck": {
        "label": "System Health Check",
        "base_cmd": [sys.executable, "-m", "scripts.run_healthcheck"],
        "description": "Run tests, dev backtest, and invariant checks.",
    },
    "edge_feedback": {
        "label": "Edge Feedback",
        "base_cmd": [sys.executable, "-m", "analytics.edge_feedback"],
        "description": "Update strategy weights from latest trade results.",
    },
}


# ============================================
# PROCESS STATE
# ============================================
@dataclass
class ProcessInfo:
    process: subprocess.Popen
    command_key: str
    command_label: str
    log_path: str
    start_time: float
    status: str = "running"       # running | complete | error
    return_code: int | None = None
    end_time: float | None = None


_processes: dict[str, ProcessInfo] = {}


# ============================================
# PUBLIC API
# ============================================

def start_command(command_key: str, extra_args: list[str] | None = None) -> str:
    """Spawn a command as a subprocess. Returns a process_id for tracking."""
    if command_key not in COMMANDS:
        raise ValueError(f"Unknown command: {command_key}")

    # Clean up old processes first
    cleanup_old()

    cmd_spec = COMMANDS[command_key]
    cmd = list(cmd_spec["base_cmd"])
    if extra_args:
        cmd.extend(extra_args)

    process_id = uuid.uuid4().hex[:8]

    # Create temp log file
    log_fh = tempfile.NamedTemporaryFile(
        mode="w",
        delete=False,
        suffix=".log",
        prefix=f"cockpit_{command_key}_",
    )
    log_path = log_fh.name

    # Spawn subprocess
    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    _processes[process_id] = ProcessInfo(
        process=proc,
        command_key=command_key,
        command_label=cmd_spec["label"],
        log_path=log_path,
        start_time=time.time(),
    )

    return process_id


def get_status(process_id: str) -> dict:
    """Poll process status. Returns dict with status, return_code, elapsed."""
    info = _processes.get(process_id)
    if info is None:
        return {"status": "unknown", "return_code": None, "elapsed": 0}

    # Check if process finished
    if info.status == "running":
        rc = info.process.poll()
        if rc is not None:
            info.return_code = rc
            info.end_time = time.time()
            info.status = "complete" if rc == 0 else "error"

    elapsed = (info.end_time or time.time()) - info.start_time
    return {
        "status": info.status,
        "return_code": info.return_code,
        "elapsed": round(elapsed, 1),
        "command_label": info.command_label,
        "command_key": info.command_key,
        "pid": info.process.pid,
    }


def get_output(process_id: str, offset: int = 0) -> dict:
    """Read new output from the log file starting at byte offset.

    Returns: {"text": str, "offset": int, "done": bool}
    """
    info = _processes.get(process_id)
    if info is None:
        return {"text": "", "offset": offset, "done": True}

    try:
        with open(info.log_path, "r", errors="replace") as f:
            f.seek(offset)
            text = f.read()
            new_offset = f.tell()
    except Exception:
        text = ""
        new_offset = offset

    done = info.status in ("complete", "error")
    return {"text": text, "offset": new_offset, "done": done}


def stop_command(process_id: str) -> bool:
    """Terminate a running process. Returns True if successfully stopped."""
    info = _processes.get(process_id)
    if info is None or info.status != "running":
        return False

    try:
        info.process.terminate()
        try:
            info.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            info.process.kill()
            info.process.wait(timeout=2)
    except Exception:
        pass

    info.status = "error"
    info.return_code = info.process.returncode
    info.end_time = time.time()
    return True


def is_any_running() -> bool:
    """Check if any process is currently running."""
    for info in _processes.values():
        if info.status == "running":
            # Refresh status
            if info.process.poll() is None:
                return True
            else:
                info.status = "complete" if info.process.returncode == 0 else "error"
                info.return_code = info.process.returncode
                info.end_time = time.time()
    return False


def cleanup_old(max_age_seconds: int = 3600) -> None:
    """Remove completed process entries older than max_age and delete their log files."""
    now = time.time()
    to_remove = []
    for pid, info in _processes.items():
        if info.status in ("complete", "error") and info.end_time:
            if now - info.end_time > max_age_seconds:
                to_remove.append(pid)

    for pid in to_remove:
        info = _processes.pop(pid, None)
        if info:
            try:
                os.unlink(info.log_path)
            except OSError:
                pass
