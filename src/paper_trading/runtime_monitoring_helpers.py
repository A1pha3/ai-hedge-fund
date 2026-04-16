from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Callable

if TYPE_CHECKING:
    from src.execution.daily_pipeline import DailyPipeline
    from src.paper_trading.runtime import SessionRuntimeContext


def resolve_runtime_pipeline(
    *,
    pipeline: "DailyPipeline | None",
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    frozen_plan_source_path: Path | None,
    resolve_pipeline_fn: Callable[..., "DailyPipeline"],
    pipeline_cls: type,
    load_frozen_post_market_plans_fn: Callable[..., object],
) -> "DailyPipeline":
    return resolve_pipeline_fn(
        pipeline=pipeline,
        frozen_plan_source_path=frozen_plan_source_path,
        resolved_model_name=resolved_model_name,
        resolved_model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        pipeline_cls=pipeline_cls,
        load_frozen_post_market_plans=load_frozen_post_market_plans_fn,
    )


def build_runtime_monitoring_summary(
    context: "SessionRuntimeContext",
    *,
    build_llm_route_provenance_fn: Callable[[], tuple[dict, dict]],
    build_llm_observability_summary_fn: Callable[[Path], dict],
    build_llm_error_digest_fn: Callable[[dict, dict], dict],
    build_execution_plan_provenance_summary_fn: Callable[["DailyPipeline | None"], dict],
    build_dual_target_session_summary_fn: Callable[[Path], dict],
) -> dict:
    llm_route_provenance, llm_metrics_artifacts = build_llm_route_provenance_fn()
    llm_observability_summary = build_llm_observability_summary_fn(Path(llm_metrics_artifacts["llm_metrics_jsonl"]))
    return {
        "llm_route_provenance": llm_route_provenance,
        "llm_metrics_artifacts": llm_metrics_artifacts,
        "llm_observability_summary": llm_observability_summary,
        "llm_error_digest": build_llm_error_digest_fn(llm_route_provenance, llm_observability_summary),
        "execution_plan_provenance": build_execution_plan_provenance_summary_fn(getattr(context.engine, "_pipeline", None)),
        "dual_target_summary": build_dual_target_session_summary_fn(context.session_paths.daily_events_path),
    }


def build_runtime_data_cache_summary(
    context: "SessionRuntimeContext",
    *,
    get_cache_runtime_info_fn: Callable[[], dict],
    diff_cache_stats_fn: Callable[[dict, dict], dict],
) -> dict:
    data_cache_summary = get_cache_runtime_info_fn()
    data_cache_summary["session_stats"] = diff_cache_stats_fn(context.cache_stats_before_run, data_cache_summary.get("stats", {}))
    return data_cache_summary


def run_runtime_cache_benchmark(
    *,
    context: "SessionRuntimeContext",
    cache_benchmark: bool,
    cache_benchmark_ticker: str | None,
    tickers: list[str] | None,
    end_date: str,
    cache_benchmark_clear_first: bool,
    run_optional_cache_benchmark_fn: Callable[..., tuple[dict, dict, str]],
    run_cache_reuse_benchmark_fn: Callable[..., object],
    repo_root: Path,
    python_executable: str,
) -> tuple[dict, dict, str]:
    return run_optional_cache_benchmark_fn(
        cache_benchmark=cache_benchmark,
        cache_benchmark_ticker=cache_benchmark_ticker,
        tickers=tickers,
        output_dir_path=context.session_paths.output_dir_path,
        end_date=end_date,
        cache_benchmark_clear_first=cache_benchmark_clear_first,
        run_cache_reuse_benchmark=run_cache_reuse_benchmark_fn,
        repo_root=repo_root,
        python_executable=python_executable,
    )
