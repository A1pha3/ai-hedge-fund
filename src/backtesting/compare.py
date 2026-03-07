from __future__ import annotations

from dataclasses import dataclass
from math import erfc, sqrt
from pathlib import Path
from statistics import mean, stdev
from typing import Callable, Sequence

from src.execution.daily_pipeline import DailyPipeline
from src.execution.layer_c_aggregator import aggregate_layer_c_results
from src.execution.models import ExecutionPlan
from src.execution.plan_generator import generate_execution_plan
from src.screening.market_state import detect_market_state
from src.screening.models import FusedScore
from src.tools.tushare_api import get_ashare_daily_gainers_with_tushare

from .engine import BacktestEngine
from .types import PerformanceMetrics
from .walk_forward import WalkForwardWindow, build_walk_forward_windows


def _baseline_fused_score(ticker: str, market_state) -> FusedScore:
    return FusedScore(
        ticker=ticker,
        score_b=0.0,
        strategy_signals={},
        arbitration_applied=[],
        market_state=market_state,
        weights_used=market_state.adjusted_weights,
        decision="watch",
    )


@dataclass
class BaselineDailyGainersPipeline(DailyPipeline):
    pct_threshold: float = 3.0
    top_n: int = 20

    def run_post_market(self, trade_date: str, portfolio_snapshot: dict | None = None) -> ExecutionPlan:
        portfolio_snapshot = portfolio_snapshot or {"cash": 1_000_000, "positions": {}}
        market_state = detect_market_state(trade_date)
        gainers = get_ashare_daily_gainers_with_tushare(trade_date, pct_threshold=self.pct_threshold, include_name=True)
        selected = gainers[: self.top_n]
        tickers = [str(item["ts_code"]).split(".")[0] for item in selected if item.get("ts_code")]

        agent_results = self.agent_runner(tickers, trade_date, "precise") if tickers else {}
        fused = [_baseline_fused_score(ticker, market_state) for ticker in tickers]
        layer_c_results = aggregate_layer_c_results(fused, agent_results)
        watchlist = [item for item in layer_c_results if item.score_final >= 0.25 and item.decision != "avoid"]
        buy_orders = self._build_buy_orders(watchlist, portfolio_snapshot)
        sell_orders = self.exit_checker(portfolio_snapshot, trade_date)
        return generate_execution_plan(
            trade_date=trade_date,
            market_state=market_state,
            watchlist=watchlist,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
            portfolio_snapshot=portfolio_snapshot,
            risk_alerts=[],
            risk_metrics={"baseline_strategy": "daily_gainers"},
            layer_a_count=len(selected),
            layer_b_count=0,
        )


@dataclass(frozen=True)
class ABWindowMetrics:
    window: WalkForwardWindow
    baseline: PerformanceMetrics
    mvp: PerformanceMetrics


def _average_metric(metrics_list: Sequence[PerformanceMetrics], key: str) -> float | None:
    values = [metrics.get(key) for metrics in metrics_list if metrics.get(key) is not None]
    if not values:
        return None
    return float(sum(values) / len(values))


def _one_sided_normal_pvalue(deltas: Sequence[float]) -> float | None:
    if len(deltas) < 2:
        return None
    delta_std = stdev(deltas)
    if delta_std == 0:
        return 0.0 if mean(deltas) > 0 else 1.0
    z_score = mean(deltas) / (delta_std / sqrt(len(deltas)))
    return 0.5 * erfc(z_score / sqrt(2.0))


def run_ab_comparison_walk_forward(
    *,
    tickers: list[str],
    start_date: str,
    end_date: str,
    initial_capital: float,
    model_name: str,
    model_provider: str,
    selected_analysts: list[str] | None,
    initial_margin_requirement: float,
    agent: Callable,
    train_months: int = 2,
    test_months: int = 1,
    step_months: int = 1,
    baseline_pct_threshold: float = 3.0,
    baseline_top_n: int = 20,
) -> tuple[list[ABWindowMetrics], dict[str, float | int | None]]:
    windows = build_walk_forward_windows(
        start_date,
        end_date,
        train_months=train_months,
        test_months=test_months,
        step_months=step_months,
    )

    results: list[ABWindowMetrics] = []
    for window in windows:
        baseline_engine = BacktestEngine(
            agent=agent,
            tickers=tickers,
            start_date=window.test_start,
            end_date=window.test_end,
            initial_capital=initial_capital,
            model_name=model_name,
            model_provider=model_provider,
            selected_analysts=selected_analysts,
            initial_margin_requirement=initial_margin_requirement,
            backtest_mode="pipeline",
            pipeline=BaselineDailyGainersPipeline(pct_threshold=baseline_pct_threshold, top_n=baseline_top_n),
        )
        mvp_engine = BacktestEngine(
            agent=agent,
            tickers=tickers,
            start_date=window.test_start,
            end_date=window.test_end,
            initial_capital=initial_capital,
            model_name=model_name,
            model_provider=model_provider,
            selected_analysts=selected_analysts,
            initial_margin_requirement=initial_margin_requirement,
            backtest_mode="pipeline",
            pipeline=DailyPipeline(),
        )
        results.append(
            ABWindowMetrics(
                window=window,
                baseline=baseline_engine.run_backtest(),
                mvp=mvp_engine.run_backtest(),
            )
        )

    baseline_metrics = [item.baseline for item in results]
    mvp_metrics = [item.mvp for item in results]
    sortino_deltas = [
        float(item.mvp.get("sortino_ratio", 0.0) or 0.0) - float(item.baseline.get("sortino_ratio", 0.0) or 0.0)
        for item in results
    ]
    summary = {
        "window_count": len(results),
        "baseline_avg_sharpe": _average_metric(baseline_metrics, "sharpe_ratio"),
        "baseline_avg_sortino": _average_metric(baseline_metrics, "sortino_ratio"),
        "mvp_avg_sharpe": _average_metric(mvp_metrics, "sharpe_ratio"),
        "mvp_avg_sortino": _average_metric(mvp_metrics, "sortino_ratio"),
        "baseline_avg_max_drawdown": _average_metric(baseline_metrics, "max_drawdown"),
        "mvp_avg_max_drawdown": _average_metric(mvp_metrics, "max_drawdown"),
        "avg_sortino_delta": mean(sortino_deltas) if sortino_deltas else None,
        "sortino_p_value_estimate": _one_sided_normal_pvalue(sortino_deltas),
    }
    return results, summary


def format_ab_comparison_report(results: Sequence[ABWindowMetrics], summary: dict[str, float | int | None]) -> str:
    lines = [
        "# A/B Walk-Forward Comparison",
        "",
        "| Window | Baseline Sharpe | MVP Sharpe | Baseline Sortino | MVP Sortino | Baseline MDD | MVP MDD |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in results:
        lines.append(
            "| {window} | {b_sharpe:.2f} | {m_sharpe:.2f} | {b_sortino:.2f} | {m_sortino:.2f} | {b_mdd:.2f} | {m_mdd:.2f} |".format(
                window=f"{item.window.test_start}..{item.window.test_end}",
                b_sharpe=float(item.baseline.get("sharpe_ratio", 0.0) or 0.0),
                m_sharpe=float(item.mvp.get("sharpe_ratio", 0.0) or 0.0),
                b_sortino=float(item.baseline.get("sortino_ratio", 0.0) or 0.0),
                m_sortino=float(item.mvp.get("sortino_ratio", 0.0) or 0.0),
                b_mdd=float(item.baseline.get("max_drawdown", 0.0) or 0.0),
                m_mdd=float(item.mvp.get("max_drawdown", 0.0) or 0.0),
            )
        )

    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Windows: {summary['window_count']}",
            f"- Baseline Avg Sharpe: {float(summary['baseline_avg_sharpe'] or 0.0):.2f}",
            f"- MVP Avg Sharpe: {float(summary['mvp_avg_sharpe'] or 0.0):.2f}",
            f"- Baseline Avg Sortino: {float(summary['baseline_avg_sortino'] or 0.0):.2f}",
            f"- MVP Avg Sortino: {float(summary['mvp_avg_sortino'] or 0.0):.2f}",
            f"- Avg Sortino Delta: {float(summary['avg_sortino_delta'] or 0.0):.2f}",
        ]
    )
    if summary.get("sortino_p_value_estimate") is not None:
        lines.append(f"- One-sided p-value estimate: {float(summary['sortino_p_value_estimate']):.4f}")
    lines.append("")
    lines.append("注：当前 p 值为正态近似估计，用于轻量化本地验证；若要做正式研究结论，建议后续引入精确统计检验。")
    return "\n".join(lines)


def save_ab_comparison_report(report: str, output_path: str | None = None) -> Path:
    if output_path is not None:
        path = Path(output_path)
    else:
        report_dir = Path(__file__).resolve().parents[2] / "data" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / "ab_walk_forward_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return path
