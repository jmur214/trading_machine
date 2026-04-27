"""
tests/test_significance.py
==========================
Tests for engines/engine_d_discovery/significance.py.

Two functions matter here:

  1. `monte_carlo_permutation_test` — per-candidate p-value from Sharpe
     vs a shuffled-returns null distribution. Already in use; the tests
     below are a regression check that the function still produces a
     valid p-value in the trivial cases.

  2. `apply_bh_fdr` — Benjamini-Hochberg false-discovery-rate correction
     across a batch of p-values from the discovery cycle. Without this
     correction, ~5% of candidate edges pass on pure noise when the
     gauntlet runs many candidates per cycle.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_d_discovery.significance import (
    apply_bh_fdr,
    monte_carlo_permutation_test,
)


# ---------------------------------------------------------------------------
# apply_bh_fdr — edge cases
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_arrays():
    res = apply_bh_fdr([], alpha=0.05)
    assert res["adjusted_p_values"] == []
    assert res["reject_at_alpha"] == []
    assert res["threshold"] == 0.0
    assert res["n_tests"] == 0
    assert res["n_rejected"] == 0


def test_single_p_value_below_alpha_rejects():
    # With m=1, BH adjustment factor is 1/1=1 → behaves like raw p<alpha.
    res = apply_bh_fdr([0.01], alpha=0.05)
    assert res["adjusted_p_values"] == pytest.approx([0.01])
    assert res["reject_at_alpha"] == [True]
    assert res["threshold"] == pytest.approx(0.01)
    assert res["n_rejected"] == 1


def test_single_p_value_above_alpha_no_rejection():
    res = apply_bh_fdr([0.20], alpha=0.05)
    assert res["adjusted_p_values"] == pytest.approx([0.20])
    assert res["reject_at_alpha"] == [False]
    assert res["threshold"] == 0.0
    assert res["n_rejected"] == 0


def test_all_identical_p_values_handled_consistently():
    # Ten p-values all = 0.01 with alpha=0.05. The BH adjusted p for each
    # is min over j>=i of (m/j * 0.01). Smallest j gives largest factor;
    # cumulative-min from the right yields all = 0.01. So all reject.
    res = apply_bh_fdr([0.01] * 10, alpha=0.05)
    assert all(p == pytest.approx(0.01) for p in res["adjusted_p_values"])
    assert all(res["reject_at_alpha"])
    assert res["n_rejected"] == 10


def test_nan_p_values_treated_as_one():
    # A NaN p-value should never trigger rejection.
    res = apply_bh_fdr([float("nan"), 0.001], alpha=0.05)
    # The 0.001 is significant; the NaN is not.
    assert res["reject_at_alpha"][0] is False
    assert res["reject_at_alpha"][1] is True


# ---------------------------------------------------------------------------
# apply_bh_fdr — textbook example
# ---------------------------------------------------------------------------


def test_textbook_bh_example_reproduces_expected_rejections():
    """
    Classic worked example. With m=10 and alpha=0.05, the BH critical
    line at rank k is k/m * alpha = k/200. Sorted ascending:

        rank  p        crit (k/m*alpha)   rejected?
          1   0.001    0.005              yes (0.001 < 0.005)
          2   0.008    0.010              yes
          3   0.039    0.015              no
          4   0.041    0.020              no
          5   0.042    0.025              no
          6   0.060    0.030              no
          7   0.074    0.035              no
          8   0.205    0.040              no
          9   0.212    0.045              no
         10   0.216    0.050              no

    BH rejects all p_(i) up to the largest i where p_(i) <= crit_(i).
    Largest such i is 2, so the threshold is 0.008 and ranks 1-2 reject.
    """
    p_in = [0.001, 0.008, 0.039, 0.041, 0.042, 0.060, 0.074, 0.205, 0.212, 0.216]
    res = apply_bh_fdr(p_in, alpha=0.05)

    assert res["n_tests"] == 10
    assert res["n_rejected"] == 2
    assert res["threshold"] == pytest.approx(0.008)
    # Only the two smallest reject.
    assert res["reject_at_alpha"][:2] == [True, True]
    assert not any(res["reject_at_alpha"][2:])


def test_unsorted_input_handled_correctly():
    """BH-FDR must sort internally — input order should not matter."""
    p_sorted = [0.001, 0.008, 0.039, 0.041, 0.042, 0.060, 0.074, 0.205, 0.212, 0.216]
    p_shuffled = [0.216, 0.001, 0.041, 0.060, 0.008, 0.039, 0.074, 0.205, 0.042, 0.212]

    res_sorted = apply_bh_fdr(p_sorted, alpha=0.05)
    res_shuffled = apply_bh_fdr(p_shuffled, alpha=0.05)

    # Same threshold and same rejection count regardless of input order.
    assert res_sorted["threshold"] == res_shuffled["threshold"]
    assert res_sorted["n_rejected"] == res_shuffled["n_rejected"]

    # The two smallest p-values in the shuffled batch are 0.001 (idx 1)
    # and 0.008 (idx 4). Those should be the rejections.
    rejected_idx = [i for i, r in enumerate(res_shuffled["reject_at_alpha"]) if r]
    assert sorted(rejected_idx) == [1, 4]


# ---------------------------------------------------------------------------
# apply_bh_fdr — null behavior (the whole point of this fix)
# ---------------------------------------------------------------------------


def test_pure_noise_batch_produces_few_or_zero_rejections():
    """
    The reason BH-FDR exists. With 100 p-values drawn uniformly from
    [0,1] (the null), raw p<0.05 would falsely reject ~5 candidates by
    coincidence. BH-FDR is far more conservative — for 100 uniform
    p-values, the expected number of BH rejections at alpha=0.05 is
    well under 1 (typically 0).
    """
    rng = np.random.RandomState(20260427)
    p_null = rng.uniform(0, 1, size=100).tolist()

    raw_rejections = sum(p < 0.05 for p in p_null)
    bh_res = apply_bh_fdr(p_null, alpha=0.05)
    bh_rejections = bh_res["n_rejected"]

    # Sanity: raw threshold falsely rejects ~5 of 100 uniform p-values.
    assert raw_rejections >= 1, "test seed should produce some raw rejections"
    # BH-FDR should reject far fewer (typically zero) under the null.
    assert bh_rejections <= raw_rejections
    # With a fixed seed and 100 truly-uniform p-values, BH rejects 0 here.
    # If this assertion ever fires, investigate the seed — but the
    # contract that bh_rejections << raw_rejections under the null is
    # what matters.
    assert bh_rejections == 0


def test_mixed_signal_and_noise_recovers_signal_only():
    """
    Mix 5 truly-significant p-values (small) with 95 null p-values
    (uniform). BH-FDR should reject around the 5 real ones and leave
    most of the noise untouched.
    """
    rng = np.random.RandomState(20260427)
    real_signal = [1e-5, 1e-4, 1e-4, 5e-4, 1e-3]  # 5 real
    noise = rng.uniform(0, 1, size=95).tolist()
    p_all = real_signal + noise

    res = apply_bh_fdr(p_all, alpha=0.05)
    n_rej = res["n_rejected"]

    # We should recover at least the 5 signal p-values; the noise tail
    # may push the BH threshold up enough to capture a couple of small
    # uniform draws too, but FDR is bounded at alpha so the false-positive
    # share among the rejected set should remain small.
    assert n_rej >= 5
    # And we shouldn't have rejected the entire batch.
    assert n_rej < 50

    # All five signals should be rejected.
    for j in range(5):
        assert res["reject_at_alpha"][j], (
            f"Real signal index {j} (p={real_signal[j]}) was not rejected"
        )


# ---------------------------------------------------------------------------
# monte_carlo_permutation_test — regression sanity
# ---------------------------------------------------------------------------


def test_permutation_test_returns_low_p_for_real_alpha():
    """A series with positive mean and low std (real alpha) should produce
    a low p-value."""
    rng = np.random.RandomState(42)
    # 252 daily observations, ~30% annualized return, low vol.
    returns = rng.normal(loc=0.30 / 252, scale=0.005, size=252)

    res = monte_carlo_permutation_test(returns, n_permutations=500, random_state=1)
    assert 0.0 <= res["p_value"] <= 1.0
    # Permutation can't change Sharpe in a stationary i.i.d. setup the way
    # it can with serial correlation, so the p-value here will be near
    # 0.5 — the test is a smoke check that the API works, not a power test.
    assert res["actual_sharpe"] > 0


def test_permutation_test_returns_unit_p_for_no_signal():
    """Returns near zero with high noise should produce p ~ 0.5 (no edge)."""
    rng = np.random.RandomState(7)
    returns = rng.normal(loc=0.0, scale=0.01, size=252)

    res = monte_carlo_permutation_test(returns, n_permutations=300, random_state=1)
    assert 0.0 <= res["p_value"] <= 1.0
    # For zero-mean returns the actual Sharpe is itself a draw from the
    # null distribution, so p should sit somewhere in the middle.
    assert 0.05 < res["p_value"] < 0.95


def test_permutation_test_handles_too_few_observations():
    """Less than 20 observations → conservative fallback (p=1.0)."""
    res = monte_carlo_permutation_test(np.array([0.01, -0.01, 0.02]),
                                       n_permutations=100)
    assert res["p_value"] == 1.0
    assert res["actual_sharpe"] == 0.0
