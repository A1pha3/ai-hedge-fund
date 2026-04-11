from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from src.backtesting.engine import BacktestEngine
    from src.execution.daily_pipeline import DailyPipeline
    from src.paper_trading.runtime import JsonlPaperTradingRecorder, SessionRuntimeContext


def prepare_session_runtime_context(
    *,
    output_dir: str | Path,
    frozen_plan_source: str | Path | None,
    model_name: str | None,
    model_provider: str | None,
    pipeline: "DailyPipeline | None",
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
    resolve_runtime_model_config_fn: Callable[..., tuple[str, str]],
    resolve_runtime_session_dependencies_fn: Callable[..., tuple[Any, "DailyPipeline"]],
    build_runtime_engine_inputs_fn: Callable[..., dict[str, Any]],
    build_runtime_recorder_and_engine_fn: Callable[..., tuple["JsonlPaperTradingRecorder", "BacktestEngine"]],
    build_session_runtime_context_fn: Callable[..., "SessionRuntimeContext"],
) -> "SessionRuntimeContext":
    resolved_model_name, resolved_model_provider = resolve_runtime_model_config_fn(
        model_name=model_name,
        model_provider=model_provider,
    )
    session_paths, resolved_pipeline = resolve_runtime_session_dependencies_fn(
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
    )
    recorder, engine = build_runtime_recorder_and_engine_fn(
        **build_runtime_engine_inputs_fn(
            agent=agent,
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            resolved_model_name=resolved_model_name,
            resolved_model_provider=resolved_model_provider,
            selected_analysts=selected_analysts,
            initial_margin_requirement=initial_margin_requirement,
            pipeline=resolved_pipeline,
            session_paths=session_paths,
        )
    )
    return build_session_runtime_context_fn(
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        session_paths=session_paths,
        pipeline=resolved_pipeline,
        recorder=recorder,
        engine=engine,
    )


def build_runtime_engine_inputs(
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
    pipeline: "DailyPipeline",
    session_paths: Any,
) -> dict[str, Any]:
    return {
        "agent": agent,
        "tickers": tickers,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "resolved_model_name": resolved_model_name,
        "resolved_model_provider": resolved_model_provider,
        "selected_analysts": selected_analysts,
        "initial_margin_requirement": initial_margin_requirement,
        "pipeline": pipeline,
        "session_paths": session_paths,
    }


def resolve_runtime_model_config(
    *,
    model_name: str | None,
    model_provider: str | None,
    get_default_model_config_fn: Callable[[], tuple[str, str]],
) -> tuple[str, str]:
    return (model_name, model_provider) if model_name and model_provider else get_default_model_config_fn()


def reset_runtime_outputs(
    *,
    session_paths: Any,
    reset_output_artifacts_for_fresh_run_fn: Callable[..., None],
) -> None:
    reset_output_artifacts_for_fresh_run_fn(
        checkpoint_path=session_paths.checkpoint_path,
        daily_events_path=session_paths.daily_events_path,
        timing_log_path=session_paths.timing_log_path,
        selection_artifact_root=session_paths.selection_artifact_root,
    )


def resolve_runtime_session_dependencies(
    *,
    output_dir: str | Path,
    frozen_plan_source: str | Path | None,
    pipeline: "DailyPipeline | None",
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    resolve_session_paths_fn: Callable[..., Any],
    reset_runtime_outputs_fn: Callable[[Any], None],
    resolve_runtime_pipeline_fn: Callable[..., "DailyPipeline"],
) -> tuple[Any, "DailyPipeline"]:
    session_paths = resolve_session_paths_fn(output_dir=output_dir, frozen_plan_source=frozen_plan_source)
    reset_runtime_outputs_fn(session_paths)
    resolved_pipeline = resolve_runtime_pipeline_fn(
        pipeline=pipeline,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        frozen_plan_source_path=session_paths.frozen_plan_source_path,
    )
    return session_paths, resolved_pipeline


def build_session_runtime_context(
    *,
    resolved_model_name: str,
    resolved_model_provider: str,
    session_paths: Any,
    pipeline: "DailyPipeline",
    recorder: "JsonlPaperTradingRecorder",
    engine: "BacktestEngine",
    snapshot_cache_stats_fn: Callable[[], dict],
    session_runtime_context_cls: type["SessionRuntimeContext"],
) -> "SessionRuntimeContext":
    return session_runtime_context_cls(
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        session_paths=session_paths,
        pipeline=pipeline,
        cache_stats_before_run=snapshot_cache_stats_fn(),
        recorder=recorder,
        engine=engine,
    )


def build_runtime_recorder_and_engine(
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
    pipeline: "DailyPipeline",
    session_paths: Any,
    build_runtime_recorder_fn: Callable[[Any], "JsonlPaperTradingRecorder"],
    build_paper_trading_engine_fn: Callable[..., "BacktestEngine"],
) -> tuple["JsonlPaperTradingRecorder", "BacktestEngine"]:
    recorder = build_runtime_recorder_fn(session_paths)
    engine = build_paper_trading_engine_fn(
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
    )
    return recorder, engine


def build_runtime_recorder(*, session_paths: Any, recorder_cls: type["JsonlPaperTradingRecorder"]) -> "JsonlPaperTradingRecorder":
    return recorder_cls(session_paths.daily_events_path)


def build_paper_trading_engine(
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
    pipeline: "DailyPipeline",
    session_paths: Any,
    recorder: "JsonlPaperTradingRecorder",
    build_selection_artifact_writer_fn: Callable[[Any], Any],
    backtest_engine_cls,
) -> "BacktestEngine":
    selection_artifact_writer = build_selection_artifact_writer_fn(session_paths)
    return backtest_engine_cls(
        agent=agent,
        tickers=tickers or [],
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        model_name=resolved_model_name,
        model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=initial_margin_requirement,
        backtest_mode="pipeline",
        pipeline=pipeline,
        checkpoint_path=str(session_paths.checkpoint_path),
        pipeline_event_recorder=recorder.record,
        selection_artifact_writer=selection_artifact_writer,
    )
