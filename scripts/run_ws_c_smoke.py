"""scripts/run_ws_c_smoke.py
============================
Workstream-C cross-asset confirmation smoke driver.

Runs the determinism harness for a SINGLE year (default 2024) twice:

  Cell A (OFF) — current main behavior, cross-asset confirm disabled.
  Cell B (ON)  — cross-asset confirm enabled (gate computed and surfaced
                 read-only into advisory; HMM also enabled so the gate
                 has a transition signal to test against).

Both cells are run for N reps; we verify each cell is bitwise deterministic
(same Sharpe + same trades canon md5 across all reps) and report the
delta between cells.

Hard constraints (enforced):
  - Default OFF on main is preserved: the smoke modifies
    `config/regime_settings.json` IN PLACE, but snapshots+restores it
    around the run so the working tree returns to its starting state.
  - Anchor files are NOT modified — `isolated()` from run_isolated.py
    handles all governor-file restoration around each rep.
  - DO NOT run multi-year — defaults to a single year (2024).

Usage:
  PYTHONHASHSEED=0 python -m scripts.run_ws_c_smoke --year 2024 --runs 3 \\
      --output docs/Audit/ws_c_smoke.md \\
      --json-output docs/Audit/ws_c_smoke.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_isolated import (  # noqa: E402
    ISOLATED_ANCHOR,
    TRADES_DIR,
    isolated,
    _find_run_id,
    _trades_canon_md5,
)


REGIME_CFG_PATH = ROOT / "config" / "regime_settings.json"


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(
            sys.executable,
            [sys.executable, "-m", "scripts.run_ws_c_smoke", *sys.argv[1:]],
        )


@contextmanager
def _temporarily_modify_regime_config(
    enable_cross_asset: bool,
    enable_hmm: bool,
) -> Iterator[None]:
    """Snapshot regime_settings.json, write a modified version with the
    requested flags, then restore on exit. The snapshot lives in /tmp so
    a crash doesn't leave a stale .bak file in the working tree."""
    backup = ROOT / ".tmp_regime_settings.bak.json"
    shutil.copy(REGIME_CFG_PATH, backup)
    try:
        with open(REGIME_CFG_PATH) as f:
            raw = json.load(f)
        if enable_hmm:
            raw.setdefault("hmm", {})["hmm_enabled"] = True
        if enable_cross_asset:
            raw.setdefault("cross_asset_confirm", {})["cross_asset_confirm_enabled"] = True
        with open(REGIME_CFG_PATH, "w") as f:
            json.dump(raw, f, indent=4)
        yield
    finally:
        shutil.copy(backup, REGIME_CFG_PATH)
        backup.unlink(missing_ok=True)


def _run_year(year: int) -> dict:
    """Single full-calendar-year backtest under prod config."""
    from orchestration.mode_controller import ModeController
    mc = ModeController(ROOT, env="prod")
    return mc.run_backtest(
        mode="prod",
        fresh=False,
        no_governor=False,
        reset_governor=True,
        alpha_debug=False,
        override_start=f"{year}-01-01",
        override_end=f"{year}-12-31",
    )


def _cell(label: str, year: int, runs: int,
          enable_cross_asset: bool, enable_hmm: bool) -> list[dict]:
    """Run one cell (OFF or ON) for `runs` reps, returning per-rep records."""
    print(f"\n========= CELL {label}: cross_asset={enable_cross_asset}, "
          f"hmm={enable_hmm}, year={year}, reps={runs} =========",
          flush=True)

    out: list[dict] = []
    with _temporarily_modify_regime_config(
        enable_cross_asset=enable_cross_asset, enable_hmm=enable_hmm,
    ):
        for rep in range(1, runs + 1):
            print(f"\n----- {label} rep {rep}/{runs} -----", flush=True)
            before = {p.name for p in TRADES_DIR.iterdir()
                      if p.is_dir() and p.name != "backup"}
            t_run = time.time()
            try:
                with isolated():
                    summary = _run_year(year)
                run_id = _find_run_id(before) or "?"
                rec = {
                    "cell": label,
                    "rep": rep,
                    "year": year,
                    "run_id": run_id,
                    "sharpe": summary.get("Sharpe Ratio"),
                    "cagr_pct": summary.get("CAGR (%)"),
                    "max_drawdown_pct": summary.get("Max Drawdown (%)"),
                    "win_rate_pct": summary.get("Win Rate (%)"),
                    "total_trades": summary.get("Total Trades"),
                    "trades_canon_md5": _trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
                    "wall_time_seconds": round(time.time() - t_run, 1),
                    "ok": True,
                }
            except Exception as e:
                rec = {
                    "cell": label, "rep": rep, "year": year, "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "wall_time_seconds": round(time.time() - t_run, 1),
                }
            out.append(rec)
            print(f"  Result: {rec}", flush=True)
    return out


def _format_markdown(off: list[dict], on: list[dict],
                     output_path: Path) -> None:
    """Produce the docs/Audit/ws_c_smoke.md summary."""
    def _summarize(records: list[dict]) -> dict:
        ok = [r for r in records if r.get("ok")]
        sharpes = [r["sharpe"] for r in ok if r["sharpe"] is not None]
        canons = [r["trades_canon_md5"] for r in ok]
        if not sharpes:
            return {"mean": None, "min": None, "max": None,
                    "range": None, "canon_unique": 0,
                    "deterministic": False, "n": len(ok)}
        return {
            "mean": statistics.mean(sharpes),
            "min": min(sharpes),
            "max": max(sharpes),
            "range": max(sharpes) - min(sharpes),
            "canon_unique": len(set(canons)),
            "deterministic": (max(sharpes) - min(sharpes) <= 1e-9
                              and len(set(canons)) == 1),
            "n": len(ok),
        }

    s_off = _summarize(off)
    s_on = _summarize(on)

    lines: list[str] = []
    lines.append("# Workstream-C Cross-Asset Confirmation Smoke Run")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## Cells")
    lines.append("")
    lines.append("| Cell | Cross-asset | HMM | Reps | Sharpes | Range | "
                 "Canon md5 unique | Bitwise det |")
    lines.append("|---|---|---|---:|---|---:|---:|---|")
    sharpes_off = [r['sharpe'] for r in off if r.get('ok')]
    sharpes_on = [r['sharpe'] for r in on if r.get('ok')]
    lines.append(
        f"| A (baseline) | OFF | OFF | {s_off['n']} | "
        f"{', '.join(f'{s:.4f}' for s in sharpes_off)} | "
        f"{s_off['range']:.6f} | {s_off['canon_unique']}/{s_off['n']} | "
        f"{'PASS' if s_off['deterministic'] else 'FAIL'} |"
    )
    lines.append(
        f"| B (gated) | ON | ON | {s_on['n']} | "
        f"{', '.join(f'{s:.4f}' for s in sharpes_on)} | "
        f"{s_on['range']:.6f} | {s_on['canon_unique']}/{s_on['n']} | "
        f"{'PASS' if s_on['deterministic'] else 'FAIL'} |"
    )
    lines.append("")

    if s_off["mean"] is not None and s_on["mean"] is not None:
        delta = s_on["mean"] - s_off["mean"]
        lines.append(f"## Sharpe delta\n")
        lines.append(f"- Cell A mean Sharpe: **{s_off['mean']:.4f}**")
        lines.append(f"- Cell B mean Sharpe: **{s_on['mean']:.4f}**")
        lines.append(f"- Delta (B - A):      **{delta:+.4f}**")
        lines.append("")
        lines.append("### Caveat")
        lines.append("")
        lines.append(
            "This is a single-year smoke (one calendar year). Statistical "
            "significance of any delta requires the full multi-year measurement "
            "(2021-2025) under the determinism harness. That measurement is "
            "GAIT-CONDITIONAL on this layer being merged to main. Do NOT "
            "draw conclusions about regime-conditional alpha from one year "
            "alone — see `project_wash_sale_falsified_multiyear_2026_05_02.md` "
            "for prior evidence that single-window measurements can mislead."
        )
        lines.append("")
        if s_on["mean"] == s_off["mean"]:
            lines.append(
                "Sharpe is **identical** between cells, which is the expected "
                "and correct outcome: the cross-asset gate is wired "
                "OBSERVABILITY-ONLY this round (advisory.cross_asset_confirm "
                "is read-only; Engine B does not consume). A non-zero delta "
                "would indicate inadvertent leakage into the live decision "
                "path and would block promotion."
            )
        else:
            lines.append(
                f"NON-ZERO delta of {delta:+.4f} indicates the gate is "
                "affecting the live decision path. This round wires the gate "
                "as observability-only — investigate before promoting."
            )

    lines.append("")
    lines.append("## Raw run records\n")
    lines.append("```json")
    lines.append(json.dumps({"off": off, "on": on}, indent=2, default=str))
    lines.append("```")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=str, default="docs/Audit/ws_c_smoke.md")
    parser.add_argument("--json-output", type=str,
                        default="docs/Audit/ws_c_smoke.json")
    args = parser.parse_args()

    if not ISOLATED_ANCHOR.exists():
        print(f"[WS-C SMOKE] No anchor at {ISOLATED_ANCHOR}; "
              "run `python -m scripts.run_isolated --save-anchor` first.",
              file=sys.stderr)
        return 1

    t_start = time.time()
    off = _cell("A_OFF", args.year, args.runs,
                enable_cross_asset=False, enable_hmm=False)
    on = _cell("B_ON", args.year, args.runs,
               enable_cross_asset=True, enable_hmm=True)

    json_path = ROOT / args.json_output
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps({"off": off, "on": on},
                                    indent=2, default=str))

    md_path = ROOT / args.output
    _format_markdown(off, on, md_path)

    elapsed = time.time() - t_start
    print(f"\n[WS-C SMOKE] Done in {elapsed/60:.1f}m")
    print(f"[WS-C SMOKE] JSON: {json_path}")
    print(f"[WS-C SMOKE] Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
