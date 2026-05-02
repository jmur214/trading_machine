"""Pin the WFO OOS-stitching fix (engines/engine_d_discovery/wfo.py).

The old code did `oos_equity.extend(test_res["equity_curve"])` and then
`pd.Series(oos_equity).pct_change()`. Each test window's backtest starts
fresh at $100k, so concatenating equity values produced phantom −4.76%
returns at every window boundary. The fix stitches RETURNS instead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engines.engine_d_discovery import wfo as wfo_module


def _sharpe_from_returns(returns):
    s = pd.Series(returns).dropna()
    if len(s) < 2 or s.std() == 0:
        return 0.0
    return float(s.mean() / s.std() * np.sqrt(252))


def test_wfo_returns_stitching_constant_drift_no_negative_sharpe(monkeypatch):
    """Stronger pin: constant positive drift across windows yields a
    positive aggregated OOS Sharpe.

    With the BUG, this same setup would yield roughly -1× Sharpe per
    extra window because each boundary added a -5% return.
    """
    rng = np.random.RandomState(7)

    def fake_quick_backtest(self, spec, params, start, end):
        # Each window: tiny positive mean, small noise → reliable +Sharpe
        n = 60
        ret = rng.normal(loc=0.001, scale=0.001, size=n)  # high SNR
        equity = (100_000.0 * np.cumprod(1 + ret)).tolist()
        sh = float(np.mean(ret) / np.std(ret) * np.sqrt(252))
        return {"sharpe": sh, "equity_curve": equity}

    monkeypatch.setattr(
        wfo_module.WalkForwardOptimizer, "_quick_backtest", fake_quick_backtest
    )

    # Define a fake edge module reachable via importlib
    import sys
    class _FakeEdge:
        def get_hyperparameter_space(self):
            return {"window": [10, 20]}
        def sample_params(self):
            return {"window": 10}
    fake_mod = type("M", (), {"FakeEdge": _FakeEdge})()
    sys.modules["engines.engine_d_discovery._fake_test_edge"] = fake_mod

    days = pd.bdate_range("2022-01-03", periods=400)
    data_map = {
        "TEST": pd.DataFrame(
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
            index=days,
        )
    }
    spec = {
        "edge_id": "test_v1",
        "module": "engines.engine_d_discovery._fake_test_edge",
        "class": "FakeEdge",
    }

    wfo = wfo_module.WalkForwardOptimizer(data_map=data_map)
    out = wfo.run_optimization(spec, start_date="2022-01-03",
                               train_months=4, test_months=2)
    assert "oos_sharpe" in out
    assert out["oos_sharpe"] > 0, (
        f"Stitched-by-returns OOS Sharpe should be positive on uniformly-"
        f"positive synthetic windows, got {out['oos_sharpe']}"
    )
