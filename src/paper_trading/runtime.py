from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any
from collections.abc import Callable, Sequence

from src.backtesting.engine import BacktestEngine
from src.backtesting.types import PerformanceMetrics
from src.data.cache_benchmark import run_cache_reuse_benchmark
from src.data.enhanced_cache import diff_cache_stats, get_cache_runtime_info, snapshot_cache_stats
from src.execution.daily_pipeline import DailyPipeline
from src.llm.defaults import get_default_model_config
from src.main import run_hedge_fund
from src.monitoring.llm_metrics import get_llm_metrics_paths
from src.paper_trading.frozen_replay import load_frozen_post_market_plans
from src.paper_trading.runtime_context_helpers import (
    build_paper_trading_engine as build_paper_trading_engine_helper,
    build_runtime_engine_inputs as build_runtime_engine_inputs_helper,
    build_runtime_recorder as build_runtime_recorder_helper,
    build_runtime_recorder_and_engine as build_runtime_recorder_and_engine_helper,
    build_session_runtime_context as build_session_runtime_context_helper,
    prepare_session_runtime_context as prepare_session_runtime_context_helper,
    reset_runtime_outputs as reset_runtime_outputs_helper,
    resolve_runtime_model_config as resolve_runtime_model_config_helper,
    resolve_runtime_session_dependencies as resolve_runtime_session_dependencies_helper,
)
from src.paper_trading.runtime_finalization_helpers import (
    build_runtime_artifacts as build_runtime_artifacts_helper,
    build_runtime_finalization_inputs as build_runtime_finalization_inputs_helper,
    build_runtime_session_artifact_inputs as build_runtime_session_artifact_inputs_helper,
    build_runtime_session_monitoring_inputs as build_runtime_session_monitoring_inputs_helper,
    build_runtime_session_recorder_inputs as build_runtime_session_recorder_inputs_helper,
    build_runtime_session_summary_inputs as build_runtime_session_summary_inputs_helper,
    build_runtime_session_summary_metadata as build_runtime_session_summary_metadata_helper,
)
from src.paper_trading.runtime_observability_helpers import (
    build_dual_target_session_summary as build_dual_target_session_summary_helper,
    build_execution_plan_provenance_summary as build_execution_plan_provenance_summary_helper,
    build_llm_error_digest as build_llm_error_digest_helper,
    build_llm_observability_summary as build_llm_observability_summary_helper,
    build_llm_route_provenance as build_llm_route_provenance_helper,
)
from src.paper_trading.runtime_io_helpers import (
    promote_runtime_timing_log as promote_runtime_timing_log_helper,
    reset_output_artifacts_for_fresh_run as reset_output_artifacts_for_fresh_run_helper,
    write_research_feedback_summary as write_research_feedback_summary_helper,
    write_runtime_summary as write_runtime_summary_helper,
)
from src.paper_trading.runtime_infra_helpers import (
    JsonlPaperTradingRecorder,
    build_selection_artifact_writer as build_selection_artifact_writer_helper,
    serialize_portfolio_values as serialize_portfolio_values_helper,
)
from src.paper_trading.runtime_monitoring_helpers import (
    build_runtime_data_cache_summary as build_runtime_data_cache_summary_helper,
    build_runtime_monitoring_summary as build_runtime_monitoring_summary_helper,
    resolve_runtime_pipeline as resolve_runtime_pipeline_helper,
    run_runtime_cache_benchmark as run_runtime_cache_benchmark_helper,
)
from src.paper_trading.runtime_run_helpers import (
    finalize_runtime_run as finalize_runtime_run_helper,
    run_paper_trading_session as run_paper_trading_session_helper,
)
from src.paper_trading.runtime_session_helpers import build_session_summary, resolve_pipeline, resolve_session_paths, run_optional_cache_benchmark
from src.research.artifacts import FileSelectionArtifactWriter
from src.research.feedback import summarize_research_feedback_directory


def _serialize_portfolio_values(portfolio_values: Sequence[dict]) -> list[dict]:
    return serialize_portfolio_values_helper(portfolio_values)


def _build_llm_route_provenance() -> tuple[dict, dict]:
    return build_llm_route_provenance_helper(get_llm_metrics_paths_fn=get_llm_metrics_paths)


def _build_llm_error_digest(llm_route_provenance: dict, llm_observability_summary: dict) -> dict:
    return build_llm_error_digest_helper(llm_route_provenance, llm_observability_summary)


def _build_llm_observability_summary(jsonl_path: Path) -> dict:
    return build_llm_observability_summary_helper(jsonl_path)


def _build_execution_plan_provenance_summary(pipeline: DailyPipeline | None) -> dict:
    return build_execution_plan_provenance_summary_helper(pipeline)


def _build_dual_target_session_summary(daily_events_path: Path) -> dict:
    return build_dual_target_session_summary_helper(daily_events_path)


@dataclass(frozen=True)
class PaperTradingArtifacts:
    output_dir: Path
    daily_events_path: Path
    timing_log_path: Path
    summary_path: Path
    selection_artifact_root: Path
    feedback_summary_path: Path


@dataclass(frozen=True)
class SessionRuntimeContext:
    resolved_model_name: str
    resolved_model_provider: str
    session_paths: Any
    pipeline: DailyPipeline
    cache_stats_before_run: dict
    recorder: JsonlPaperTradingRecorder
    engine: BacktestEngine


def _reset_output_artifacts_for_fresh_run(
    *,
    checkpoint_path: Path,
    daily_events_path: Path,
    timing_log_path: Path,
    selection_artifact_root: Path,
) -> None:
    return reset_output_artifacts_for_fresh_run_helper(
        checkpoint_path=checkpoint_path,
        daily_events_path=daily_events_path,
        timing_log_path=timing_log_path,
        selection_artifact_root=selection_artifact_root,
    )


def _write_research_feedback_summary(selection_artifact_root: Path) -> tuple[dict, Path]:
    return write_research_feedback_summary_helper(
        selection_artifact_root,
        summarize_research_feedback_directory_fn=summarize_research_feedback_directory,
    )


def _prepare_session_runtime_context(
    *,
    output_dir: str | Path,
    frozen_plan_source: str | Path | None,
    model_name: str | None,
    model_provider: str | None,
    pipeline: DailyPipeline | None,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    agent: Callable,
    tickers: list[str] | None,
    start_date: str,
    end_date: str,
    initial_capital: float,
    initial_margin_requirement: float,
) -> SessionRuntimeContext:
    return prepare_session_runtime_context_helper(
        output_dir=output_dir,
        frozen_plan_source=frozen_plan_source,
        model_name=model_name,
        model_provider=model_provider,
        pipeline=pipeline,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        initial_margin_requirement=initial_margin_requirement,
        resolve_runtime_model_config_fn=_resolve_runtime_model_config,
        resolve_runtime_session_dependencies_fn=_resolve_runtime_session_dependencies,
        build_runtime_engine_inputs_fn=_build_runtime_engine_inputs,
        build_runtime_recorder_and_engine_fn=_build_runtime_recorder_and_engine,
        build_session_runtime_context_fn=_build_session_runtime_context,
    )


def _build_runtime_engine_inputs(
    *,
    agent: Callable,
    tickers: list[str] | None,
    start_date: str,
    end_date: str,
    initial_capital: float,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    initial_margin_requirement: float,
    pipeline: DailyPipeline,
    session_paths: Any,
) -> dict[str, Any]:
    return build_runtime_engine_inputs_helper(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=initial_margin_requirement,
        pipeline=pipeline,
        session_paths=session_paths,
    )


def _resolve_runtime_model_config(*, model_name: str | None, model_provider: str | None) -> tuple[str, str]:
    return resolve_runtime_model_config_helper(
        model_name=model_name,
        model_provider=model_provider,
        get_default_model_config_fn=get_default_model_config,
    )


def _reset_runtime_outputs(session_paths: Any) -> None:
    reset_runtime_outputs_helper(
        session_paths=session_paths,
        reset_output_artifacts_for_fresh_run_fn=_reset_output_artifacts_for_fresh_run,
    )


def _resolve_runtime_session_dependencies(
    *,
    output_dir: str | Path,
    frozen_plan_source: str | Path | None,
    pipeline: DailyPipeline | None,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
) -> tuple[Any, DailyPipeline]:
    return resolve_runtime_session_dependencies_helper(
        output_dir=output_dir,
        frozen_plan_source=frozen_plan_source,
        pipeline=pipeline,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        resolve_session_paths_fn=resolve_session_paths,
        reset_runtime_outputs_fn=_reset_runtime_outputs,
        resolve_runtime_pipeline_fn=_resolve_runtime_pipeline,
    )


def _build_session_runtime_context(
    *,
    resolved_model_name: str,
    resolved_model_provider: str,
    session_paths: Any,
    pipeline: DailyPipeline,
    recorder: JsonlPaperTradingRecorder,
    engine: BacktestEngine,
) -> SessionRuntimeContext:
    return build_session_runtime_context_helper(
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        session_paths=session_paths,
        pipeline=pipeline,
        recorder=recorder,
        engine=engine,
        snapshot_cache_stats_fn=snapshot_cache_stats,
        session_runtime_context_cls=SessionRuntimeContext,
    )


def _resolve_runtime_pipeline(
    *,
    pipeline: DailyPipeline | None,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    frozen_plan_source_path: Path | None,
) -> DailyPipeline:
    return resolve_runtime_pipeline_helper(
        pipeline=pipeline,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        frozen_plan_source_path=frozen_plan_source_path,
        resolve_pipeline_fn=resolve_pipeline,
        pipeline_cls=DailyPipeline,
        load_frozen_post_market_plans_fn=load_frozen_post_market_plans,
    )


def _build_runtime_recorder_and_engine(
    *,
    agent: Callable,
    tickers: list[str] | None,
    start_date: str,
    end_date: str,
    initial_capital: float,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    initial_margin_requirement: float,
    pipeline: DailyPipeline,
    session_paths: Any,
) -> tuple[JsonlPaperTradingRecorder, BacktestEngine]:
    return build_runtime_recorder_and_engine_helper(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=initial_margin_requirement,
        pipeline=pipeline,
        session_paths=session_paths,
        build_runtime_recorder_fn=_build_runtime_recorder,
        build_paper_trading_engine_fn=_build_paper_trading_engine,
    )


def _build_runtime_recorder(session_paths: Any) -> JsonlPaperTradingRecorder:
    return build_runtime_recorder_helper(
        session_paths=session_paths,
        recorder_cls=JsonlPaperTradingRecorder,
    )


def _build_paper_trading_engine(
    *,
    agent: Callable,
    tickers: list[str] | None,
    start_date: str,
    end_date: str,
    initial_capital: float,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    initial_margin_requirement: float,
    pipeline: DailyPipeline,
    session_paths,
    recorder: JsonlPaperTradingRecorder,
) -> BacktestEngine:
    return build_paper_trading_engine_helper(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=initial_margin_requirement,
        pipeline=pipeline,
        session_paths=session_paths,
        recorder=recorder,
        build_selection_artifact_writer_fn=_build_selection_artifact_writer,
        backtest_engine_cls=BacktestEngine,
    )


def _build_selection_artifact_writer(session_paths: Any) -> FileSelectionArtifactWriter:
    return build_selection_artifact_writer_helper(
        session_paths,
        selection_artifact_writer_cls=FileSelectionArtifactWriter,
    )


def _finalize_paper_trading_session(
    *,
    context: SessionRuntimeContext,
    metrics: PerformanceMetrics,
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
) -> tuple[dict, Path]:
    research_feedback_summary, feedback_summary_path = _write_research_feedback_summary(context.session_paths.selection_artifact_root)
    monitoring_summary = _build_runtime_monitoring_summary(context)
    data_cache_summary = _build_runtime_data_cache_summary(context)
    cache_benchmark_summary, cache_benchmark_artifacts, cache_benchmark_status = _run_runtime_cache_benchmark(
        context=context,
        cache_benchmark=cache_benchmark,
        cache_benchmark_ticker=cache_benchmark_ticker,
        tickers=tickers,
        end_date=end_date,
        cache_benchmark_clear_first=cache_benchmark_clear_first,
    )
    summary = build_session_summary(
        **_build_runtime_session_summary_inputs(
            context=context,
            metrics=metrics,
            start_date=start_date,
            end_date=end_date,
            tickers=tickers,
            initial_capital=initial_capital,
            selected_analysts=selected_analysts,
            fast_selected_analysts=fast_selected_analysts,
            short_trade_target_profile_name=short_trade_target_profile_name,
            short_trade_target_profile_overrides=short_trade_target_profile_overrides,
            selection_target=selection_target,
            research_feedback_summary=research_feedback_summary,
            feedback_summary_path=feedback_summary_path,
            monitoring_summary=monitoring_summary,
            data_cache_summary=data_cache_summary,
            cache_benchmark_summary=cache_benchmark_summary,
            cache_benchmark_artifacts=cache_benchmark_artifacts,
            cache_benchmark_status=cache_benchmark_status,
        )
    )
    _write_runtime_summary(context.session_paths.summary_path, summary)
    return summary, feedback_summary_path


def _build_runtime_session_summary_inputs(
    *,
    context: SessionRuntimeContext,
    metrics: PerformanceMetrics,
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
) -> dict:
    return build_runtime_session_summary_inputs_helper(
        context=context,
        metrics=metrics,
        start_date=start_date,
        end_date=end_date,
        tickers=tickers,
        initial_capital=initial_capital,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        research_feedback_summary=research_feedback_summary,
        feedback_summary_path=feedback_summary_path,
        monitoring_summary=monitoring_summary,
        data_cache_summary=data_cache_summary,
        cache_benchmark_summary=cache_benchmark_summary,
        cache_benchmark_artifacts=cache_benchmark_artifacts,
        cache_benchmark_status=cache_benchmark_status,
        serialize_portfolio_values_fn=_serialize_portfolio_values,
    )


def _build_runtime_session_summary_metadata(
    *,
    context: SessionRuntimeContext,
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
    return build_runtime_session_summary_metadata_helper(
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
    )


def _build_runtime_session_monitoring_inputs(monitoring_summary: dict) -> dict:
    return build_runtime_session_monitoring_inputs_helper(monitoring_summary)


def _build_runtime_session_recorder_inputs(context: SessionRuntimeContext) -> dict:
    return build_runtime_session_recorder_inputs_helper(context)


def _build_runtime_session_artifact_inputs(
    *,
    context: SessionRuntimeContext,
    feedback_summary_path: Path,
    cache_benchmark_artifacts: dict,
    llm_metrics_artifacts: dict,
) -> dict:
    return build_runtime_session_artifact_inputs_helper(
        context=context,
        feedback_summary_path=feedback_summary_path,
        cache_benchmark_artifacts=cache_benchmark_artifacts,
        llm_metrics_artifacts=llm_metrics_artifacts,
    )


def _build_runtime_monitoring_summary(context: SessionRuntimeContext) -> dict:
    return build_runtime_monitoring_summary_helper(
        context,
        build_llm_route_provenance_fn=_build_llm_route_provenance,
        build_llm_observability_summary_fn=_build_llm_observability_summary,
        build_llm_error_digest_fn=_build_llm_error_digest,
        build_execution_plan_provenance_summary_fn=_build_execution_plan_provenance_summary,
        build_dual_target_session_summary_fn=_build_dual_target_session_summary,
    )


def _build_runtime_data_cache_summary(context: SessionRuntimeContext) -> dict:
    return build_runtime_data_cache_summary_helper(
        context,
        get_cache_runtime_info_fn=get_cache_runtime_info,
        diff_cache_stats_fn=diff_cache_stats,
    )


def _run_runtime_cache_benchmark(
    *,
    context: SessionRuntimeContext,
    cache_benchmark: bool,
    cache_benchmark_ticker: str | None,
    tickers: list[str] | None,
    end_date: str,
    cache_benchmark_clear_first: bool,
) -> tuple[dict, dict, str]:
    return run_runtime_cache_benchmark_helper(
        context=context,
        cache_benchmark=cache_benchmark,
        cache_benchmark_ticker=cache_benchmark_ticker,
        tickers=tickers,
        end_date=end_date,
        cache_benchmark_clear_first=cache_benchmark_clear_first,
        run_optional_cache_benchmark_fn=run_optional_cache_benchmark,
        run_cache_reuse_benchmark_fn=run_cache_reuse_benchmark,
        repo_root=Path(__file__).resolve().parents[2],
        python_executable=sys.executable,
    )


def _write_runtime_summary(summary_path: Path, summary: dict) -> None:
    return write_runtime_summary_helper(summary_path, summary)


def _promote_runtime_timing_log(context: SessionRuntimeContext) -> None:
    return promote_runtime_timing_log_helper(context)


def _build_runtime_artifacts(context: SessionRuntimeContext, feedback_summary_path: Path) -> PaperTradingArtifacts:
    return build_runtime_artifacts_helper(
        context=context,
        feedback_summary_path=feedback_summary_path,
        paper_trading_artifacts_cls=PaperTradingArtifacts,
    )


def _run_runtime_backtest(context: SessionRuntimeContext) -> PerformanceMetrics:
    metrics: PerformanceMetrics = context.engine.run_backtest()
    _promote_runtime_timing_log(context)
    return metrics


def _finalize_runtime_run(
    *,
    context: SessionRuntimeContext,
    metrics: PerformanceMetrics,
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
) -> PaperTradingArtifacts:
    return finalize_runtime_run_helper(
        context=context,
        metrics=metrics,
        start_date=start_date,
        end_date=end_date,
        tickers=tickers,
        initial_capital=initial_capital,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        cache_benchmark=cache_benchmark,
        cache_benchmark_ticker=cache_benchmark_ticker,
        cache_benchmark_clear_first=cache_benchmark_clear_first,
        build_runtime_finalization_inputs_fn=_build_runtime_finalization_inputs,
        finalize_paper_trading_session_fn=_finalize_paper_trading_session,
        build_runtime_artifacts_fn=_build_runtime_artifacts,
    )


def _build_runtime_finalization_inputs(
    *,
    context: SessionRuntimeContext,
    metrics: PerformanceMetrics,
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
    return build_runtime_finalization_inputs_helper(
        context=context,
        metrics=metrics,
        start_date=start_date,
        end_date=end_date,
        tickers=tickers,
        initial_capital=initial_capital,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        cache_benchmark=cache_benchmark,
        cache_benchmark_ticker=cache_benchmark_ticker,
        cache_benchmark_clear_first=cache_benchmark_clear_first,
    )


def run_paper_trading_session(
    *,
    start_date: str,
    end_date: str,
    output_dir: str | Path,
    tickers: list[str] | None = None,
    initial_capital: float = 100000.0,
    model_name: str | None = None,
    model_provider: str | None = None,
    selected_analysts: list[str] | None = None,
    fast_selected_analysts: list[str] | None = None,
    short_trade_target_profile_name: str = "default",
    short_trade_target_profile_overrides: dict[str, object] | None = None,
    initial_margin_requirement: float = 0.0,
    agent: Callable = run_hedge_fund,
    pipeline: DailyPipeline | None = None,
    frozen_plan_source: str | Path | None = None,
    selection_target: str = "research_only",
    cache_benchmark: bool = False,
    cache_benchmark_ticker: str | None = None,
    cache_benchmark_clear_first: bool = False,
) -> PaperTradingArtifacts:
    return run_paper_trading_session_helper(
        start_date=start_date,
        end_date=end_date,
        output_dir=output_dir,
        tickers=tickers,
        initial_capital=initial_capital,
        model_name=model_name,
        model_provider=model_provider,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        initial_margin_requirement=initial_margin_requirement,
        agent=agent,
        pipeline=pipeline,
        frozen_plan_source=frozen_plan_source,
        selection_target=selection_target,
        cache_benchmark=cache_benchmark,
        cache_benchmark_ticker=cache_benchmark_ticker,
        cache_benchmark_clear_first=cache_benchmark_clear_first,
        prepare_session_runtime_context_fn=_prepare_session_runtime_context,
        run_runtime_backtest_fn=_run_runtime_backtest,
        finalize_runtime_run_fn=_finalize_runtime_run,
    )
