from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from src.backtesting.types import PerformanceMetrics
    from src.paper_trading.runtime import PaperTradingArtifacts, SessionRuntimeContext


def build_runtime_session_summary_metadata(
    *,
    context: "SessionRuntimeContext",
    start_date: str,
    end_date: str,
    tickers: list[str] | None,
    initial_capital: float,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
) -> dict:
    return {
        "start_date": start_date,
        "end_date": end_date,
        "tickers": tickers,
        "initial_capital": initial_capital,
        "resolved_model_name": context.resolved_model_name,
        "resolved_model_provider": context.resolved_model_provider,
        "selected_analysts": selected_analysts,
        "fast_selected_analysts": fast_selected_analysts,
        "short_trade_target_profile_name": short_trade_target_profile_name,
        "short_trade_target_profile_overrides": short_trade_target_profile_overrides,
        "frozen_plan_source_path": context.session_paths.frozen_plan_source_path,
        "selection_target": selection_target,
    }


def build_runtime_session_monitoring_inputs(monitoring_summary: dict) -> dict:
    return {
        "llm_route_provenance": monitoring_summary["llm_route_provenance"],
        "execution_plan_provenance": monitoring_summary["execution_plan_provenance"],
        "dual_target_summary": monitoring_summary["dual_target_summary"],
        "llm_observability_summary": monitoring_summary["llm_observability_summary"],
        "llm_error_digest": monitoring_summary["llm_error_digest"],
    }


def build_runtime_session_recorder_inputs(context: "SessionRuntimeContext") -> dict:
    return {
        "recorder_day_count": context.recorder.day_count,
        "recorder_executed_trade_days": context.recorder.executed_trade_days,
        "recorder_total_executed_orders": context.recorder.total_executed_orders,
    }


def build_runtime_session_artifact_inputs(
    *,
    context: "SessionRuntimeContext",
    feedback_summary_path: Path,
    cache_benchmark_artifacts: dict,
    llm_metrics_artifacts: dict,
) -> dict:
    return {
        "daily_events_path": context.session_paths.daily_events_path,
        "timing_log_path": context.session_paths.timing_log_path,
        "summary_path": context.session_paths.summary_path,
        "selection_artifact_root": context.session_paths.selection_artifact_root,
        "feedback_summary_path": feedback_summary_path,
        "cache_benchmark_artifacts": cache_benchmark_artifacts,
        "llm_metrics_artifacts": llm_metrics_artifacts,
    }


def build_runtime_session_summary_inputs(
    *,
    context: "SessionRuntimeContext",
    metrics: "PerformanceMetrics",
    start_date: str,
    end_date: str,
    tickers: list[str] | None,
    initial_capital: float,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    research_feedback_summary: dict,
    feedback_summary_path: Path,
    monitoring_summary: dict,
    data_cache_summary: dict,
    cache_benchmark_summary: dict,
    cache_benchmark_artifacts: dict,
    cache_benchmark_status: str,
    serialize_portfolio_values_fn: Callable[[Any], list[dict]],
) -> dict:
    return {
        **build_runtime_session_summary_metadata(
            context=context,
            start_date=start_date,
            end_date=end_date,
            tickers=tickers,
            initial_capital=initial_capital,
            selected_analysts=selected_analysts,
            fast_selected_analysts=fast_selected_analysts,
            short_trade_target_profile_name=short_trade_target_profile_name,
            short_trade_target_profile_overrides=short_trade_target_profile_overrides,
            selection_target=selection_target,
        ),
        "metrics": dict(metrics),
        "portfolio_values": serialize_portfolio_values_fn(context.engine.get_portfolio_values()),
        "final_portfolio_snapshot": context.engine.get_portfolio_snapshot(),
        **build_runtime_session_monitoring_inputs(monitoring_summary),
        "data_cache_summary": data_cache_summary,
        "cache_benchmark_summary": cache_benchmark_summary,
        "cache_benchmark_status": cache_benchmark_status,
        "research_feedback_summary": research_feedback_summary,
        **build_runtime_session_recorder_inputs(context),
        **build_runtime_session_artifact_inputs(
            context=context,
            feedback_summary_path=feedback_summary_path,
            cache_benchmark_artifacts=cache_benchmark_artifacts,
            llm_metrics_artifacts=monitoring_summary["llm_metrics_artifacts"],
        ),
    }


def build_runtime_finalization_inputs(
    *,
    context: "SessionRuntimeContext",
    metrics: "PerformanceMetrics",
    start_date: str,
    end_date: str,
    tickers: list[str] | None,
    initial_capital: float,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    cache_benchmark: bool,
    cache_benchmark_ticker: str | None,
    cache_benchmark_clear_first: bool,
) -> dict[str, Any]:
    return {
        "context": context,
        "metrics": metrics,
        "start_date": start_date,
        "end_date": end_date,
        "tickers": tickers,
        "initial_capital": initial_capital,
        "selected_analysts": selected_analysts,
        "fast_selected_analysts": fast_selected_analysts,
        "short_trade_target_profile_name": short_trade_target_profile_name,
        "short_trade_target_profile_overrides": short_trade_target_profile_overrides,
        "selection_target": selection_target,
        "cache_benchmark": cache_benchmark,
        "cache_benchmark_ticker": cache_benchmark_ticker,
        "cache_benchmark_clear_first": cache_benchmark_clear_first,
    }


def build_runtime_artifacts(
    *,
    context: "SessionRuntimeContext",
    feedback_summary_path: Path,
    paper_trading_artifacts_cls: type["PaperTradingArtifacts"],
) -> "PaperTradingArtifacts":
    return paper_trading_artifacts_cls(
        output_dir=context.session_paths.output_dir_path,
        daily_events_path=context.session_paths.daily_events_path,
        timing_log_path=context.session_paths.timing_log_path,
        summary_path=context.session_paths.summary_path,
        selection_artifact_root=context.session_paths.selection_artifact_root,
        feedback_summary_path=feedback_summary_path,
    )
