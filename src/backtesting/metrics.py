from __future__ import annotations

import warnings
from collections.abc import Sequence

import numpy as np
import pandas as pd

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

        # Sortino ratio uses canonical downside deviation:
        #   σ_d = sqrt(mean(min(R - Rf, 0)²)) over ALL returns.
        # Positive deviations contribute 0 to the sum; denominator is N
        # (not n_neg - 1). See docs/bugs/2026-06-05 for derivation.
        downside_squared = np.minimum(excess.values, 0.0) ** 2
        downside_std = float(np.sqrt(np.mean(downside_squared)))
        if downside_std > 1e-12:
            sortino = float(np.sqrt(self.annual_trading_days) * (mean_excess / downside_std))
        elif mean_excess > 0:
            sortino = float("inf")
        else:
            sortino = 0.0

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

        # CVaR(95%) = mean of the worst 5% of daily returns (historical
        # simulation). Tail count is ceil(0.05 * N), k >= 1. See
        # docs/bugs/2026-06-05 for derivation rationale.
        # Minimum 20 observations required: with N<20 the tail is a single
        # point (ceil(0.05*N)=1), which is just the sample minimum, not a
        # meaningful conditional tail expectation.
        sorted_returns = np.sort(clean_returns.values)
        n_obs = len(sorted_returns)
        if n_obs < 20:
            cvar_95 = None
        else:
            tail_count = max(1, int(np.ceil(0.05 * n_obs)))
            cvar_95 = float(sorted_returns[:tail_count].mean())

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

        **Precondition**: both sequences must be aligned by date (same trading
        days in the same order). If lengths differ, only the overlapping prefix
        is used — this is a **silent truncation** and may produce a wrong beta
        if the series are offset (ALPHA-007 / GAMMA-005). Callers must ensure
        alignment before passing data here.
        """
        if len(portfolio_returns) < 10 or len(benchmark_returns) < 10:
            return None
        n = min(len(portfolio_returns), len(benchmark_returns))
        if len(portfolio_returns) != len(benchmark_returns):
            warnings.warn(
                f"compute_beta: portfolio_returns ({len(portfolio_returns)}) and "
                f"benchmark_returns ({len(benchmark_returns)}) have different lengths. "
                f"Using first {n} elements — results may be incorrect if series "
                f"are not date-aligned (ALPHA-007).",
                stacklevel=2,
            )
        pr = np.array(portfolio_returns[:n])
        br = np.array(benchmark_returns[:n])
        var_b = np.var(br, ddof=1)
        if var_b < 1e-12:
            return None
        cov_pb = np.cov(pr, br)[0][1]
        return float(cov_pb / var_b)

