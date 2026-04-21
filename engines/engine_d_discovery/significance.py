"""
Statistical significance testing for edge discovery validation.

Provides two key tests:
1. Monte Carlo permutation test — shuffle returns to build null distribution,
   compare actual Sharpe to determine if performance is statistically significant.
2. Minimum Track Record Length (MinTRL) — Bailey & Lopez de Prado formula to
   determine how many observations are needed before a Sharpe ratio is reliable.
"""

import numpy as np
import logging
from typing import Optional

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
