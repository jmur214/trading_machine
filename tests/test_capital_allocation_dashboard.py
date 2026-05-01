"""Smoke test for the Capital Allocation Diagnostic dashboard tab.

Verifies the data loaders against the 2025 OOS anchor UUID
(`72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34`), the same trade log the
`docs/Audit/oos_2025_decomposition_2026_04.md` rivalry analysis used,
and that the layout + callback registration cycle does not raise.

The numeric assertions encode the rivalry pattern the dashboard exists
to surface: bottom-three edges by PnL consume ~83% of fills, the cap
binds on a majority of trading days, and rivalry edges are flagged.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ANCHOR_UUID = "72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34"
TRADES_PATH = REPO_ROOT / "data" / "trade_logs" / ANCHOR_UUID / "trades.csv"

pytestmark = pytest.mark.skipif(
    not TRADES_PATH.exists(),
    reason=f"Anchor trade log {ANCHOR_UUID} not present in this worktree",
)


@pytest.fixture(autouse=True)
def chdir_repo_root(monkeypatch):
    """Loaders use relative `data/` paths; pin cwd at repo root."""
    monkeypatch.chdir(REPO_ROOT)
    # Clear LRU caches so successive tests see a clean state.
    from cockpit.dashboard_v2.utils.capital_allocation_loader import (
        load_trades, load_edge_status,
    )
    load_trades.cache_clear()
    load_edge_status.cache_clear()


def test_anchor_trades_load():
    from cockpit.dashboard_v2.utils.capital_allocation_loader import load_trades
    trades = load_trades(ANCHOR_UUID)
    assert not trades.empty
    assert len(trades) == 5498  # exact match to audit doc
    assert {"edge", "trigger", "pnl", "regime_label"}.issubset(trades.columns)


def test_per_edge_summary_matches_audit_numbers():
    """Audit found volume_anomaly_v1 PnL +$1933.73 on 191 fills (avg +$10.12/fill)."""
    from cockpit.dashboard_v2.utils.capital_allocation_loader import (
        load_trades, compute_edge_summary,
    )
    trades = load_trades(ANCHOR_UUID)
    summary = compute_edge_summary(trades)

    by_edge = summary.set_index("edge")
    va = by_edge.loc["volume_anomaly_v1"]
    assert int(va["fill_count"]) == 191
    assert va["total_pnl"] == pytest.approx(1933.73, abs=0.5)
    assert va["mean_pnl_per_fill"] == pytest.approx(10.12, abs=0.05)

    me = by_edge.loc["momentum_edge_v1"]
    assert int(me["fill_count"]) == 2203
    assert me["total_pnl"] == pytest.approx(-883.0, abs=2.0)


def test_rivalry_flag_catches_bottom_three():
    """Audit's bottom-3 rivalry edges should all be flagged."""
    from cockpit.dashboard_v2.utils.capital_allocation_loader import (
        load_trades, compute_edge_summary, flag_rivalry,
    )
    trades = load_trades(ANCHOR_UUID)
    summary = flag_rivalry(compute_edge_summary(trades))
    flagged = set(summary[summary["rivalry_flag"]]["edge"])
    assert "momentum_edge_v1" in flagged
    assert "low_vol_factor_v1" in flagged
    assert "atr_breakout_v1" in flagged
    # heroes should NOT be flagged
    assert "volume_anomaly_v1" not in flagged
    assert "herding_v1" not in flagged


def test_cap_binding_dominantly_momentum():
    """Audit predicted: cap binds on ~99% of entry-days, momentum_edge_v1 dominates."""
    from cockpit.dashboard_v2.utils.capital_allocation_loader import (
        load_trades, compute_rolling_fill_share, cap_binding_summary,
    )
    trades = load_trades(ANCHOR_UUID)
    rolling = compute_rolling_fill_share(trades, window_days=20)
    binding = cap_binding_summary(rolling, cap=0.20)

    assert binding["binding"].mean() > 0.95
    top_binders = binding[binding["binding"]]["max_edge"].value_counts()
    assert top_binders.index[0] == "momentum_edge_v1"
    # combined top-2 should account for >90% of binding days
    assert top_binders.head(2).sum() / top_binders.sum() > 0.90


def test_layout_renders_without_error():
    """Importing + rendering the layout function must not raise."""
    from cockpit.dashboard_v2.tabs.capital_allocation_tab import capital_allocation_layout
    layout = capital_allocation_layout()
    assert layout is not None
    # Basic Dash component structure check
    assert hasattr(layout, "children")


def test_callbacks_register_without_error():
    """Wiring callbacks against a fresh Dash app must not raise."""
    import dash
    from cockpit.dashboard_v2.callbacks.capital_allocation_callbacks import (
        register_capital_allocation_callbacks,
    )
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_capital_allocation_callbacks(app)
    # App should now have at least one callback registered.
    assert len(app.callback_map) >= 1


def test_callback_executes_against_anchor_uuid():
    """Run the pure callback body against the anchor UUID and check outputs are well-formed."""
    from cockpit.dashboard_v2.callbacks.capital_allocation_callbacks import (
        compute_capital_allocation_view,
    )

    table_data, scatter, binding_chart, binding_text, regime_chart, headline = (
        compute_capital_allocation_view(ANCHOR_UUID, 0.20, 20)
    )
    assert isinstance(table_data, list) and len(table_data) > 0
    # rivalry-flagged rows present
    assert any(row.get("rivalry_flag") for row in table_data)
    # scatter has data trace + diagonal + zero line
    assert len(scatter.data) >= 2
    # binding chart has at least one edge series
    assert len(binding_chart.data) >= 1
    assert "Cap-binding days" in binding_text
    # regime chart populated (anchor has regime_label data)
    assert len(regime_chart.data) >= 1
