"""One-shot backfill of decision diary with this week's load-bearing decisions.

Idempotent: refuses to run if the diary already contains entries with the
same (timestamp, what_changed) keys we are about to write.

Usage::

    python scripts/backfill_decision_diary.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `import core...` when run from repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from core.observability.decision_diary import (  # noqa: E402
    DEFAULT_DIARY_PATH,
    DecisionType,
    append_entry,
    read_entries,
)

MEM = "/Users/jacksonmurphy/.claude/projects/-Users-jacksonmurphy-Dev-trading-machine-2/memory"

ENTRIES = [
    {
        "timestamp": "2026-05-04T14:00:00+00:00",
        "decision_type": DecisionType.MEASUREMENT_RUN,
        "what_changed": "Foundation Gate measurement: deterministic harness 2021-2025, mean Sharpe 1.296",
        "expected_impact": "Pass gate 0.5 to unblock Round-N+1 5-agent dispatch",
        "actual_impact": "PASS by 0.796 margin; 5/5 years positive; later flagged substrate-conditional",
        "rationale_link": f"{MEM}/project_foundation_gate_passed_2026_05_04.md",
    },
    {
        "timestamp": "2026-05-05T10:00:00+00:00",
        "decision_type": DecisionType.CONFIG_CHANGE,
        "what_changed": "SimFin FREE adapter wired: PIT panel + 8 V/Q/A factors over 3984 US tickers, 2020-2025",
        "expected_impact": "Unblock Path C real-fundamentals harness without spending $420 BASIC",
        "actual_impact": "Cross-checks AAPL/MSFT/GOOG vs 10-Qs clean; banks gap on FREE forces ex-financials",
        "rationale_link": f"{MEM}/project_simfin_free_wired_2026_05_05.md",
    },
    {
        "timestamp": "2026-05-05T18:00:00+00:00",
        "decision_type": DecisionType.MEASUREMENT_RUN,
        "what_changed": "Path C 4-cell harness ran: 351-ticker S&P ex-financials, real Cell D 5.64% CAGR / 0.461 Sharpe",
        "expected_impact": "Verify real fundamentals beat synthetic Cell C and SPY on -15% MDD target",
        "actual_impact": "Beats SPY +43bp/+0.055 Sharpe; FAILS -15% MDD target at -21.36%",
        "rationale_link": f"{MEM}/project_path_c_4cell_2026_05_05.md",
    },
    {
        "timestamp": "2026-05-06T14:00:00+00:00",
        "decision_type": DecisionType.MEASUREMENT_RUN,
        "what_changed": "Path C vol overlay (Cell E) tested as MDD rescue at annual rebalance cadence",
        "expected_impact": "Close MDD gap from -21.36% to -15% target with Engine C vol-target as overlay",
        "actual_impact": "0.00pp MDD rescue at -2.27pp CAGR cost; cadence too coarse — 2022 drawdown between rebalances",
        "rationale_link": f"{MEM}/project_path_c_vol_overlay_falsified_2026_05_06.md",
    },
    {
        "timestamp": "2026-05-06T16:00:00+00:00",
        "decision_type": DecisionType.MERGE,
        "what_changed": "V/Q/A fundamentals edges merged to main: 6 edges active across value/quality/anomaly factors",
        "expected_impact": "Add fundamentals-driven alpha layer alongside existing technical edges",
        "actual_impact": "3 HIGH bugs found in subsequent audit: integration mismatch, basket churn, score-zero on hold",
        "rationale_link": f"{MEM}/project_fundamentals_edges_shipped_2026_05_06.md",
    },
    {
        "timestamp": "2026-05-06T18:00:00+00:00",
        "decision_type": DecisionType.EDGE_STATUS_CHANGE,
        "what_changed": "V/Q/A 3 HIGH bugfixes shipped: basket churn, integration mismatch, hold-state scoring",
        "expected_impact": "Close drag from V/Q/A merge by patching the three highest-severity defects",
        "actual_impact": "Residual -1.07 Sharpe drag exposed vs baseline 1.666 — bugfixes necessary but not sufficient",
        "rationale_link": f"{MEM}/project_vqa_bugfix_residual_drag_2026_05_06.md",
    },
    {
        "timestamp": "2026-05-07T14:00:00+00:00",
        "decision_type": DecisionType.EDGE_STATUS_CHANGE,
        "what_changed": "V/Q/A sustained_score=0.3 emission on held positions (state-transition pattern)",
        "expected_impact": "Close residual -1.07 drag by giving held positions a position-defending vote",
        "actual_impact": "2021 Sharpe 1.607 vs baseline 1.666 = -0.06 within noise; integration-mismatch hypothesis CONFIRMED",
        "rationale_link": f"{MEM}/project_vqa_sustained_scores_win_2026_05_07.md",
    },
    {
        "timestamp": "2026-05-06T19:00:00+00:00",
        "decision_type": DecisionType.MEASUREMENT_RUN,
        "what_changed": "HMM regime signal validated against forward drawdowns (read-only)",
        "expected_impact": "Verify HMM crisis probability predicts forward drawdowns before Engine B integration",
        "actual_impact": "Crisis AUC 0.49 on 20d-fwd; signal is coincident not predictive; Engine B integration BLOCKED",
        "rationale_link": f"{MEM}/project_regime_signal_falsified_2026_05_06.md",
    },
    {
        "timestamp": "2026-05-06T21:00:00+00:00",
        "decision_type": DecisionType.MEASUREMENT_RUN,
        "what_changed": "Cheap regime validation Branch 3: VIX term + CBOE P/C tested before committing to Schwab",
        "expected_impact": "Identify a leading regime feature on free data before paying for Schwab options chain",
        "actual_impact": "VIX term decisively coincident (3rd measurement); CBOE P/C historical unobtainable in 2026",
        "rationale_link": f"{MEM}/project_cheap_input_validation_branch3_2026_05_06.md",
    },
    {
        "timestamp": "2026-05-06T22:00:00+00:00",
        "decision_type": DecisionType.CONFIG_CHANGE,
        "what_changed": "Path C deferred: 3-day arc complete, cells E/F/G/H all falsified",
        "expected_impact": "Pause Path C iteration to avoid curve-fitting on 4-event MDD sample",
        "actual_impact": "3 unblock criteria written: HMM in production + Engine B regime de-grossing + sleeve abstractions",
        "rationale_link": f"{MEM}/project_path_c_deferred_2026_05_06.md",
    },
    {
        "timestamp": "2026-05-06T23:00:00+00:00",
        "decision_type": DecisionType.AGENT_DISPATCH,
        "what_changed": "External audit findings consolidated F1-F11 from cross-dev review",
        "expected_impact": "Surface highest-leverage substrate fixes before further alpha work",
        "actual_impact": "F6 universe-loader becomes top priority; F1-F11 form Phase A/B/C remediation backlog",
        "rationale_link": "docs/Sessions/Other-dev-opinion/2026-05-06_consolidated_audit_findings.md",
    },
    {
        "timestamp": "2026-05-07T18:00:00+00:00",
        "decision_type": DecisionType.MERGE,
        "what_changed": "Phase A substrate cleanup begins: A1 (2093 LOC archived d3cf6c8) + A3 (gauntlet 2513676) merged",
        "expected_impact": "Reduce active-engine surface area and narrow gauntlet bare-excepts before alpha work",
        "actual_impact": "A1+A3 merged to main; A2 mutable-globals snapshot pending",
        "rationale_link": "/Users/jacksonmurphy/.claude/plans/foamy-foraging-horizon.md",
    },
]


def main() -> int:
    existing = read_entries()
    existing_keys = {(e.timestamp, e.what_changed) for e in existing}

    written = 0
    skipped = 0
    for spec in ENTRIES:
        key = (spec["timestamp"], spec["what_changed"])
        if key in existing_keys:
            skipped += 1
            continue
        append_entry(**spec)
        written += 1

    after = read_entries()
    print(f"Backfill complete. wrote={written} skipped={skipped} total_in_diary={len(after)}")
    print(f"Diary path: {DEFAULT_DIARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
