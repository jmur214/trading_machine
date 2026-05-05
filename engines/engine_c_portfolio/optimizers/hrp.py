"""Hierarchical Risk Parity optimizer.

Implements López de Prado's HRP algorithm (2016) with three steps:
    1. Tree clustering on the correlation distance matrix
    2. Quasi-diagonalization (matrix seriation by linkage order)
    3. Recursive bisection — split portfolio variance proportionally

HRP avoids the matrix-inversion instability of mean-variance under
near-singular covariance, which is the dominant failure mode at the
3-active-edge / ~100-ticker scale this codebase runs at. See
docs/Measurements/2026-05/engine_c_hrp_first_slice_2026_05.md for design notes.

Covariance estimation defaults to Ledoit-Wolf shrinkage (sklearn).
A sample covariance fallback is used if sklearn isn't available so the
import doesn't cascade into a hard dependency for callers that don't
opt into HRP.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform


@dataclass
class HRPConfig:
    cov_lookback: int = 60          # bars of history for covariance estimation
    min_history: int = 30           # below this we fall back to equal-weight
    use_ledoit_wolf: bool = True    # shrinkage covariance (sklearn)
    linkage_method: str = "single"  # López de Prado uses single-linkage
    eps: float = 1e-12


class HRPOptimizer:
    """Hierarchical Risk Parity weight builder.

    Inputs (per call):
        returns_df : DataFrame indexed by date with one column per ticker.
                     The last `cov_lookback` rows feed the covariance.
        active_tickers : optional subset of returns_df.columns to include.
                         Tickers with insufficient history are dropped.

    Output:
        pd.Series of weights indexed by ticker, summing to 1.0,
        all non-negative (long-only HRP — short side handled by sign
        of the aggregate_score in the caller).
    """

    def __init__(self, cfg: Optional[HRPConfig] = None):
        self.cfg = cfg or HRPConfig()

    def optimize(
        self,
        returns_df: pd.DataFrame,
        active_tickers: Optional[list[str]] = None,
    ) -> pd.Series:
        cols = list(active_tickers) if active_tickers else list(returns_df.columns)
        cols = [c for c in cols if c in returns_df.columns]
        if not cols:
            return pd.Series(dtype=float)

        window = returns_df[cols].tail(self.cfg.cov_lookback)

        # When the whole window is shorter than min_history we cannot
        # estimate covariance reliably — fall back to equal-weight over
        # the requested universe rather than dropping it entirely.
        if len(window) < self.cfg.min_history:
            n = len(cols)
            return pd.Series([1.0 / n] * n, index=cols)

        # With enough total rows, drop columns that lack history.
        window = window.dropna(axis=1, thresh=self.cfg.min_history)
        cols = list(window.columns)

        n = len(cols)
        if n == 0:
            return pd.Series(dtype=float)
        if n == 1:
            return pd.Series([1.0], index=cols)

        cov = self._estimate_cov(window)
        corr = self._cov_to_corr(cov)
        dist = self._correlation_distance(corr)

        link = linkage(squareform(dist, checks=False), method=self.cfg.linkage_method)
        sort_idx = self._quasi_diag(link, n)
        sorted_tickers = [cols[i] for i in sort_idx]

        weights = self._recursive_bisection(cov.loc[sorted_tickers, sorted_tickers])
        return weights.reindex(cols).fillna(0.0)

    def _estimate_cov(self, returns: pd.DataFrame) -> pd.DataFrame:
        if self.cfg.use_ledoit_wolf:
            try:
                from sklearn.covariance import LedoitWolf
                lw = LedoitWolf().fit(returns.values)
                cov = pd.DataFrame(lw.covariance_, index=returns.columns, columns=returns.columns)
                return cov
            except ImportError:
                pass
        return returns.cov()

    @staticmethod
    def _cov_to_corr(cov: pd.DataFrame) -> pd.DataFrame:
        std = np.sqrt(np.diag(cov.values))
        std = np.where(std < 1e-12, 1e-12, std)
        corr = cov.values / np.outer(std, std)
        np.clip(corr, -1.0, 1.0, out=corr)
        np.fill_diagonal(corr, 1.0)
        return pd.DataFrame(corr, index=cov.index, columns=cov.columns)

    @staticmethod
    def _correlation_distance(corr: pd.DataFrame) -> np.ndarray:
        d = np.sqrt(0.5 * (1.0 - corr.values))
        np.fill_diagonal(d, 0.0)
        return d

    @staticmethod
    def _quasi_diag(link: np.ndarray, n_leaves: int) -> list[int]:
        """López de Prado quasi-diagonalization: order leaves so that
        similar items are adjacent. Linkage matrix `link` is shape
        (n-1, 4); rows describe successive merges of clusters.
        """
        link = link.astype(int)
        sort_ix = pd.Series([link[-1, 0], link[-1, 1]])
        num_items = n_leaves
        while sort_ix.max() >= num_items:
            sort_ix.index = range(0, sort_ix.shape[0] * 2, 2)
            df0 = sort_ix[sort_ix >= num_items]
            i = df0.index
            j = df0.values - num_items
            sort_ix[i] = link[j, 0]
            df1 = pd.Series(link[j, 1], index=i + 1)
            sort_ix = pd.concat([sort_ix, df1]).sort_index()
            sort_ix.index = range(sort_ix.shape[0])
        return sort_ix.tolist()

    def _recursive_bisection(self, cov: pd.DataFrame) -> pd.Series:
        weights = pd.Series(1.0, index=cov.index)
        clusters: list[list[str]] = [list(cov.index)]

        while clusters:
            next_clusters: list[list[str]] = []
            for cluster in clusters:
                if len(cluster) <= 1:
                    continue
                mid = len(cluster) // 2
                left = cluster[:mid]
                right = cluster[mid:]

                v_left = self._cluster_variance(cov, left)
                v_right = self._cluster_variance(cov, right)
                alpha = 1.0 - v_left / (v_left + v_right + self.cfg.eps)

                weights[left] *= alpha
                weights[right] *= 1.0 - alpha

                next_clusters.append(left)
                next_clusters.append(right)
            clusters = next_clusters

        total = weights.sum()
        if total <= self.cfg.eps:
            n = len(weights)
            return pd.Series([1.0 / n] * n, index=weights.index)
        return weights / total

    def _cluster_variance(self, cov: pd.DataFrame, items: list[str]) -> float:
        """Inverse-variance portfolio variance for a cluster — the
        building block HRP uses to decide bisection split ratio.
        """
        sub = cov.loc[items, items].values
        ivp = 1.0 / np.diag(sub)
        ivp = ivp / ivp.sum()
        return float(ivp @ sub @ ivp)
