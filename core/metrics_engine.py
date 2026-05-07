
import numpy as np
import pandas as pd
from scipy import stats as _stats
from typing import Dict, Any, Optional

# Euler-Mascheroni constant (used by DSR)
_EULER_GAMMA = 0.5772156649015329

class MetricsEngine:
    """
    Tier 2 Metrics: Institutional Grade Scorecard.
    
    Centralized logic for calculating performance metrics across Research,
    Backtesting, and Live Trading.
    """
    
    @staticmethod
    def calculate_all(equity_curve: pd.Series, benchmark_curve: Optional[pd.Series] = None) -> Dict[str, float]:
        """
        Compute comprehensive metrics from an equity curve (daily or intraday).
        """
        if equity_curve.empty or len(equity_curve) < 2:
            return MetricsEngine._empty_metrics()
            
        returns = equity_curve.pct_change().dropna()
        if len(returns) < 2 or returns.std() == 0:
             return MetricsEngine._empty_metrics()
        
        # 1. Basic Risk/Return
        total_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1.0
        cagr = MetricsEngine.cagr(equity_curve)
        sharpe = MetricsEngine.sharpe_ratio(returns)
        sortino = MetricsEngine.sortino_ratio(returns)
        max_dd = MetricsEngine.max_drawdown(equity_curve)
        calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0
        volatility = returns.std() * np.sqrt(252)
        
        # 2. Trade Statistics (Implied from curve)
        # Note: True trade stats require a trade log, but we can estimate from curve
        # Win Rate etc. requires distinct periods or trade list.
        # Here we only compute Time-Series metrics.
        
        # 3. Advanced Risk
        var_95 = MetricsEngine.value_at_risk(returns, 0.95)
        ulcer = MetricsEngine.ulcer_index(equity_curve)
        skew = MetricsEngine.skewness(returns)
        ex_kurt = MetricsEngine.excess_kurtosis(returns)
        tail = MetricsEngine.tail_ratio(returns)

        # 4. Statistical Sharpe — sample-size + skew + kurtosis aware
        # PSR > benchmark Sharpe is the right "is this Sharpe real" gate
        psr_above_zero = MetricsEngine.probabilistic_sharpe_ratio(returns, 0.0)

        # 5. Benchmark Relative
        beta = 0.0
        alpha = 0.0
        info_ratio = 0.0
        if benchmark_curve is not None and not benchmark_curve.empty:
            # Align
            bench_returns = benchmark_curve.pct_change().dropna()
            aligned = pd.concat([returns, bench_returns], axis=1, join="inner").dropna()
            if not aligned.empty:
                beta = MetricsEngine.beta(aligned.iloc[:, 0], aligned.iloc[:, 1])
                # Alpha approx
                alpha = total_return - (beta * ((benchmark_curve.iloc[-1]/benchmark_curve.iloc[0]) - 1.0))
                info_ratio = MetricsEngine.information_ratio(aligned.iloc[:, 0], aligned.iloc[:, 1])

        return {
            "Total Return %": total_return * 100,
            "CAGR %": cagr * 100,
            "Sharpe": sharpe,
            "Sortino": sortino,
            "PSR": psr_above_zero,
            "Max Drawdown %": max_dd * 100,
            "Calmar": calmar,
            "Ulcer Index": ulcer,
            "Volatility %": volatility * 100,
            "VaR 95%": var_95 * 100,
            "Skewness": skew,
            "Excess Kurtosis": ex_kurt,
            "Tail Ratio": tail,
            "Beta": beta,
            "Alpha": alpha,
            "Information Ratio": info_ratio,
        }

    @staticmethod
    def _empty_metrics():
        return {k: 0.0 for k in [
            "Total Return %", "CAGR %", "Sharpe", "Sortino", "PSR",
            "Max Drawdown %", "Calmar", "Ulcer Index", "Volatility %",
            "VaR 95%", "Skewness", "Excess Kurtosis", "Tail Ratio",
            "Beta", "Alpha", "Information Ratio",
        ]}

    @staticmethod
    def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0, periods: int = 252) -> float:
        if returns.std() == 0: return 0.0
        return (returns.mean() - risk_free_rate) / returns.std() * np.sqrt(periods)

    @staticmethod
    def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0, periods: int = 252) -> float:
        downside = returns[returns < 0]
        if downside.empty or downside.std() == 0: return 10.0 # Capped max
        return (returns.mean() - risk_free_rate) / downside.std() * np.sqrt(periods)

    @staticmethod
    def max_drawdown(equity_curve: pd.Series) -> float:
        """Returns positive number 0.15 for 15% drawdown, or strictly negative? Convention: Negative."""
        roll_max = equity_curve.cummax()
        drawdown = (equity_curve - roll_max) / roll_max
        return float(drawdown.min())

    @staticmethod
    def cagr(equity_curve: pd.Series) -> float:
        if len(equity_curve) < 2: return 0.0
        start = equity_curve.index[0]
        end = equity_curve.index[-1]
        years = (end - start).days / 365.25
        if years < 0.1: return 0.0 # Too short
        total_ret = equity_curve.iloc[-1] / equity_curve.iloc[0]
        if total_ret <= 0: return -1.0
        return float(total_ret ** (1 / years) - 1)

    @staticmethod
    def beta(strategy_rets: pd.Series, benchmark_rets: pd.Series) -> float:
        cov = strategy_rets.cov(benchmark_rets)
        var = benchmark_rets.var()
        if var == 0: return 0.0
        return float(cov / var)
        
    @staticmethod
    def value_at_risk(returns: pd.Series, confidence: float = 0.95) -> float:
        """
        Historical VaR.
        """
        return float(np.percentile(returns, 100 * (1 - confidence)))
    
    @staticmethod
    def sqn(trades_pnl: pd.Series) -> float:
        """
        System Quality Number (Tharp).
        Expectancy / StdDev * sqrt(N)
        """
        if len(trades_pnl) < 2 or trades_pnl.std() == 0: return 0.0
        return (trades_pnl.mean() / trades_pnl.std()) * np.sqrt(len(trades_pnl))

    @staticmethod
    def kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
        """
        Kelly = W - (1-W)/R
        """
        if win_loss_ratio == 0: return 0.0
        return win_rate - (1 - win_rate) / win_loss_ratio

    @staticmethod
    def probabilistic_sharpe_ratio(
        returns: pd.Series,
        sr_benchmark_annualized: float = 0.0,
        periods: int = 252,
    ) -> float:
        """
        Probabilistic Sharpe Ratio (Bailey & Lopez de Prado 2012).

        Probability that the true (population) annualized Sharpe ratio
        exceeds ``sr_benchmark_annualized``, accounting for sample size,
        skewness, and excess kurtosis. Output in [0, 1].

        Reference: Bailey, D. and Lopez de Prado, M. (2012),
        "The Sharpe Ratio Efficient Frontier", Journal of Risk 15(2).
        """
        if returns is None or len(returns) < 4:
            return 0.0
        std = float(returns.std(ddof=1))
        if std == 0.0:
            return 0.0
        n = int(len(returns))
        # Non-annualized (per-period) sample Sharpe — formula is on this scale
        sr_hat = float(returns.mean()) / std
        # Convert annualized benchmark to per-period scale
        sr_bench = float(sr_benchmark_annualized) / np.sqrt(periods)
        skew = float(_stats.skew(returns, bias=False))
        # Pearson kurtosis (not excess) — formula uses (γ4 - 1)/4 with γ4 = E[(x-μ)^4/σ^4]
        kurt_pearson = float(_stats.kurtosis(returns, fisher=False, bias=False))
        denom_inner = 1.0 - skew * sr_hat + ((kurt_pearson - 1.0) / 4.0) * (sr_hat ** 2)
        if denom_inner <= 0.0:
            return 0.0
        sigma_sr = np.sqrt(denom_inner / (n - 1))
        if sigma_sr == 0.0:
            return 1.0 if sr_hat > sr_bench else 0.0
        z = (sr_hat - sr_bench) / sigma_sr
        return float(_stats.norm.cdf(z))

    @staticmethod
    def deflated_sharpe_ratio(
        returns: pd.Series,
        n_trials: int,
        periods: int = 252,
    ) -> float:
        """
        Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).

        PSR with the benchmark set to ``E[max SR_i]`` under the null of
        ``n_trials`` independent strategies, correcting for selection bias
        from multiple testing. Output in [0, 1].

        Variance of trial Sharpes is approximated from the observed series'
        standard error of SR (per Bailey-Lopez de Prado closed-form).

        Reference: Bailey, D. and Lopez de Prado, M. (2014), "The Deflated
        Sharpe Ratio", Journal of Portfolio Management 40(5).
        """
        if returns is None or len(returns) < 4 or n_trials < 1:
            return 0.0
        n = int(len(returns))
        # Variance of SR across the trials, approximated by the per-period
        # SR standard error of the observed series
        std = float(returns.std(ddof=1))
        if std == 0.0:
            return 0.0
        sr_hat = float(returns.mean()) / std
        skew = float(_stats.skew(returns, bias=False))
        kurt_pearson = float(_stats.kurtosis(returns, fisher=False, bias=False))
        denom_inner = 1.0 - skew * sr_hat + ((kurt_pearson - 1.0) / 4.0) * (sr_hat ** 2)
        if denom_inner <= 0.0:
            return 0.0
        v_sr = denom_inner / (n - 1)
        sigma_sr = np.sqrt(v_sr)
        if n_trials == 1:
            sr_zero = 0.0  # No selection bias to correct for
        else:
            # Expected max of n_trials i.i.d. standard normals (per BLdP):
            # E[max] ≈ (1 - γ) Φ⁻¹(1 - 1/N) + γ Φ⁻¹(1 - 1/(N e))
            phi_inv_a = float(_stats.norm.ppf(1.0 - 1.0 / n_trials))
            phi_inv_b = float(_stats.norm.ppf(1.0 - 1.0 / (n_trials * np.e)))
            sr_zero_per_period = sigma_sr * (
                (1.0 - _EULER_GAMMA) * phi_inv_a + _EULER_GAMMA * phi_inv_b
            )
            sr_zero = sr_zero_per_period * np.sqrt(periods)  # annualize
        return MetricsEngine.probabilistic_sharpe_ratio(
            returns, sr_benchmark_annualized=sr_zero, periods=periods
        )

    @staticmethod
    def information_ratio(
        strategy_rets: pd.Series,
        benchmark_rets: pd.Series,
        periods: int = 252,
    ) -> float:
        """
        Information Ratio: annualized active-return / tracking error.

        IR = mean(strat_ret - bench_ret) / std(strat_ret - bench_ret) * sqrt(periods)

        The right metric for "beat the benchmark significantly" — Sharpe
        confounds market exposure with skill; IR isolates the active component.
        """
        if strategy_rets is None or benchmark_rets is None:
            return 0.0
        active = (strategy_rets - benchmark_rets).dropna()
        if len(active) < 2 or active.std(ddof=1) == 0.0:
            return 0.0
        return float(active.mean() / active.std(ddof=1) * np.sqrt(periods))

    @staticmethod
    def tail_ratio(returns: pd.Series, percentile: float = 0.05) -> float:
        """
        Tail Ratio: |avg of top tail| / |avg of bottom tail|.

        > 1.0 means right tail is fatter than left (good for asymmetric-upside).
        < 1.0 means left tail is fatter (negative skew; common in momentum strategies).

        ``percentile`` is each tail's mass (default 5%, so top 5% vs bottom 5%).
        """
        if returns is None or len(returns) < int(1 / max(percentile, 1e-9)):
            return 0.0
        upper = returns.quantile(1.0 - percentile)
        lower = returns.quantile(percentile)
        top_tail = returns[returns >= upper]
        bot_tail = returns[returns <= lower]
        if bot_tail.empty or top_tail.empty:
            return 0.0
        bot_mean = bot_tail.mean()
        if bot_mean == 0.0:
            return 0.0
        return float(abs(top_tail.mean()) / abs(bot_mean))

    @staticmethod
    def skewness(returns: pd.Series) -> float:
        """Sample skewness (γ_3) — flags asymmetric return distributions."""
        if returns is None or len(returns) < 3:
            return 0.0
        return float(_stats.skew(returns, bias=False))

    @staticmethod
    def excess_kurtosis(returns: pd.Series) -> float:
        """
        Excess kurtosis (Fisher; normal distribution → 0).

        Positive = fat tails, negative = thin tails. Important for any
        strategy whose Sharpe assumes Gaussian returns.
        """
        if returns is None or len(returns) < 4:
            return 0.0
        return float(_stats.kurtosis(returns, fisher=True, bias=False))

    @staticmethod
    def ulcer_index(equity_curve: pd.Series) -> float:
        """
        Ulcer Index (Martin & McCann): RMS of percent drawdowns.

        Captures both depth AND duration of drawdowns, unlike max_drawdown
        which is depth-only. Better aligned with the psychological pain of
        being underwater for extended periods.
        """
        if equity_curve is None or len(equity_curve) < 2:
            return 0.0
        roll_max = equity_curve.cummax()
        drawdown_pct = (equity_curve - roll_max) / roll_max * 100.0
        return float(np.sqrt((drawdown_pct ** 2).mean()))
