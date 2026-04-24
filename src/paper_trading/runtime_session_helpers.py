from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PaperTradingSessionPaths:
    output_dir_path: Path
    frozen_plan_source_path: Path | None
    daily_events_path: Path
    timing_log_path: Path
    summary_path: Path
    checkpoint_path: Path
    selection_artifact_root: Path


def resolve_session_paths(*, output_dir: str | Path, frozen_plan_source: str | Path | None) -> PaperTradingSessionPaths:
    output_dir_path = Path(output_dir).resolve()
    output_dir_path.mkdir(parents=True, exist_ok=True)
    frozen_plan_source_path = Path(frozen_plan_source).resolve() if frozen_plan_source is not None else None
    return PaperTradingSessionPaths(
        output_dir_path=output_dir_path,
        frozen_plan_source_path=frozen_plan_source_path,
        daily_events_path=output_dir_path / "daily_events.jsonl",
        timing_log_path=output_dir_path / "pipeline_timings.jsonl",
        summary_path=output_dir_path / "session_summary.json",
        checkpoint_path=output_dir_path / "session.checkpoint.json",
        selection_artifact_root=output_dir_path / "selection_artifacts",
    )


def resolve_pipeline(
    *,
    pipeline,
    frozen_plan_source_path: Path | None,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    selection_target: str,
    pipeline_cls,
    load_frozen_post_market_plans,
):
    pipeline_kwargs = {
        "base_model_name": resolved_model_name,
        "base_model_provider": resolved_model_provider,
        "selected_analysts": selected_analysts,
        "fast_selected_analysts": fast_selected_analysts,
        "short_trade_target_profile_name": short_trade_target_profile_name,
        "short_trade_target_profile_overrides": short_trade_target_profile_overrides or {},
        "target_mode": selection_target,
    }
    if frozen_plan_source_path is not None:
        if pipeline is not None:
            raise ValueError("pipeline and frozen_plan_source cannot be used together")
        return pipeline_cls(
            **pipeline_kwargs,
            frozen_post_market_plans=load_frozen_post_market_plans(frozen_plan_source_path),
            frozen_plan_source=str(frozen_plan_source_path),
        )
    if pipeline is None:
        return pipeline_cls(**pipeline_kwargs)
    if isinstance(pipeline, pipeline_cls):
        if selected_analysts is not None:
            pipeline.selected_analysts = list(selected_analysts)
        if fast_selected_analysts is not None:
            pipeline.fast_selected_analysts = list(fast_selected_analysts)
        pipeline.short_trade_target_profile_name = str(short_trade_target_profile_name or "default")
        pipeline.short_trade_target_profile_overrides = dict(short_trade_target_profile_overrides or {})
    return pipeline


def run_optional_cache_benchmark(
    *,
    cache_benchmark: bool,
    cache_benchmark_ticker: str | None,
    tickers: list[str] | None,
    output_dir_path: Path,
    end_date: str,
    cache_benchmark_clear_first: bool,
    run_cache_reuse_benchmark,
    repo_root: Path,
    python_executable: str,
) -> tuple[dict[str, Any] | None, dict[str, str], dict[str, Any]]:
    cache_benchmark_summary = None
    cache_benchmark_artifacts: dict[str, str] = {}
    cache_benchmark_status: dict[str, Any] = {
        "requested": bool(cache_benchmark),
        "executed": False,
        "write_status": "not_requested" if not cache_benchmark else "skipped",
        "reason": None,
    }
    benchmark_ticker = cache_benchmark_ticker or (tickers[0] if tickers else None)
    if cache_benchmark and benchmark_ticker:
        cache_benchmark_json_path = output_dir_path / "data_cache_benchmark.json"
        cache_benchmark_markdown_path = output_dir_path / "data_cache_benchmark.md"
        cache_benchmark_append_path = output_dir_path / "window_review.md"
        try:
            cache_benchmark_summary = run_cache_reuse_benchmark(
                repo_root=repo_root,
                python_executable=python_executable,
                trade_date=end_date.replace("-", ""),
                ticker=benchmark_ticker,
                clear_first=cache_benchmark_clear_first,
                output_path=cache_benchmark_json_path,
                markdown_output_path=cache_benchmark_markdown_path,
                append_markdown_to=cache_benchmark_append_path,
            )
            cache_benchmark_artifacts = {
                "data_cache_benchmark_json": str(cache_benchmark_json_path),
                "data_cache_benchmark_markdown": str(cache_benchmark_markdown_path),
                "data_cache_benchmark_appended_report": str(cache_benchmark_append_path),
            }
            cache_benchmark_status = {
                "requested": True,
                "executed": True,
                "write_status": "success",
                "reason": None,
            }
        except Exception as error:
            cache_benchmark_summary = {
                "requested": True,
                "executed": False,
                "write_status": "failed",
                "reason": str(error),
                "ticker": benchmark_ticker,
                "trade_date": end_date.replace("-", ""),
            }
            cache_benchmark_status = {
                "requested": True,
                "executed": False,
                "write_status": "failed",
                "reason": str(error),
            }
    elif cache_benchmark:
        cache_benchmark_summary = {
            "requested": True,
            "executed": False,
            "write_status": "skipped",
            "reason": "no benchmark ticker available",
        }
        cache_benchmark_status = {
            "requested": True,
            "executed": False,
            "write_status": "skipped",
            "reason": "no benchmark ticker available",
        }
    return cache_benchmark_summary, cache_benchmark_artifacts, cache_benchmark_status


def build_session_summary(
    *,
    start_date: str,
    end_date: str,
    tickers: list[str] | None,
    initial_capital: float,
    resolved_model_name: str,
    resolved_model_provider: str,
    selected_analysts: list[str] | None,
    fast_selected_analysts: list[str] | None,
    short_trade_target_profile_name: str,
    short_trade_target_profile_overrides: dict[str, object] | None,
    frozen_plan_source_path: Path | None,
    selection_target: str,
    metrics: dict[str, Any],
    portfolio_values: list[dict[str, Any]],
    final_portfolio_snapshot: dict[str, Any],
    llm_route_provenance: dict[str, Any],
    execution_plan_provenance: dict[str, Any],
    dual_target_summary: dict[str, Any],
    llm_observability_summary: dict[str, Any],
    llm_error_digest: dict[str, Any],
    data_cache_summary: dict[str, Any],
    cache_benchmark_summary: dict[str, Any] | None,
    cache_benchmark_status: dict[str, Any],
    research_feedback_summary: dict[str, Any],
    recorder_day_count: int,
    recorder_executed_trade_days: int,
    recorder_total_executed_orders: int,
    daily_events_path: Path,
    timing_log_path: Path,
    summary_path: Path,
    selection_artifact_root: Path,
    feedback_summary_path: Path,
    cache_benchmark_artifacts: dict[str, str],
    llm_metrics_artifacts: dict[str, str],
) -> dict[str, Any]:
    summary = {
        "mode": "paper_trading",
        "start_date": start_date,
        "end_date": end_date,
        "tickers": list(tickers or []),
        "initial_capital": float(initial_capital),
        "model_name": resolved_model_name,
        "model_provider": resolved_model_provider,
        "selected_analysts": selected_analysts,
        "fast_selected_analysts": fast_selected_analysts,
        "short_trade_target_profile_name": short_trade_target_profile_name,
        "short_trade_target_profile_overrides": short_trade_target_profile_overrides or {},
        "plan_generation": {
            "mode": "frozen_current_plan_replay" if frozen_plan_source_path is not None else "live_pipeline",
            "frozen_plan_source": str(frozen_plan_source_path) if frozen_plan_source_path is not None else None,
            "selection_target": selection_target,
        },
        "btst_0422_flags": {
            "p5_execution_contract_mode": str(os.getenv("BTST_0422_P5_EXECUTION_CONTRACT_MODE", "off") or "off").strip().lower() or "off",
            "p6_risk_budget_mode": str(os.getenv("BTST_0422_P6_RISK_BUDGET_MODE", "off") or "off").strip().lower() or "off",
        },
        "performance_metrics": dict(metrics),
        "portfolio_values": portfolio_values,
        "final_portfolio_snapshot": final_portfolio_snapshot,
        "llm_route_provenance": llm_route_provenance,
        "execution_plan_provenance": execution_plan_provenance,
        "dual_target_summary": dual_target_summary,
        "llm_observability_summary": llm_observability_summary,
        "llm_error_digest": llm_error_digest,
        "data_cache": data_cache_summary,
        "data_cache_benchmark": cache_benchmark_summary,
        "data_cache_benchmark_status": cache_benchmark_status,
        "research_feedback_summary": research_feedback_summary,
        "daily_event_stats": {
            "day_count": recorder_day_count,
            "executed_trade_days": recorder_executed_trade_days,
            "total_executed_orders": recorder_total_executed_orders,
        },
        "artifacts": {
            "daily_events": str(daily_events_path),
            "timing_log": str(timing_log_path),
            "summary": str(summary_path),
            "selection_artifact_root": str(selection_artifact_root),
            "research_feedback_summary": str(feedback_summary_path),
            "data_cache_path": data_cache_summary.get("disk_path"),
            **cache_benchmark_artifacts,
            **llm_metrics_artifacts,
        },
    }
    btst_regime_gate_summary = dict((dual_target_summary or {}).get("btst_regime_gate_summary", {}) or {})
    if btst_regime_gate_summary:
        summary["btst_regime_gate_summary"] = btst_regime_gate_summary
    btst_risk_budget_p6_summary = dict((dual_target_summary or {}).get("btst_risk_budget_p6_summary", {}) or {})
    if btst_risk_budget_p6_summary:
        summary["btst_risk_budget_p6_summary"] = btst_risk_budget_p6_summary
    return summary
