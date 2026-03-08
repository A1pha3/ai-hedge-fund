from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import erfc, sqrt
from pathlib import Path
from statistics import mean, stdev
import json
from time import perf_counter
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


def _slice_agent_results(agent_results: dict[str, dict[str, dict]], tickers: list[str]) -> dict[str, dict[str, dict]]:
    requested = set(tickers)
    return {
        agent_id: {ticker: payload for ticker, payload in ticker_payload.items() if ticker in requested}
        for agent_id, ticker_payload in agent_results.items()
    }


def make_backtest_agent_runner(agent: Callable, model_name: str, model_provider: str) -> Callable[[list[str], str, str], dict[str, dict[str, dict]]]:
    cached_results_by_config: dict[tuple[str, str, str], dict[str, dict[str, dict]]] = {}
    cached_tickers_by_config: dict[tuple[str, str, str], set[str]] = {}

    def _runner(tickers: list[str], trade_date: str, model_tier: str) -> dict[str, dict[str, dict]]:
        del model_tier
        cache_key = (trade_date, model_provider, model_name)
        requested_tickers = set(tickers)
        cached_results = cached_results_by_config.get(cache_key)
        cached_tickers = cached_tickers_by_config.get(cache_key, set())
        if requested_tickers and cached_results is not None and requested_tickers.issubset(cached_tickers):
            return _slice_agent_results(cached_results, tickers)

        trade_dt = datetime.strptime(trade_date, "%Y%m%d")
        start_date = (trade_dt - timedelta(days=365)).strftime("%Y-%m-%d")
        end_date = trade_dt.strftime("%Y-%m-%d")
        result = agent(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            portfolio={"cash": 1_000_000, "positions": {}, "margin_requirement": 0.0, "margin_used": 0.0, "realized_gains": {}},
            show_reasoning=False,
            model_name=model_name,
            model_provider=model_provider,
        )
        analyst_signals = result.get("analyst_signals", {})
        if requested_tickers:
            cached_results_by_config[cache_key] = analyst_signals
            cached_tickers_by_config[cache_key] = requested_tickers
        return analyst_signals

    return _runner


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
    top_n: int = 10

    def run_post_market(self, trade_date: str, portfolio_snapshot: dict | None = None) -> ExecutionPlan:
        total_started_at = perf_counter()
        portfolio_snapshot = portfolio_snapshot or {"cash": 1_000_000, "positions": {}}

        stage_started_at = perf_counter()
        market_state = detect_market_state(trade_date)
        market_state_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        gainers = get_ashare_daily_gainers_with_tushare(trade_date, pct_threshold=self.pct_threshold, include_name=True)
        gainers_seconds = perf_counter() - stage_started_at
        selected = gainers[: self.top_n]
        tickers = [str(item["ts_code"]).split(".")[0] for item in selected if item.get("ts_code")]

        stage_started_at = perf_counter()
        agent_results = self.agent_runner(tickers, trade_date, "precise") if tickers else {}
        precise_agent_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        fused = [_baseline_fused_score(ticker, market_state) for ticker in tickers]
        layer_c_results = aggregate_layer_c_results(fused, agent_results)
        aggregate_layer_c_seconds = perf_counter() - stage_started_at
        watchlist = [item for item in layer_c_results if item.score_final >= 0.25 and item.decision != "avoid"]

        stage_started_at = perf_counter()
        buy_orders = self._build_buy_orders(watchlist, portfolio_snapshot)
        build_buy_orders_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        sell_orders = self.exit_checker(portfolio_snapshot, trade_date)
        sell_check_seconds = perf_counter() - stage_started_at

        timing_seconds = {
            "market_state": round(market_state_seconds, 3),
            "fetch_gainers": round(gainers_seconds, 3),
            "precise_agent": round(precise_agent_seconds, 3),
            "aggregate_layer_c": round(aggregate_layer_c_seconds, 3),
            "build_buy_orders": round(build_buy_orders_seconds, 3),
            "sell_check": round(sell_check_seconds, 3),
            "total_post_market": round(perf_counter() - total_started_at, 3),
        }
        return generate_execution_plan(
            trade_date=trade_date,
            market_state=market_state,
            watchlist=watchlist,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
            portfolio_snapshot=portfolio_snapshot,
            risk_alerts=[],
            risk_metrics={
                "baseline_strategy": "daily_gainers",
                "timing_seconds": timing_seconds,
                "counts": {
                    "selected_gainers_count": len(selected),
                    "precise_agent_ticker_count": len(tickers),
                    "layer_c_count": len(layer_c_results),
                    "watchlist_count": len(watchlist),
                    "buy_order_count": len(buy_orders),
                    "sell_order_count": len(sell_orders),
                },
            },
            layer_a_count=len(selected),
            layer_b_count=0,
        )


@dataclass(frozen=True)
class ABWindowMetrics:
    window: WalkForwardWindow
    baseline: PerformanceMetrics
    mvp: PerformanceMetrics

    def to_dict(self) -> dict:
        return {
            "window": {
                "train_start": self.window.train_start,
                "train_end": self.window.train_end,
                "test_start": self.window.test_start,
                "test_end": self.window.test_end,
            },
            "baseline": dict(self.baseline),
            "mvp": dict(self.mvp),
        }


def _window_key(window: WalkForwardWindow) -> str:
    return f"{window.train_start}_{window.train_end}_{window.test_start}_{window.test_end}"


def _load_compare_checkpoint(path: Path | None) -> dict[str, dict]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("windows", {})


def _save_compare_checkpoint(path: Path | None, windows_state: dict[str, dict]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"windows": windows_state}, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove_if_exists(path: Path | None) -> None:
    if path is not None and path.exists():
        path.unlink()


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
    baseline_top_n: int = 10,
    checkpoint_path: str | None = None,
) -> tuple[list[ABWindowMetrics], dict[str, float | int | None]]:
    windows = build_walk_forward_windows(
        start_date,
        end_date,
        train_months=train_months,
        test_months=test_months,
        step_months=step_months,
    )
    agent_runner = make_backtest_agent_runner(agent, model_name, model_provider)
    compare_checkpoint = Path(checkpoint_path) if checkpoint_path else None
    windows_state = _load_compare_checkpoint(compare_checkpoint)

    results: list[ABWindowMetrics] = []
    for index, window in enumerate(windows, start=1):
        window_state = windows_state.get(_window_key(window), {})
        baseline_metrics = window_state.get("baseline")
        mvp_metrics = window_state.get("mvp")
        baseline_checkpoint = compare_checkpoint.with_name(f"{compare_checkpoint.stem}.window{index}.baseline.engine.json") if compare_checkpoint else None
        mvp_checkpoint = compare_checkpoint.with_name(f"{compare_checkpoint.stem}.window{index}.mvp.engine.json") if compare_checkpoint else None

        if baseline_metrics is None:
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
                pipeline=BaselineDailyGainersPipeline(agent_runner=agent_runner, pct_threshold=baseline_pct_threshold, top_n=baseline_top_n),
                checkpoint_path=str(baseline_checkpoint) if baseline_checkpoint else None,
            )
            baseline_metrics = baseline_engine.run_backtest()
            window_state["baseline"] = baseline_metrics
            windows_state[_window_key(window)] = window_state
            _save_compare_checkpoint(compare_checkpoint, windows_state)

        if mvp_metrics is None:
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
                pipeline=DailyPipeline(agent_runner=agent_runner),
                checkpoint_path=str(mvp_checkpoint) if mvp_checkpoint else None,
            )
            mvp_metrics = mvp_engine.run_backtest()
            window_state["mvp"] = mvp_metrics
            windows_state[_window_key(window)] = window_state
            _save_compare_checkpoint(compare_checkpoint, windows_state)

        results.append(ABWindowMetrics(window=window, baseline=baseline_metrics, mvp=mvp_metrics))
        _remove_if_exists(baseline_checkpoint)
        _remove_if_exists(mvp_checkpoint)

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
    _remove_if_exists(compare_checkpoint)
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


def build_ab_comparison_payload(results: Sequence[ABWindowMetrics], summary: dict[str, float | int | None]) -> dict:
    return {
        "summary": summary,
        "windows": [item.to_dict() for item in results],
    }


def save_ab_comparison_payload(payload: dict, output_path: str | None = None) -> Path:
    if output_path is not None:
        path = Path(output_path)
    else:
        report_dir = Path(__file__).resolve().parents[2] / "data" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / "ab_walk_forward_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path
