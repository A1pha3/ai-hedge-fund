from __future__ import annotations

from collections.abc import Sequence

from .types import PerformanceMetrics, PortfolioValuePoint


class PerformanceMetricsCalculator:
    """Concrete metrics calculator like sharpe ratio, sortino ratio, max drawdown, etc."""

    def __init__(self, *, annual_trading_days: int = 252, annual_rf_rate: float = 0.0434) -> None:
        self.annual_trading_days = annual_trading_days
        self.annual_rf_rate = annual_rf_rate

    def update_metrics(self, metrics: PerformanceMetrics, values: Sequence[PortfolioValuePoint]) -> None:
        """Deprecated: mutate provided dict. Kept for backward compatibility."""
        computed = self.compute_metrics(values)
        if not computed:
            return
        metrics.update(computed)  # type: ignore[arg-type]

    def compute_metrics(self, values: Sequence[PortfolioValuePoint]) -> PerformanceMetrics:
        import numpy as np
        import pandas as pd

        if not values:
            return {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}

        df = pd.DataFrame(values)
        if df.empty or "Portfolio Value" not in df:
            return {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}

        df = df.set_index("Date")
        df["Daily Return"] = df["Portfolio Value"].pct_change()
        clean_returns = df["Daily Return"].dropna()
        if len(clean_returns) < 2:
            return {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}

        daily_rf = self.annual_rf_rate / self.annual_trading_days
        excess = clean_returns - daily_rf
        mean_excess = excess.mean()
        std_excess = excess.std()

        if std_excess > 1e-12:
            sharpe = float(np.sqrt(self.annual_trading_days) * (mean_excess / std_excess))
        else:
            sharpe = 0.0

        negative_excess = excess[excess < 0]
        if len(negative_excess) > 0:
            downside_std = negative_excess.std()
            if downside_std > 1e-12:
                sortino = float(np.sqrt(self.annual_trading_days) * (mean_excess / downside_std))
            else:
                sortino = float("inf") if mean_excess > 0 else 0.0
        else:
            sortino = float("inf") if mean_excess > 0 else 0.0

        rolling_max = df["Portfolio Value"].cummax()
        drawdown = (df["Portfolio Value"] - rolling_max) / rolling_max
        if len(drawdown) > 0:
            min_dd = float(drawdown.min())
            max_drawdown = float(min_dd * 100.0)
            if min_dd < 0:
                max_drawdown_date = drawdown.idxmin().strftime("%Y-%m-%d")
            else:
                max_drawdown_date = None
        else:
            max_drawdown = 0.0
            max_drawdown_date = None

        # --- Phase 0.3 新增指标 ---
        # Calmar Ratio = 年化收益 / |最大回撤|
        total_return = (df["Portfolio Value"].iloc[-1] / df["Portfolio Value"].iloc[0]) - 1
        trading_days = len(clean_returns)
        annual_return = (1 + total_return) ** (self.annual_trading_days / max(trading_days, 1)) - 1
        abs_mdd = abs(min_dd) if min_dd < 0 else 0
        calmar = float(annual_return / abs_mdd) if abs_mdd > 1e-12 else (float("inf") if annual_return > 0 else 0.0)

        # CVaR(95%) 历史模拟法
        sorted_returns = np.sort(clean_returns.values)
        var_index = int(np.floor(0.05 * len(sorted_returns)))
        if var_index > 0:
            cvar_95 = float(sorted_returns[:var_index].mean())
        else:
            cvar_95 = float(sorted_returns[0]) if len(sorted_returns) > 0 else 0.0

        return {
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "max_drawdown": max_drawdown,
            "max_drawdown_date": max_drawdown_date,
            "calmar_ratio": calmar,
            "cvar_95": cvar_95,
        }

    @staticmethod
    def compute_beta(portfolio_returns: Sequence[float], benchmark_returns: Sequence[float]) -> float | None:
        """
        计算组合 Beta（对基准指数的回归系数）。

        Beta = Cov(Rp, Rb) / Var(Rb)
        """
        import numpy as np

        if len(portfolio_returns) < 10 or len(benchmark_returns) < 10:
            return None
        pr = np.array(portfolio_returns[:min(len(portfolio_returns), len(benchmark_returns))])
        br = np.array(benchmark_returns[:min(len(portfolio_returns), len(benchmark_returns))])
        var_b = np.var(br)
        if var_b < 1e-12:
            return None
        cov_pb = np.cov(pr, br)[0][1]
        return float(cov_pb / var_b)
