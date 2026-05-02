"""A/B/C/D harness — Path A tax-efficient core (HRP slice 2 + turnover
penalty + LT-hold preference + wash-sale avoidance).

Cells:
    A  weighted_sum, no turnover penalty, no LT pref, no wash-sale
       (current ship state)
    B  weighted_sum + turnover penalty + LT pref + wash-sale
       (no HRP — isolates the tax-aware modules)
    C  hrp_composed + turnover penalty + LT pref + wash-sale
       (full Path A — the deployable retail config)
    D  hrp (REPLACEMENT, slice 1) — no tax-aware modules
       (sanity reproduction of the slice-1 failure)

Per cell: ``--runs N`` (default 3) replicates inside ``run_isolated.isolated()``
so the governor state is restored before/after each run. We collect:
    - sharpe (pre-tax, from PerformanceMetrics)
    - sharpe_A_baseline (slippage-only, cost completeness)
    - sharpe_B_after_borrow_alpaca
    - sharpe_C_after_tax (the deployable retail number)
    - canon md5 of the trade log (within-cell determinism check)

The harness mutates ``config/portfolio_settings.json`` and
``config/backtest_settings.json`` between cells and restores the original
files at the end (whether or not we crash).

Usage:
    PYTHONHASHSEED=0 python -m scripts.ab_path_a_tax_efficient_core --runs 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO_CFG = ROOT / "config" / "portfolio_settings.json"
BACKTEST_CFG = ROOT / "config" / "backtest_settings.json"
TRADES_DIR = ROOT / "data" / "trade_logs"


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, "-m", "scripts.ab_path_a_tax_efficient_core", *sys.argv[1:]])


# ---- cell definitions ------------------------------------------------------
# Each cell is (label, portfolio_overrides, backtest_overrides)
# - portfolio_overrides patches a few keys in portfolio_settings.json
# - backtest_overrides patches tax_drag_model.enabled (we always want tax
#   drag computed so we can read sharpe_C, regardless of cell)
CELL_DEFS = {
    "A_baseline": {
        "label": "A — weighted_sum, no Path A modules (current ship state)",
        "portfolio": {
            "portfolio_optimizer": {"method": "weighted_sum"},
            "wash_sale_avoidance": {"enabled": False},
            "lt_hold_preference": {"enabled": False},
        },
    },
    "B_tax_only": {
        "label": "B — weighted_sum + LT-hold + wash-sale (no HRP)",
        "portfolio": {
            "portfolio_optimizer": {"method": "weighted_sum"},
            "wash_sale_avoidance": {"enabled": True},
            "lt_hold_preference": {"enabled": True},
        },
    },
    "C_full_path_a": {
        "label": "C — hrp_composed + LT-hold + wash-sale (full Path A)",
        "portfolio": {
            "portfolio_optimizer": {"method": "hrp_composed"},
            "wash_sale_avoidance": {"enabled": True},
            "lt_hold_preference": {"enabled": True},
        },
    },
    "D_hrp_replacement": {
        "label": "D — hrp REPLACEMENT (slice 1 sanity reproduction)",
        "portfolio": {
            "portfolio_optimizer": {"method": "hrp"},
            "wash_sale_avoidance": {"enabled": False},
            "lt_hold_preference": {"enabled": False},
        },
    },
}


def _deep_merge(base: dict, overrides: dict) -> dict:
    out = deepcopy(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=4) + "\n")


def _apply_cell(cell_key: str, base_portfolio: dict, base_backtest: dict) -> None:
    cell = CELL_DEFS[cell_key]
    new_portfolio = _deep_merge(base_portfolio, cell["portfolio"])
    _write_json(PORTFOLIO_CFG, new_portfolio)
    # Always force tax_drag on so post-tax Sharpe is computable.
    new_backtest = _deep_merge(
        base_backtest, {"tax_drag_model": {"enabled": True}},
    )
    _write_json(BACKTEST_CFG, new_backtest)


def _run_cell(cell_key: str, runs: int) -> list[dict]:
    print(f"\n{'#' * 70}\n###### CELL: {cell_key} — {CELL_DEFS[cell_key]['label']}\n{'#' * 70}")
    from scripts import run_isolated as ri

    if not ri.ISOLATED_ANCHOR.exists():
        raise RuntimeError(
            f"No anchor at {ri.ISOLATED_ANCHOR}; run "
            f"`python -m scripts.run_isolated --save-anchor` first."
        )

    results = []
    for i in range(runs):
        print(f"\n===== {cell_key} RUN {i + 1}/{runs} =====")
        before = {
            p.name for p in TRADES_DIR.iterdir()
            if p.is_dir() and p.name != "backup"
        }
        with ri.isolated():
            summary = ri._run_q1_inside_context()
        run_id = ri._find_run_id(before) or "?"
        # cost_completeness_layer_v1 lives in the per-run perf summary
        # JSON written by BacktestController._post_run (not in the dict
        # returned from ModeController.run_backtest). Read it directly.
        cost_layer: dict = {}
        path_a_modules: dict = {}
        if run_id != "?":
            perf_json = TRADES_DIR / run_id / "performance_summary.json"
            if perf_json.exists():
                try:
                    perf_data = json.loads(perf_json.read_text())
                    cost_layer = perf_data.get("cost_completeness_layer_v1", {}) or {}
                    path_a_modules = perf_data.get("path_a_modules", {}) or {}
                except Exception:
                    cost_layer = {}
                    path_a_modules = {}
        record = {
            "cell": cell_key,
            "run_id": run_id,
            "sharpe_pretax": summary.get("Sharpe Ratio"),
            "cagr_pct": summary.get("CAGR (%)"),
            "mdd_pct": summary.get("Max Drawdown (%)"),
            "sharpe_A_baseline": cost_layer.get("sharpe_A_baseline"),
            "sharpe_B_after_borrow_alpaca": cost_layer.get(
                "sharpe_B_after_borrow_alpaca"
            ),
            "sharpe_C_after_tax": cost_layer.get("sharpe_C_after_tax"),
            "total_tax_drag": cost_layer.get("total_tax_drag_usd"),
            "wash_sale_disallowed_loss": (
                cost_layer.get("yearly_tax_breakdown", {})
                .get(str(2025), {})
                .get("wash_sale_disallowed_loss")
            ),
            "wash_sale_buys_blocked": (
                path_a_modules.get("wash_sale", {}).get("buys_blocked")
            ),
            "wash_sale_loss_exits_recorded": (
                path_a_modules.get("wash_sale", {}).get("loss_exits_recorded")
            ),
            "lt_hold_exits_deferred": (
                path_a_modules.get("lt_hold", {}).get("exits_deferred")
            ),
            "lt_hold_exits_proposed": (
                path_a_modules.get("lt_hold", {}).get("exits_proposed")
            ),
            "trades_canon_md5": (
                ri._trades_canon_md5(run_id) if run_id != "?" else "(no run_id)"
            ),
        }
        results.append(record)
        print(f"  Sharpe (pre-tax):    {record['sharpe_pretax']}")
        print(f"  Sharpe A (slip):     {record['sharpe_A_baseline']}")
        print(f"  Sharpe B (+borrow):  {record['sharpe_B_after_borrow_alpaca']}")
        print(f"  Sharpe C (post-tax): {record['sharpe_C_after_tax']}")
        print(f"  CAGR%:               {record['cagr_pct']}")
        print(f"  MDD%:                {record['mdd_pct']}")
        print(f"  total_tax_drag $:    {record['total_tax_drag']}")
        print(f"  wash_sale_disallowed_loss $: {record['wash_sale_disallowed_loss']}")
        print(f"  wash_sale buys_blocked:      {record['wash_sale_buys_blocked']}")
        print(f"  lt_hold exits_deferred/proposed: {record['lt_hold_exits_deferred']}/{record['lt_hold_exits_proposed']}")
        print(f"  canon md5:           {record['trades_canon_md5']}")
    return results


def _summarize(cell_key: str, runs: list[dict]) -> dict:
    def _mean(vals):
        clean = [v for v in vals if v is not None]
        return sum(clean) / len(clean) if clean else None

    def _spread(vals):
        clean = [v for v in vals if v is not None]
        return (max(clean) - min(clean)) if clean else None

    canons = [r["trades_canon_md5"] for r in runs]
    return {
        "cell": cell_key,
        "label": CELL_DEFS[cell_key]["label"],
        "n_runs": len(runs),
        "mean_sharpe_pretax": _mean([r["sharpe_pretax"] for r in runs]),
        "mean_sharpe_A_baseline": _mean([r["sharpe_A_baseline"] for r in runs]),
        "mean_sharpe_B_after_borrow_alpaca": _mean([r["sharpe_B_after_borrow_alpaca"] for r in runs]),
        "mean_sharpe_C_after_tax": _mean([r["sharpe_C_after_tax"] for r in runs]),
        "spread_sharpe_pretax": _spread([r["sharpe_pretax"] for r in runs]),
        "spread_sharpe_C_after_tax": _spread([r["sharpe_C_after_tax"] for r in runs]),
        "canon_unique": len(set(canons)),
        "canon_md5s": canons,
        "mean_total_tax_drag": _mean([r["total_tax_drag"] for r in runs]),
        "mean_wash_sale_disallowed_loss": _mean(
            [r["wash_sale_disallowed_loss"] for r in runs]
        ),
        "mean_wash_sale_buys_blocked": _mean(
            [r["wash_sale_buys_blocked"] for r in runs]
        ),
        "mean_lt_hold_exits_deferred": _mean(
            [r["lt_hold_exits_deferred"] for r in runs]
        ),
        "raw": runs,
    }


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3,
                        help="Replicates per cell (default 3 for determinism check).")
    parser.add_argument("--cells", default="A_baseline,B_tax_only,C_full_path_a,D_hrp_replacement",
                        help="Comma-separated cell keys to run, in order.")
    args = parser.parse_args()

    cells_to_run = [c.strip() for c in args.cells.split(",") if c.strip()]
    for c in cells_to_run:
        if c not in CELL_DEFS:
            print(f"[ERROR] Unknown cell key: {c}", file=sys.stderr)
            return 1

    base_portfolio = json.loads(PORTFOLIO_CFG.read_text())
    base_backtest = json.loads(BACKTEST_CFG.read_text())
    portfolio_snapshot = PORTFOLIO_CFG.read_text()
    backtest_snapshot = BACKTEST_CFG.read_text()

    all_results: dict[str, list[dict]] = {}
    summaries: dict[str, dict] = {}
    try:
        for cell_key in cells_to_run:
            _apply_cell(cell_key, base_portfolio, base_backtest)
            cell_results = _run_cell(cell_key, args.runs)
            all_results[cell_key] = cell_results
            summaries[cell_key] = _summarize(cell_key, cell_results)
    finally:
        # Always restore original config files even on crash / interrupt.
        PORTFOLIO_CFG.write_text(portfolio_snapshot)
        BACKTEST_CFG.write_text(backtest_snapshot)
        print(f"\n[CFG-RESTORE] Restored {PORTFOLIO_CFG.name} and {BACKTEST_CFG.name}")

    # ----- summary table --------------------------------------------------
    print("\n" + "=" * 84)
    print("  PATH A — TAX-EFFICIENT CORE — A/B/C/D RESULTS")
    print("=" * 84)
    headers = ("Cell", "Pre-tax", "Post-tax", "ΔPost-Pre", "Tax $", "Canon")
    print(f"  {headers[0]:<20} {headers[1]:>10} {headers[2]:>10} {headers[3]:>10} {headers[4]:>10} {headers[5]:>9}")
    for cell_key, s in summaries.items():
        pre = s["mean_sharpe_pretax"]
        post = s["mean_sharpe_C_after_tax"]
        delta = (post - pre) if (pre is not None and post is not None) else None
        tax = s["mean_total_tax_drag"]
        canon = f"{s['canon_unique']}/{s['n_runs']}"
        print(
            f"  {cell_key:<20} "
            f"{(f'{pre:.4f}' if pre is not None else 'n/a'):>10} "
            f"{(f'{post:.4f}' if post is not None else 'n/a'):>10} "
            f"{(f'{delta:+.4f}' if delta is not None else 'n/a'):>10} "
            f"{(f'${tax:,.0f}' if tax is not None else 'n/a'):>10} "
            f"{canon:>9}"
        )

    # Persist to disk for the audit doc
    out_path = ROOT / "docs" / "Audit" / "path_a_tax_efficient_core_ab_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {"cells": all_results, "summaries": summaries}, indent=2,
    ))
    print(f"\n[OUTPUT] Detailed results: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
