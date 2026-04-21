
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

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
        
        # 4. Benchmark Relative
        beta = 0.0
        alpha = 0.0
        if benchmark_curve is not None and not benchmark_curve.empty:
            # Align
            aligned = pd.concat([returns, benchmark_curve.pct_change().dropna()], axis=1, join="inner")
            if not aligned.empty:
                beta = MetricsEngine.beta(aligned.iloc[:, 0], aligned.iloc[:, 1])
                # Alpha approx
                alpha = total_return - (beta * ((benchmark_curve.iloc[-1]/benchmark_curve.iloc[0]) - 1.0))

        return {
            "Total Return %": total_return * 100,
            "CAGR %": cagr * 100,
            "Sharpe": sharpe,
            "Sortino": sortino,
            "Max Drawdown %": max_dd * 100,
            "Calmar": calmar,
            "Volatility %": volatility * 100,
            "VaR 95%": var_95 * 100,
            "Beta": beta,
            "Alpha": alpha
        }

    @staticmethod
    def _empty_metrics():
        return {k: 0.0 for k in ["Total Return %", "CAGR %", "Sharpe", "Sortino", "Max Drawdown %", "Calmar", "Volatility %", "VaR 95%", "Beta", "Alpha"]}

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
