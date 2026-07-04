from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    return dict(json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8")) or {})


def _extract_selected_hit_rate(weekly_payload: dict[str, Any]) -> float:
    selected_surface_summary = dict(weekly_payload.get("selected_surface_summary") or {})
    surface_metrics = dict(selected_surface_summary.get("surface_metrics") or {})
    if "hit_rate_15pct" in surface_metrics:
        return round(float(surface_metrics.get("hit_rate_15pct") or 0.0), 4)
    weekly_surface_summaries = dict(weekly_payload.get("weekly_surface_summaries") or {})
    selected_summary = dict(weekly_surface_summaries.get("selected") or {})
    return round(float(selected_summary.get("max_future_high_return_2_5d_hit_rate_at_15pct") or 0.0), 4)


def _extract_shadow_scenario(weekly_payload: dict[str, Any]) -> dict[str, Any]:
    raw_scenarios = weekly_payload.get("selected_shadow_scenarios") or {}
    if isinstance(raw_scenarios, dict):
        return dict(raw_scenarios.get("layer_c_watchlist_only") or {})
    for scenario in list(raw_scenarios or []):
        scenario_dict = dict(scenario or {})
        excluded_candidate_sources = set(str(value) for value in list(scenario_dict.get("excluded_candidate_sources") or []))
        if "layer_c_watchlist" in excluded_candidate_sources:
            return scenario_dict
    return {}


def _extract_shadow_hit_rate(weekly_payload: dict[str, Any]) -> float:
    shadow_scenario = _extract_shadow_scenario(weekly_payload)
    surface_metrics = dict(shadow_scenario.get("surface_metrics") or {})
    if "hit_rate_15pct" in surface_metrics:
        return round(float(surface_metrics.get("hit_rate_15pct") or 0.0), 4)
    surface_summary = dict(shadow_scenario.get("surface_summary") or {})
    return round(float(surface_summary.get("max_future_high_return_2_5d_hit_rate_at_15pct") or 0.0), 4)


def _build_recommendation_summary(*, recommendation_status: str, execution_eligible_delta: int, buy_order_delta: int, selected_hit_rate: float, shadow_hit_rate: float) -> str:
    execution_eligible_reduction = abs(int(execution_eligible_delta))
    buy_order_reduction = abs(int(buy_order_delta))
    if recommendation_status == "governed_shadow_ready":
        return f"先收 formal buy：shadow 把 execution_eligible 收缩 {execution_eligible_reduction} 个、buy_order 收缩 {buy_order_reduction} 个，" f"同时 5D/+15% 命中率从 {selected_hit_rate:.4f} 提升到 {shadow_hit_rate:.4f}。"
    return f"继续扩窗验证：当前 5D/+15% 命中率仅从 {selected_hit_rate:.4f} 变化到 {shadow_hit_rate:.4f}，" f"execution_eligible delta={execution_eligible_delta}、buy_order delta={buy_order_delta} 还不足以支持 rollout。"


def analyze_btst_layer_c_rollout_validation(
    *,
    weekly_validation_json: str | Path,
    shadow_replay_json: str | Path,
    output_json_path: str | Path | None = None,
    output_markdown_path: str | Path | None = None,
) -> dict[str, Any]:
    weekly_payload = _load_json(weekly_validation_json)
    replay_payload = _load_json(shadow_replay_json)
    baseline_counts = dict(dict(replay_payload.get("baseline") or {}).get("aggregate_counts") or {})
    shadow_counts = dict(dict(replay_payload.get("shadow") or {}).get("aggregate_counts") or {})

    selected_hit_rate = _extract_selected_hit_rate(weekly_payload)
    shadow_hit_rate = _extract_shadow_hit_rate(weekly_payload)
    execution_eligible_delta = int(shadow_counts.get("execution_eligible_count", 0)) - int(baseline_counts.get("execution_eligible_count", 0))
    buy_order_delta = int(shadow_counts.get("buy_order_count", 0)) - int(baseline_counts.get("buy_order_count", 0))
    selected_count_delta = int(shadow_counts.get("selected_count", 0)) - int(baseline_counts.get("selected_count", 0))

    recommendation_status = "governed_shadow_ready" if shadow_hit_rate > selected_hit_rate and execution_eligible_delta < 0 and buy_order_delta < 0 else "hold_for_more_validation"
    report = {
        "payoff_summary": {
            "selected_hit_rate_15pct": selected_hit_rate,
            "shadow_hit_rate_15pct": shadow_hit_rate,
        },
        "replay_summary": {
            "selected_count_delta": selected_count_delta,
            "execution_eligible_delta": execution_eligible_delta,
            "buy_order_delta": buy_order_delta,
            "execution_eligibility_lost_by_date": dict(dict(replay_payload.get("delta") or {}).get("execution_eligibility_lost_by_date") or {}),
            "buy_orders_removed_by_date": dict(dict(replay_payload.get("delta") or {}).get("buy_orders_removed_by_date") or {}),
        },
        "recommendation": {
            "status": recommendation_status,
            "primary_lane": "layer_c_formal_precision_tightening",
            "summary": _build_recommendation_summary(
                recommendation_status=recommendation_status,
                execution_eligible_delta=execution_eligible_delta,
                buy_order_delta=buy_order_delta,
                selected_hit_rate=selected_hit_rate,
                shadow_hit_rate=shadow_hit_rate,
            ),
        },
    }
    if output_json_path is not None:
        json_path = Path(output_json_path).expanduser().resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_markdown_path is not None:
        markdown_path = Path(output_markdown_path).expanduser().resolve()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_rollout_validation_markdown(report) + "\n", encoding="utf-8")
    return report


def render_rollout_validation_markdown(report: dict[str, Any]) -> str:
    recommendation = dict(report.get("recommendation") or {})
    payoff_summary = dict(report.get("payoff_summary") or {})
    replay_summary = dict(report.get("replay_summary") or {})
    lines = [
        "# BTST Layer-C Rollout Validation",
        "",
        "## Recommendation",
        f"- status: {recommendation.get('status')}",
        f"- primary_lane: {recommendation.get('primary_lane')}",
        f"- summary: {recommendation.get('summary')}",
        "",
        "## Payoff Summary",
        f"- selected_hit_rate_15pct: {payoff_summary.get('selected_hit_rate_15pct')}",
        f"- shadow_hit_rate_15pct: {payoff_summary.get('shadow_hit_rate_15pct')}",
        "",
        "## Replay Summary",
        f"- execution_eligible_delta: {replay_summary.get('execution_eligible_delta')}",
        f"- buy_order_delta: {replay_summary.get('buy_order_delta')}",
        "",
    ]
    return "\n".join(lines).rstrip()
