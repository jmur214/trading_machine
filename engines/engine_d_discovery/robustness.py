
import pandas as pd
import numpy as np
from typing import List, Dict, Optional


class RobustnessTester:
    """
    Tier 1 Research Tool: Robustness & Overfitting Check.

    Problem:
    --------
    "We have limited data." -> Standard backtests overfit to the specific history.

    Solution:
    ---------
    Data Augmentation via Circular Block Bootstrap.
    We generate N "Synthetic Realities" that preserve the statistical properties
    (volatility, correlation, regimes) of the original data but scramble the sequence.

    If a strategy survives these alternate realities, it is NOT overfit.

    Two bootstrap modes (2026-05-02 architectural fix):
    - ``generate_bootstrap_paths`` — legacy single-ticker bootstrap. Resamples
      one symbol's price series; used by callers operating on a single
      instrument.
    - ``generate_cross_section_bootstrap`` — synchronized cross-section
      bootstrap. Picks the same calendar block across ALL tickers
      simultaneously, preserving cross-sectional correlation. Required for
      multi-name edges where cross-sectional signal density matters
      (volume_anomaly, herding, momentum, etc.).
    - ``bootstrap_returns_stream`` — block bootstrap of a 1-D returns
      series. Used by the post-architectural-fix gauntlet to bootstrap
      the candidate's attribution stream directly (cheaper than re-running
      the full backtest, and the right primitive for portfolio-level
      contribution stability).
    """

    def generate_bootstrap_paths(self, df: pd.DataFrame, n_paths: int = 100, block_size: int = 20) -> List[pd.DataFrame]:
        """
        Generate N synthetic price histories using Circular Block Bootstrap.
        Preserves serial correlation within blocks (e.g. 20 days).

        Single-ticker version. For multi-ticker universes use
        ``generate_cross_section_bootstrap`` instead — this version
        scrambles each ticker independently and destroys cross-sectional
        correlation, which is wrong for cross-sectional edges.
        """
        if df.empty:
            return []

        returns = df["Close"].pct_change().dropna().values
        n_samples = len(returns)

        synthetic_dfs = []

        # Pre-compute start price
        start_price = df["Close"].iloc[0]

        for i in range(n_paths):
            # Generate random block starting indices
            # We need approx n_samples / block_size blocks
            n_blocks = int(np.ceil(n_samples / block_size))

            # Random indices
            indices = np.random.randint(0, n_samples, n_blocks)

            synthetic_returns = []

            for idx in indices:
                # Grab the block, wrapping around if needed (Circular)
                if idx + block_size > n_samples:
                    # Split block (end + start)
                    part1 = returns[idx:]
                    part2 = returns[:(idx + block_size - n_samples)]
                    block = np.concatenate([part1, part2])
                else:
                    block = returns[idx : idx + block_size]

                synthetic_returns.append(block)

            # Flatten
            flat_ret = np.concatenate(synthetic_returns)[:n_samples]

            # Reconstruct Price Path (Geometric Brownian Motion approx from returns)
            # Price_t = Price_0 * Product(1 + r)
            price_path = start_price * np.cumprod(1 + flat_ret)

            # Create DataFrame
            # We preserve index (dates) for compatibility, though the "events" are scrambled
            syn_df = df.copy()
            # We only overwrite Close/Open/High/Low scalled
            # This is a simplification. For rigorous checks we'd scale everything.

            # Scale factor for H/L/O based on new Close vs Old Close magnitude?
            # Simpler: Just replace Close, assume execution assumes Close.
            # Or better: Apply pct_change to all columns?
            # MVP: Reconstruct Close.
            syn_df["Close"] = price_path
            syn_df["Open"] = price_path # Approx
            syn_df["High"] = price_path # Approx
            syn_df["Low"] = price_path # Approx

            synthetic_dfs.append(syn_df)

        return synthetic_dfs

    def generate_cross_section_bootstrap(
        self,
        data_map: Dict[str, pd.DataFrame],
        n_paths: int = 50,
        block_size: int = 20,
        seed: Optional[int] = 42,
    ) -> List[Dict[str, pd.DataFrame]]:
        """Synchronized cross-section block bootstrap.

        Each synthetic path picks the same calendar blocks across ALL
        tickers in `data_map`. Cross-sectional correlation between names
        is preserved (when SPY rallies on date d, MSFT and AAPL also see
        their date-d returns), which is what multi-name edges need.

        Mechanism
        ---------
        1. Find the common date intersection across all tickers in `data_map`.
        2. For each path, sample n_blocks block-start indices from the
           common date axis.
        3. For each ticker, take the same block-start indices into its
           own returns series, reconstruct its price path, and emit a
           per-ticker synthetic DataFrame.

        Each synthetic path is a dict[ticker -> DataFrame] with the
        same shape as the input — drop-in for a strategy_wrapper that
        expects a `data_map` arg.

        Notes
        -----
        - Each ticker's synthetic OHLC is reduced to a flat Close series
          (Open=High=Low=Close). The single-ticker bootstrap has the same
          simplification — for rigorous backtests on bootstrap paths, the
          OHLC reconstruction is a known limitation.
        - Tickers with insufficient data (fewer than block_size bars)
          are dropped.
        - Reproducibility via `seed`. Pass None for non-reproducible.
        """
        if not data_map:
            return []

        # Find common date intersection so blocks are synchronized.
        date_sets = []
        for t, df in data_map.items():
            if df is None or df.empty:
                continue
            date_sets.append(set(pd.to_datetime(df.index)))
        if not date_sets:
            return []
        common_dates = sorted(set.intersection(*date_sets))
        if len(common_dates) < block_size + 1:
            return []
        common_index = pd.DatetimeIndex(common_dates)

        # Pre-compute returns + start prices for each ticker, aligned to common_dates.
        ticker_returns: Dict[str, np.ndarray] = {}
        ticker_start_prices: Dict[str, float] = {}
        for t, df in data_map.items():
            if df is None or df.empty:
                continue
            aligned = df.reindex(common_index)["Close"].astype(float)
            if aligned.isna().any():
                # Forward-fill NaNs from the reindex; if the leading bar is
                # NaN we drop this ticker.
                aligned = aligned.ffill().bfill()
                if aligned.isna().any():
                    continue
            ret = aligned.pct_change().dropna().values
            if len(ret) < block_size:
                continue
            ticker_returns[t] = ret
            ticker_start_prices[t] = float(aligned.iloc[0])

        if not ticker_returns:
            return []

        n_samples = min(len(r) for r in ticker_returns.values())
        n_blocks = int(np.ceil(n_samples / block_size))

        rng = np.random.RandomState(seed) if seed is not None else np.random

        synthetic_paths: List[Dict[str, pd.DataFrame]] = []
        for i in range(n_paths):
            block_starts = rng.randint(0, n_samples, n_blocks)
            path: Dict[str, pd.DataFrame] = {}
            for t, ret in ticker_returns.items():
                # Apply the same block_starts to each ticker → synchronized.
                blocks = []
                for idx in block_starts:
                    if idx + block_size > len(ret):
                        part1 = ret[idx:]
                        part2 = ret[: (idx + block_size - len(ret))]
                        blocks.append(np.concatenate([part1, part2]))
                    else:
                        blocks.append(ret[idx : idx + block_size])
                flat_ret = np.concatenate(blocks)[:n_samples]
                price_path = ticker_start_prices[t] * np.cumprod(1 + flat_ret)
                # Build a DataFrame using the (n_samples + 1) leading dates
                # so the index matches the price path length.
                idx = common_index[: len(price_path)]
                syn_df = pd.DataFrame({
                    "Open": price_path,
                    "High": price_path,
                    "Low": price_path,
                    "Close": price_path,
                    "Volume": np.full(len(price_path), 1_000_000.0),
                }, index=idx)
                path[t] = syn_df
            synthetic_paths.append(path)
        return synthetic_paths

    def bootstrap_returns_stream(
        self,
        returns: pd.Series,
        n_paths: int = 200,
        block_size: int = 20,
        seed: Optional[int] = 42,
    ) -> List[pd.Series]:
        """Circular-block bootstrap of a 1-D returns stream.

        Used by the post-architectural-fix gauntlet to bootstrap a
        candidate's attribution stream (per-day returns of the
        with-candidate ensemble minus baseline). Each synthetic stream
        preserves serial correlation within blocks while scrambling the
        ordering — the right primitive for "is the contribution
        temporally robust?"

        Returns a list of synthetic pd.Series, each with the same length
        as the input.
        """
        r = pd.Series(returns).dropna()
        if len(r) < block_size + 1:
            return []
        arr = r.values.astype(float)
        n = len(arr)
        n_blocks = int(np.ceil(n / block_size))
        rng = np.random.RandomState(seed) if seed is not None else np.random

        out: List[pd.Series] = []
        for i in range(n_paths):
            block_starts = rng.randint(0, n, n_blocks)
            blocks = []
            for idx in block_starts:
                if idx + block_size > n:
                    part1 = arr[idx:]
                    part2 = arr[: (idx + block_size - n)]
                    blocks.append(np.concatenate([part1, part2]))
                else:
                    blocks.append(arr[idx : idx + block_size])
            flat = np.concatenate(blocks)[:n]
            out.append(pd.Series(flat))
        return out

    def calculate_pbo(self,
                      strategy_func,
                      df: pd.DataFrame,
                      n_paths: int = 50) -> Dict[str, float]:
        """
        Probability of Backtest Overfitting (PBO).
        Runs the strategy on N synthetic paths.

        Metric: What % of synthetic equity curves have Sharpe > 0?
        If the strategy works in < 50% of synthetic markets, it effectively is random luck.
        We want > 90% survival rate.

        NOTE: This is the legacy single-ticker variant. After the
        2026-05-02 architectural fix, the gauntlet calls
        `calculate_pbo_returns_stream` instead, which bootstraps the
        candidate's attribution stream rather than re-running the strategy
        on synthetic OHLC. This method is retained for backward compat
        with single-ticker callers.
        """
        paths = self.generate_bootstrap_paths(df, n_paths=n_paths)

        sharpes = []
        for path_df in paths:
            # Run strategy (Duck typed function that takes DF and returns equity curve or sharpe)
            # We assume strategy_func returns a dict with 'sharpe'
            try:
                res = strategy_func({"SYTH": path_df})
                sharpes.append(res.get("sharpe", -1.0))
            except Exception:
                sharpes.append(-1.0)

        sharpes = np.array(sharpes)

        # Real-data Sharpe — needed to locate the actual result inside the
        # synthetic null distribution. If strategy_func chokes on the real
        # data we fall back to the median of the null (50th percentile).
        try:
            actual_res = strategy_func({"SYTH": df})
            actual_sharpe = float(actual_res.get("sharpe", 0.0))
            if len(sharpes) > 0:
                original_sharpe_percentile = float(
                    (sharpes < actual_sharpe).mean() * 100.0
                )
            else:
                original_sharpe_percentile = 50.0
        except Exception:
            original_sharpe_percentile = 50.0

        # PBO Logic (Simplified variant)
        # Probability that the strategy fails in random market variants
        # Survival Rate
        survival_rate = (sharpes > 0.0).mean()
        avg_sharpe = sharpes.mean()

        return {
            "n_paths": n_paths,
            "survival_rate": float(survival_rate),  # Target > 0.9
            "avg_synthetic_sharpe": float(avg_sharpe),
            "original_sharpe_percentile": original_sharpe_percentile,
        }

    def calculate_pbo_returns_stream(
        self,
        attribution_stream: pd.Series,
        n_paths: int = 200,
        block_size: int = 20,
        seed: Optional[int] = 42,
    ) -> Dict[str, float]:
        """PBO survival on a per-day attribution stream (post-fix gauntlet).

        Bootstraps the 1-D return series with circular block bootstrap
        and counts the fraction of paths whose Sharpe stays positive.

        Returns a dict with:
          - n_paths: int
          - survival_rate: float (fraction of paths with Sharpe > 0)
          - avg_synthetic_sharpe: float
          - actual_sharpe: float (the input stream's Sharpe, for comparison)
          - actual_sharpe_percentile: float (where the actual sits in the
            null distribution, 0-100)
        """
        r = pd.Series(attribution_stream).dropna()
        if len(r) < block_size + 1:
            return {
                "n_paths": 0, "survival_rate": 0.0,
                "avg_synthetic_sharpe": 0.0, "actual_sharpe": 0.0,
                "actual_sharpe_percentile": 50.0,
            }

        synth = self.bootstrap_returns_stream(
            r, n_paths=n_paths, block_size=block_size, seed=seed,
        )
        if not synth:
            return {
                "n_paths": 0, "survival_rate": 0.0,
                "avg_synthetic_sharpe": 0.0, "actual_sharpe": 0.0,
                "actual_sharpe_percentile": 50.0,
            }

        ann = float(np.sqrt(252))
        sharpes = []
        for s in synth:
            std = float(s.std())
            if std > 0 and len(s) > 1:
                sharpes.append(float(s.mean() / std * ann))
            else:
                sharpes.append(0.0)
        sharpes = np.array(sharpes)

        actual_std = float(r.std())
        actual_sharpe = (
            float(r.mean() / actual_std * ann) if actual_std > 0 else 0.0
        )

        return {
            "n_paths": int(len(sharpes)),
            "survival_rate": float((sharpes > 0.0).mean()),
            "avg_synthetic_sharpe": float(sharpes.mean()),
            "actual_sharpe": actual_sharpe,
            "actual_sharpe_percentile": float(
                (sharpes < actual_sharpe).mean() * 100.0
            ),
        }
