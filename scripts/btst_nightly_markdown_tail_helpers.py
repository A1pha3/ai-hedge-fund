from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


RelativeLink = Callable[[str | Path | None, Path], str | None]


def append_priority_board_snapshot_markdown(lines: list[str], snapshot: dict[str, Any]) -> None:
    lines.append("## Priority Board Snapshot")
    lines.append(f"- summary: {snapshot.get('summary')}")
    lines.append(f"- brief_recommendation: {snapshot.get('brief_recommendation')}")
    for index, row in enumerate(list(snapshot.get("priority_rows") or []), start=1):
        lines.append(f"- {index}. {row.get('ticker')}: lane={row.get('lane')} actionability={row.get('actionability')} execution_quality_label={row.get('execution_quality_label')}")
        lines.append(f"  why_now: {row.get('why_now')}")
        lines.append(f"  suggested_action: {row.get('suggested_action')}")
        lines.append(f"  historical_summary: {row.get('historical_summary')}")
    for guardrail in list(snapshot.get("global_guardrails") or []):
        lines.append(f"- guardrail: {guardrail}")
    lines.append("")


def append_catalyst_theme_frontier_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    lines.append("## Catalyst Theme Frontier")
    if not summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {summary.get('status')}")
        lines.append(f"- shadow_candidate_count: {summary.get('shadow_candidate_count')}")
        lines.append(f"- baseline_selected_count: {summary.get('baseline_selected_count')}")
        lines.append(f"- recommended_variant_name: {summary.get('recommended_variant_name')}")
        lines.append(f"- recommended_promoted_shadow_count: {summary.get('recommended_promoted_shadow_count')}")
        lines.append(f"- recommended_relaxation_cost: {summary.get('recommended_relaxation_cost')}")
        lines.append(f"- recommended_thresholds: {summary.get('recommended_thresholds')}")
        promoted_tickers = list(summary.get("recommended_promoted_tickers") or [])
        lines.append(f"- recommended_promoted_tickers: {', '.join(promoted_tickers) if promoted_tickers else 'none'}")
        lines.append(f"- recommendation: {summary.get('recommendation')}")
    lines.append("")


def append_score_fail_frontier_queue_markdown(lines: list[str], summary: dict[str, Any]) -> None:
    lines.append("## Score-Fail Frontier Queue")
    if not summary:
        lines.append("- unavailable")
    else:
        lines.append(f"- status: {summary.get('status')}")
        lines.append(f"- rejected_short_trade_boundary_count: {summary.get('rejected_short_trade_boundary_count')}")
        lines.append(f"- rescueable_case_count: {summary.get('rescueable_case_count')}")
        lines.append(f"- threshold_only_rescue_count: {summary.get('threshold_only_rescue_count')}")
        lines.append(f"- recurring_case_count: {summary.get('recurring_case_count')}")
        lines.append(f"- transition_candidate_count: {summary.get('transition_candidate_count')}")
        lines.append(f"- recurring_shadow_refresh_status: {summary.get('recurring_shadow_refresh_status')}")
        priority_queue_tickers = list(summary.get("priority_queue_tickers") or [])
        lines.append(f"- priority_queue_tickers: {', '.join(priority_queue_tickers) if priority_queue_tickers else 'none'}")
        top_rescue_tickers = list(summary.get("top_rescue_tickers") or [])
        lines.append(f"- top_rescue_tickers: {', '.join(top_rescue_tickers) if top_rescue_tickers else 'none'}")
        for row in list(summary.get("priority_queue") or []):
            lines.append(f"- recurring_priority: {row.get('ticker')} occurrence_count={row.get('occurrence_count')} minimal_adjustment_cost={row.get('minimal_adjustment_cost')} gap_to_near_miss_mean={row.get('gap_to_near_miss_mean')}")
        for row in list(summary.get("top_rescue_rows") or []):
            lines.append(f"- top_rescue_row: {row.get('trade_date')} {row.get('ticker')} baseline_score={row.get('baseline_score_target')} replayed_score={row.get('replayed_score_target')} adjustment_cost={row.get('adjustment_cost')}")
        lines.append(f"- recommendation: {summary.get('recommendation')}")
    lines.append("")


def append_nightly_llm_health_markdown(lines: list[str], llm_error_digest: dict[str, Any]) -> None:
    lines.append("## LLM Health")
    lines.append(f"- status: {llm_error_digest.get('status')}")
    lines.append(f"- error_count: {llm_error_digest.get('error_count')}")
    lines.append(f"- rate_limit_error_count: {llm_error_digest.get('rate_limit_error_count')}")
    lines.append(f"- fallback_attempt_count: {llm_error_digest.get('fallback_attempt_count')}")
    lines.append(f"- affected_provider_count: {llm_error_digest.get('affected_provider_count')}")
    lines.append(f"- fallback_gap_detected: {llm_error_digest.get('fallback_gap_detected')}")
    top_error_types = list(llm_error_digest.get("top_error_types") or [])
    if top_error_types:
        for row in top_error_types:
            lines.append(f"- top_error_type: {row.get('error_type')} count={row.get('count')}")
    else:
        lines.append("- top_error_type: none")
    affected_providers = list(llm_error_digest.get("affected_providers") or [])
    if affected_providers:
        for row in affected_providers:
            lines.append(f"- provider_health: {row.get('provider')} errors={row.get('errors')} attempts={row.get('attempts')} error_rate={row.get('error_rate')} fallback_attempts={row.get('fallback_attempts')}")
    else:
        lines.append("- provider_health: none")
    sample_errors = list(llm_error_digest.get("sample_errors") or [])
    if sample_errors:
        for row in sample_errors:
            lines.append(f"- sample_error: {row.get('provider')} {row.get('error_type')} stage={row.get('pipeline_stage')} tier={row.get('model_tier')} message={row.get('message')}")
    else:
        lines.append("- sample_error: none")
    lines.append("")


def append_replay_cohort_snapshot_markdown(lines: list[str], replay_cohort_snapshot: dict[str, Any]) -> None:
    lines.append("## Replay Cohort Snapshot")
    lines.append(f"- short_trade_summary: {replay_cohort_snapshot.get('short_trade_summary')}")
    lines.append(f"- frozen_summary: {replay_cohort_snapshot.get('frozen_summary')}")
    latest_short_trade_row = dict(replay_cohort_snapshot.get("latest_short_trade_row") or {})
    if latest_short_trade_row:
        lines.append(f"- latest_short_trade_report: {latest_short_trade_row.get('report_dir_name')}")
        lines.append(f"  total_return_pct: {latest_short_trade_row.get('total_return_pct')}")
        lines.append(f"  near_miss_count: {latest_short_trade_row.get('near_miss_count')}")
        lines.append(f"  opportunity_pool_count: {latest_short_trade_row.get('opportunity_pool_count')}")
    for row in list(replay_cohort_snapshot.get("top_return_rows") or []):
        lines.append(f"- top_return_row: {row.get('report_dir_name')} | selection_target={row.get('selection_target')} | total_return_pct={row.get('total_return_pct')} | near_miss_count={row.get('near_miss_count')}")
    lines.append("")


def append_nightly_reading_order_markdown(lines: list[str], payload: dict[str, Any]) -> None:
    lines.append("## Reading Order")
    for item in list(payload.get("recommended_reading_order") or []):
        lines.append(f"- {item.get('entry_id')}: {item.get('question')} | {item.get('report_path')}")
    lines.append("")


def append_nightly_fast_links_markdown(
    lines: list[str],
    source_paths: dict[str, Any],
    output_parent: Path,
    *,
    relative_link: RelativeLink,
) -> None:
    lines.append("## Fast Links")
    for label, source_path in source_paths.items():
        relative_target = relative_link(source_path, output_parent)
        if relative_target:
            lines.append(f"- {label}: [{Path(source_path).name}]({relative_target})")
        else:
            lines.append(f"- {label}: {source_path}")
    lines.append("")
