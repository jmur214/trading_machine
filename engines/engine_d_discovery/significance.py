"""
Statistical significance testing for edge discovery validation.

Provides three key tests:
1. Monte Carlo permutation test — shuffle returns to build null distribution,
   compare actual Sharpe to determine if performance is statistically significant.
2. Minimum Track Record Length (MinTRL) — Bailey & Lopez de Prado formula to
   determine how many observations are needed before a Sharpe ratio is reliable.
3. Benjamini-Hochberg false-discovery-rate correction — adjusts a batch of
   p-values for multiple testing so that the discovery cycle doesn't pass ~5%
   of candidates on pure noise.

Multiple-testing-correction usage:
    Each candidate's `monte_carlo_permutation_test` returns a raw p-value. The
    caller (the discovery orchestrator) batches all candidate p-values from a
    cycle and calls `apply_bh_fdr` once to compute the BH-corrected gate.
    Per-test API is intentionally unchanged — the correction is a batch step.
"""

from typing import Optional, Sequence
import logging

import numpy as np

logger = logging.getLogger("SIGNIFICANCE")


def monte_carlo_permutation_test(
    strategy_returns: np.ndarray,
    n_permutations: int = 1000,
    annualization: float = np.sqrt(252),
    random_state: Optional[int] = 42,
) -> dict:
    """
    Test whether the strategy's Sharpe ratio is statistically significant
    by comparing it to a null distribution of shuffled returns.

    Parameters
    ----------
    strategy_returns : array-like
        Daily returns of the strategy.
    n_permutations : int
        Number of random shuffles to build the null distribution.
    annualization : float
        Annualization factor (sqrt(252) for daily).
    random_state : int or None
        Random seed for reproducibility.

    Returns
    -------
    dict with keys:
        - p_value: float — probability of observing the actual Sharpe or better
          under the null hypothesis (lower is better, < 0.05 is significant).
        - actual_sharpe: float — the strategy's annualized Sharpe ratio.
        - null_mean: float — mean Sharpe of the null distribution.
        - null_std: float — std of the null distribution.
        - percentile: float — percentile rank of actual Sharpe in null (0-100).
    """
    rng = np.random.RandomState(random_state)
    returns = np.asarray(strategy_returns, dtype=float)
    returns = returns[~np.isnan(returns)]

    if len(returns) < 20:
        logger.warning("[SIGNIFICANCE] Too few returns for permutation test.")
        return {
            "p_value": 1.0,
            "actual_sharpe": 0.0,
            "null_mean": 0.0,
            "null_std": 0.0,
            "percentile": 50.0,
        }

    # Actual Sharpe
    mean_r = returns.mean()
    std_r = returns.std()
    if std_r < 1e-12:
        actual_sharpe = 0.0
    else:
        actual_sharpe = (mean_r / std_r) * annualization

    # Build null distribution by shuffling returns
    null_sharpes = np.zeros(n_permutations)
    for i in range(n_permutations):
        shuffled = rng.permutation(returns)
        s_mean = shuffled.mean()
        s_std = shuffled.std()
        if s_std < 1e-12:
            null_sharpes[i] = 0.0
        else:
            null_sharpes[i] = (s_mean / s_std) * annualization

    # p-value: fraction of null Sharpes >= actual Sharpe
    p_value = float((null_sharpes >= actual_sharpe).mean())
    percentile = float((null_sharpes < actual_sharpe).mean() * 100)

    return {
        "p_value": p_value,
        "actual_sharpe": float(actual_sharpe),
        "null_mean": float(null_sharpes.mean()),
        "null_std": float(null_sharpes.std()),
        "percentile": percentile,
    }


def apply_bh_fdr(
    p_values: Sequence[float],
    alpha: float = 0.05,
) -> dict:
    """
    Benjamini-Hochberg false-discovery-rate correction for a batch of p-values.

    Controls FDR at level `alpha` across the full batch — the expected
    proportion of false positives among rejected nulls is bounded by alpha,
    even when many tests are run together. Less conservative than Bonferroni
    (which controls the family-wise error rate) and closer to the right
    primitive for "we tested 100 candidate edges and want to keep the real
    ones without flooding production with noise."

    Reference: Benjamini & Hochberg (1995), "Controlling the False Discovery
    Rate: A Practical and Powerful Approach to Multiple Testing."

    Procedure:
        1. Sort the p-values ascending: p_(1) <= p_(2) <= ... <= p_(m).
        2. Find the largest k such that p_(k) <= (k / m) * alpha.
        3. Reject H0 for all tests with p <= p_(k) (the "BH threshold").
        4. Adjusted p-values: p_adj_(i) = min_{j>=i}(p_(j) * m / j), capped at 1.

    Parameters
    ----------
    p_values : sequence of float
        Raw p-values from independent (or PRDS-dependent) tests, e.g. one
        per candidate edge from `monte_carlo_permutation_test`.
    alpha : float
        Target false-discovery rate (default 0.05). The expected fraction
        of rejected nulls that are actually true (false positives) is
        bounded by this value.

    Returns
    -------
    dict with keys:
        - adjusted_p_values: list[float] — BH-adjusted p-values aligned to
          the input order. Compare directly to alpha to test rejection.
        - reject_at_alpha: list[bool] — True for tests rejected at the BH
          threshold (i.e., adjusted p <= alpha), aligned to input order.
        - threshold: float — the largest raw p-value that is rejected.
          Returns 0.0 if no test is rejected (no candidate is significant).
        - n_tests: int — batch size (informational).
        - n_rejected: int — number of rejections at this alpha.

    Notes
    -----
    Edge cases:
        - Empty input: returns zero-length lists, threshold 0.0.
        - Single p-value: BH reduces to plain p < alpha (no correction
          since correction factor m/k = 1/1 = 1).
        - All identical p-values: tied, all rejected together if any is.
        - NaN p-values: treated as 1.0 (cannot reject).
    """
    p_arr = np.asarray(list(p_values), dtype=float)
    m = len(p_arr)

    if m == 0:
        return {
            "adjusted_p_values": [],
            "reject_at_alpha": [],
            "threshold": 0.0,
            "n_tests": 0,
            "n_rejected": 0,
        }

    # Coerce NaN to 1.0 (can't reject — most conservative).
    p_arr = np.where(np.isnan(p_arr), 1.0, p_arr)

    # Sort ascending and remember the inverse permutation to map back.
    order = np.argsort(p_arr, kind="mergesort")
    sorted_p = p_arr[order]
    ranks = np.arange(1, m + 1, dtype=float)

    # BH adjusted p-values via standard right-to-left cumulative-min:
    #   p_adj_(i) = min_{j >= i} ( m/j * p_(j) ), then cap at 1.
    raw_adj = sorted_p * m / ranks
    sorted_adj = np.minimum.accumulate(raw_adj[::-1])[::-1]
    sorted_adj = np.minimum(sorted_adj, 1.0)

    # Map adjusted values back to input order.
    adjusted = np.empty_like(sorted_adj)
    adjusted[order] = sorted_adj

    # BH rejection threshold: largest sorted p with sorted_p <= (k/m) * alpha.
    crit_line = ranks / m * alpha
    below = sorted_p <= crit_line
    if np.any(below):
        k = int(np.max(np.where(below)[0])) + 1  # 1-indexed largest passing rank
        threshold = float(sorted_p[k - 1])
    else:
        k = 0
        threshold = 0.0

    reject = adjusted <= alpha

    return {
        "adjusted_p_values": [float(x) for x in adjusted],
        "reject_at_alpha": [bool(x) for x in reject],
        "threshold": threshold,
        "n_tests": m,
        "n_rejected": int(reject.sum()),
    }


def minimum_track_record_length(
    observed_sharpe: float,
    benchmark_sharpe: float = 0.0,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> int:
    """
    Minimum Track Record Length (MinTRL) per Bailey & Lopez de Prado (2012).

    Returns the minimum number of observations needed before the observed
    Sharpe ratio is statistically reliable at the 95% confidence level.

    Parameters
    ----------
    observed_sharpe : float
        Annualized Sharpe ratio observed in backtest.
    benchmark_sharpe : float
        Sharpe ratio of the benchmark (usually 0 for "is this better than nothing?").
    skewness : float
        Skewness of returns (0 for normal).
    kurtosis : float
        Kurtosis of returns (3 for normal).

    Returns
    -------
    int — minimum number of observations (trading days).
    """
    sr_diff = observed_sharpe - benchmark_sharpe
    if abs(sr_diff) < 1e-9:
        return 999999  # infinite — can't distinguish from benchmark

    # Z-score for 95% confidence
    z_alpha = 1.96

    # MinTRL formula (annualized Sharpe, daily observations)
    # MinTRL = 1 + (1 - skew*SR + (kurtosis-1)/4 * SR^2) * (z/SR_diff)^2
    sr = observed_sharpe / np.sqrt(252)  # de-annualize to per-period
    sr_diff_per = sr_diff / np.sqrt(252)

    if abs(sr_diff_per) < 1e-12:
        return 999999

    variance_factor = 1.0 - skewness * sr + ((kurtosis - 1) / 4.0) * sr**2
    min_trl = 1 + variance_factor * (z_alpha / sr_diff_per) ** 2

    return max(int(np.ceil(min_trl)), 1)
