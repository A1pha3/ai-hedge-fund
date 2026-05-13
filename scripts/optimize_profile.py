"""Optimize short-trade target profile parameters via grid search.

Uses replay-based multi-window analysis to evaluate parameter combinations.
Supports checkpointing for long-running searches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

from scripts.btst_optimized_profile_manifest_helpers import publish_btst_optimized_profile_manifest
from scripts.analyze_btst_weekly_validation import analyze_btst_weekly_validation
from src.backtesting.evaluation_bundle import BTST_EXECUTION_GUARDRAILS, BTST_QUALITY_FLOORS
from src.backtesting.param_search import (
    format_search_report,
    GuardrailSpec,
    ParamSpace,
    run_param_search,
    save_search_payload,
    save_search_report,
    SearchObjective,
    SearchReport,
)
from src.targets import get_short_trade_target_profile
from src.utils.logging import get_logger

logger = get_logger(__name__)

REPORTS_DIR = Path("data/reports")
PARTIAL_HORIZON_WEIGHT_PENALTY = 0.85
PARTIAL_T3_HORIZON_WEIGHT_PENALTY = 0.92
DEFAULT_BTST_REPLAY_GUARDRAILS: dict[str, GuardrailSpec] = {
    "next_close_positive_rate": BTST_QUALITY_FLOORS["next_close_positive_rate"],
    "next_high_hit_rate": BTST_QUALITY_FLOORS["next_high_hit_rate"],
    "downside_p10": BTST_QUALITY_FLOORS["downside_p10"],
    "window_coverage": BTST_QUALITY_FLOORS["window_coverage"],
    "projected_theme_exposure": {"max": 0.35},
    "incremental_theme_exposure": {"max": 0.12},
    "liquidity_capacity_raw_100": dict(BTST_EXECUTION_GUARDRAILS["liquidity_capacity_raw_100"]),
    "crowding_risk_raw_100": dict(BTST_EXECUTION_GUARDRAILS["crowding_risk_raw_100"]),
    "gap_risk_raw_100": dict(BTST_EXECUTION_GUARDRAILS["gap_risk_raw_100"]),
}
DEFAULT_BTST_RUNNER_REPLAY_GUARDRAILS: dict[str, GuardrailSpec] = {
    "max_future_high_return_2_5d_hit_rate_at_20pct": {"min": 0.10},
    "next_close_positive_rate": BTST_QUALITY_FLOORS["next_close_positive_rate"],
    "downside_p10": BTST_QUALITY_FLOORS["downside_p10"],
    "window_coverage": BTST_QUALITY_FLOORS["window_coverage"],
    "gap_risk_raw_100": dict(BTST_EXECUTION_GUARDRAILS["gap_risk_raw_100"]),
    "runner_escape_rate": {"min": 0.03, "max": 0.60},
    "avg_composite_score_escaped": {"min": BTST_QUALITY_FLOORS["avg_composite_score_escaped"]},
    "t_plus_2_close_payoff_ratio": {"min": BTST_QUALITY_FLOORS["t_plus_2_close_payoff_ratio"]},
    "t_plus_3_close_payoff_ratio": {"min": BTST_QUALITY_FLOORS["t_plus_3_close_payoff_ratio"]},
}
MOMENTUM_OPTIMIZED_STAGE_PRESET_GRIDS: dict[str, dict[str, list[Any]]] = {
    "coarse": {
        "select_threshold": [0.46, 0.50, 0.54],
        "near_miss_threshold": [0.30, 0.34, 0.38],
        "breakout_freshness_weight": [0.12, 0.16],
        "trend_acceleration_weight": [0.18, 0.22],
        "volume_expansion_quality_weight": [0.16, 0.20],
        "close_strength_weight": [0.12, 0.16],
        "catalyst_freshness_weight": [0.10, 0.14],
        "momentum_strength_weight": [0.00, 0.06],
        "short_term_reversal_weight": [0.00, 0.04],
    },
    "focused": {
        "select_threshold": [0.46, 0.50, 0.54],
        "near_miss_threshold": [0.30, 0.34, 0.38],
        "breakout_freshness_weight": [0.12, 0.16],
        "trend_acceleration_weight": [0.18, 0.22],
        "volume_expansion_quality_weight": [0.16, 0.20],
        "close_strength_weight": [0.12, 0.16],
        "catalyst_freshness_weight": [0.10, 0.14],
        "momentum_strength_weight": [0.00, 0.06],
        "short_term_reversal_weight": [0.00, 0.04],
    },
}
COMPARISON_METRICS: tuple[str, ...] = (
    "next_close_positive_rate",
    "next_high_hit_rate",
    "next_close_expectancy",
    "downside_p10",
    "window_coverage",
    "liquidity_capacity_raw_100",
    "crowding_risk_raw_100",
    "gap_risk_raw_100",
    "projected_theme_exposure",
    "incremental_theme_exposure",
    "max_future_high_return_2_5d_hit_rate_at_20pct",
    "time_to_hit_20pct_median",
    "runner_capture_count",
    "runner_escape_rate",
    "avg_composite_score_escaped",
    "t_plus_2_close_positive_rate",
    "t_plus_2_close_payoff_ratio",
    "t_plus_3_close_positive_rate",
    "t_plus_3_close_expectancy",
    "t_plus_3_close_payoff_ratio",
)
COMPARISON_METRIC_LABELS: dict[str, str] = {
    "next_close_positive_rate": "Close+",
    "next_high_hit_rate": "High-hit",
    "next_close_expectancy": "Expectancy",
    "downside_p10": "Downside P10",
    "window_coverage": "Coverage",
    "liquidity_capacity_raw_100": "Liquidity",
    "crowding_risk_raw_100": "Crowding",
    "gap_risk_raw_100": "Gap Risk",
    "projected_theme_exposure": "Projected Exp",
    "incremental_theme_exposure": "Incremental Exp",
    "max_future_high_return_2_5d_hit_rate_at_20pct": "Runner 20% Hit",
    "time_to_hit_20pct_median": "Time-to-20% Med",
    "runner_capture_count": "Runner Count",
    "runner_escape_rate": "Runner Escape %",
    "avg_composite_score_escaped": "Avg Escaped Score",
    "t_plus_2_close_positive_rate": "T+2 Close+",
    "t_plus_2_close_payoff_ratio": "T+2 Payoff",
    "t_plus_3_close_positive_rate": "T+3 Close+",
    "t_plus_3_close_expectancy": "T+3 Expectancy",
    "t_plus_3_close_payoff_ratio": "T+3 Payoff",
}
LOWER_IS_BETTER_COMPARISON_METRICS = {
    "crowding_risk_raw_100",
    "gap_risk_raw_100",
    "projected_theme_exposure",
    "incremental_theme_exposure",
    "time_to_hit_20pct_median",
}
# Runner metrics are optional — surfaces computed without the runner analysis pipeline
# will not have these fields, and their absence should not block rollout.
OPTIONAL_COMPARISON_METRICS: frozenset[str] = frozenset({
    "max_future_high_return_2_5d_hit_rate_at_20pct",
    "time_to_hit_20pct_median",
    "runner_capture_count",
    "runner_escape_rate",
    "avg_composite_score_escaped",
    "t_plus_2_close_positive_rate",
    "t_plus_2_close_payoff_ratio",
    "t_plus_3_close_positive_rate",
    "t_plus_3_close_expectancy",
    "t_plus_3_close_payoff_ratio",
})
COMPARISON_METRIC_EPSILON: dict[str, float] = {
    "next_close_positive_rate": 0.0,
    "next_high_hit_rate": 0.0,
    "next_close_expectancy": 0.0,
    "downside_p10": 0.002,
    "window_coverage": 0.002,
    "projected_theme_exposure": 0.005,
    "incremental_theme_exposure": 0.005,
    "liquidity_capacity_raw_100": 1.0,
    "crowding_risk_raw_100": 1.0,
    "gap_risk_raw_100": 1.0,
    "max_future_high_return_2_5d_hit_rate_at_20pct": 0.01,
    "time_to_hit_20pct_median": 0.1,
    "runner_capture_count": 1.0,
    "runner_escape_rate": 0.01,
    "avg_composite_score_escaped": 0.01,
    "t_plus_2_close_positive_rate": 0.0,
    "t_plus_2_close_payoff_ratio": 0.01,
    "t_plus_3_close_positive_rate": 0.0,
    "t_plus_3_close_expectancy": 0.0,
    "t_plus_3_close_payoff_ratio": 0.01,
}


def resolve_replay_input_paths(
    *,
    input_paths: list[str] | None,
    reports_root: str | Path | None,
    weekly_start_date: str | None,
    weekly_end_date: str | None,
) -> list[Path]:
    if input_paths:
        return [Path(path).expanduser().resolve() for path in input_paths]
    if not reports_root or not weekly_start_date or not weekly_end_date:
        raise ValueError("Provide --input or --reports-root with --weekly-start-date and --weekly-end-date")

    analysis = analyze_btst_weekly_validation(
        reports_root,
        start_date=weekly_start_date,
        end_date=weekly_end_date,
    )
    missing_trade_dates = list(analysis.get("missing_trade_dates") or [])
    if missing_trade_dates:
        raise ValueError(f"missing_trade_dates={missing_trade_dates}")

    replay_input_paths: list[Path] = []
    for row in list(analysis.get("selected_reports") or []):
        replay_input_path = Path(str(row["report_dir"])) / "selection_artifacts" / str(row["trade_date"]) / "selection_target_replay_input.json"
        if replay_input_path.exists():
            replay_input_paths.append(replay_input_path.resolve())
    if not replay_input_paths:
        raise FileNotFoundError("No replay inputs found for the requested weekly window")
    return replay_input_paths


def _build_default_checkpoint_path(
    *,
    profile: str,
    objective: str,
    replay_input_paths: list[Path] | None = None,
    walk_forward_descriptor: str | None = None,
) -> str:
    descriptor_parts = [f"profile={profile}", f"objective={objective}"]
    if replay_input_paths:
        resolved_paths = sorted(str(path.expanduser().resolve()) for path in replay_input_paths)
        descriptor_parts.append("mode=replay")
        descriptor_parts.extend(resolved_paths)
    else:
        descriptor_parts.append("mode=walk_forward")
        descriptor_parts.append(walk_forward_descriptor or "")
    digest = hashlib.sha1("||".join(descriptor_parts).encode("utf-8")).hexdigest()[:12]
    return str(REPORTS_DIR / f"param_search_{profile}_{digest}_checkpoint.json")


def _parse_grid_params(raw: list[str]) -> dict[str, list[Any]]:
    def _parse_scalar(value: str) -> Any:
        stripped = value.strip()
        lowered = stripped.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if "." in stripped:
            try:
                return float(stripped)
            except ValueError:
                return stripped
        if stripped.isdigit():
            return int(stripped)
        return stripped

    grid: dict[str, list[Any]] = {}
    for item in raw:
        if "=" in item:
            key, values_str = item.split("=", 1)
            values = [_parse_scalar(v) for v in values_str.split(",")]
            grid[key.strip()] = values
        else:
            try:
                with open(item) as f:
                    grid = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                logger.error("Cannot parse grid param: %s (use key=val1,val2 or path/to.json)", item)
                sys.exit(1)
    return grid


def _normalize_guardrail_spec(spec: GuardrailSpec) -> dict[str, float]:
    if isinstance(spec, dict):
        normalized: dict[str, float] = {}
        if spec.get("min") is not None:
            normalized["min"] = float(spec["min"])
        if spec.get("max") is not None:
            normalized["max"] = float(spec["max"])
        if not normalized:
            raise ValueError("Guardrail spec dict must contain min and/or max")
        return normalized
    return {"min": float(spec)}


def _parse_guardrails(raw: list[str]) -> dict[str, GuardrailSpec]:
    guardrails: dict[str, GuardrailSpec] = {}
    for item in raw:
        operator = None
        if "<=" in item:
            key, raw_value = item.split("<=", 1)
            operator = "max"
        elif ">=" in item:
            key, raw_value = item.split(">=", 1)
            operator = "min"
        elif "=" in item:
            key, raw_value = item.split("=", 1)
            operator = "legacy_min"
        else:
            raise ValueError(f"Invalid guardrail {item!r}; expected metric=floor, metric>=floor, or metric<=cap")
        value = _safe_float(raw_value)
        if value is None:
            raise ValueError(f"Invalid guardrail floor for {key!r}: {raw_value!r}")
        normalized_key = key.strip()
        if operator == "legacy_min":
            guardrails[normalized_key] = float(value)
            continue
        existing = guardrails.get(normalized_key)
        merged = _normalize_guardrail_spec(existing) if existing is not None else {}
        merged[operator] = float(value)
        guardrails[normalized_key] = merged
    return guardrails


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_guardrail_spec(spec: GuardrailSpec) -> str:
    if isinstance(spec, dict):
        parts: list[str] = []
        if spec.get("min") is not None:
            parts.append(f"min={float(spec['min'])}")
        if spec.get("max") is not None:
            parts.append(f"max={float(spec['max'])}")
        return ", ".join(parts)
    return str(float(spec))


def resolve_guardrails(
    *,
    profile_name: str,
    objective: str,
    replay_mode: bool,
    raw_guardrails: list[str],
) -> dict[str, GuardrailSpec]:
    resolved: dict[str, GuardrailSpec] = {}
    if replay_mode and profile_name == "momentum_optimized" and objective == SearchObjective.BTST.value:
        resolved.update(DEFAULT_BTST_REPLAY_GUARDRAILS)
    if replay_mode and profile_name == "momentum_optimized" and objective == SearchObjective.BTST_RUNNER.value:
        resolved.update(DEFAULT_BTST_RUNNER_REPLAY_GUARDRAILS)
    resolved.update(_parse_guardrails(raw_guardrails))
    return resolved


def _resolve_distribution_stat(surface: dict[str, Any], distribution_key: str, stat_key: str) -> float | None:
    distribution = dict(surface.get(distribution_key) or {})
    return _safe_float(distribution.get(stat_key))


def _extract_committee_component_metric(row: dict[str, Any], metric_key: str) -> float | None:
    metrics_payload = dict(row.get("metrics_payload") or {})
    committee_payload = dict(metrics_payload.get("committee") or {})
    committee_components = dict(committee_payload.get("components") or {})
    component_value = _safe_float(committee_components.get(metric_key))
    if component_value is not None:
        return component_value
    return _safe_float(metrics_payload.get(metric_key))


def _resolve_scope_rows(rows: list[dict[str, Any]], *, primary_scope: str) -> list[dict[str, Any]]:
    allowed_decisions = {"selected"} if primary_scope == "selected" else {"selected", "near_miss"}
    return [dict(row or {}) for row in rows if str(row.get("decision") or "").strip() in allowed_decisions]


def _average_scope_metric(rows: list[dict[str, Any]], metric_key: str) -> float | None:
    numeric_values = [
        float(value)
        for value in (_extract_committee_component_metric(row, metric_key) for row in rows)
        if value is not None
    ]
    if not numeric_values:
        return None
    return sum(numeric_values) / len(numeric_values)


def _resolve_primary_surface(
    *,
    selected_surface: dict[str, Any],
    tradeable_surface: dict[str, Any],
    min_selected_next_day_count: int = 6,
    min_selected_closed_cycle_count: int = 3,
) -> tuple[dict[str, Any], str]:
    selected_next_day_count = int(selected_surface.get("next_day_available_count") or 0)
    selected_closed_cycle_count = int(selected_surface.get("closed_cycle_count") or 0)
    if selected_next_day_count >= min_selected_next_day_count and selected_closed_cycle_count >= min_selected_closed_cycle_count:
        return selected_surface, "selected"
    return tradeable_surface, "tradeable_fallback"


def _compute_source_coverage_pass_ratio(source_coverage_summaries: list[dict[str, Any]]) -> float:
    """Compute high-quality (exact_tick) source fraction across tracked source fields.

    Args:
        source_coverage_summaries: List of source_coverage_summary dicts from replay windows.

    Returns:
        Fraction of tracked source slots covered by exact_tick (0.0 if no data).
    """
    _TRACKED_FIELDS = [
        "flow_60_source_counts",
        "persist_120_source_counts",
        "close_support_30_source_counts",
        "committee_component_sources_counts",
    ]
    _STRONG_SOURCE = "exact_tick"
    strong_total = 0
    grand_total = 0
    for summary in source_coverage_summaries:
        for field in _TRACKED_FIELDS:
            field_counts = dict(summary.get(field) or {})
            for source, count in field_counts.items():
                grand_total += int(count)
                if source == _STRONG_SOURCE:
                    strong_total += int(count)
    if grand_total == 0:
        return 0.0
    return float(strong_total) / float(grand_total)


def _build_replay_evaluator(
    input_paths: list[Path],
    *,
    base_profile: str,
    next_high_hit_threshold: float = 0.02,
) -> Callable:
    from scripts.btst_profile_replay_utils import analyze_btst_profile_replay_window

    def evaluator(params: dict[str, Any]) -> dict[str, float | None]:
        from src.targets.profiles import build_short_trade_target_profile

        try:
            build_short_trade_target_profile(base_profile, overrides=params)
        except Exception as e:
            logger.warning("Invalid params %s: %s", params, e)
            return {
                "sharpe_ratio": None,
                "sortino_ratio": None,
                "max_drawdown": None,
                "next_close_positive_rate": None,
                "next_close_payoff_ratio": None,
                "next_close_expectancy": None,
                "next_high_hit_rate": None,
                "t_plus_2_close_positive_rate": None,
                "t_plus_2_close_payoff_ratio": None,
                "t_plus_3_close_positive_rate": None,
                "t_plus_3_close_expectancy": None,
                "t_plus_3_close_payoff_ratio": None,
                "downside_p10": None,
                "sample_weight": None,
                "window_coverage": 0.0,
                "window_count": 0,
                "source_coverage_pass_ratio": 0.0,
            }

        total_metrics: dict[str, list[float]] = {
            "sharpe": [],
            "sortino": [],
            "max_dd": [],
            "next_close_positive_rate": [],
            "next_close_payoff_ratio": [],
            "next_close_expectancy": [],
            "next_high_hit_rate": [],
            "t_plus_2_close_positive_rate": [],
            "t_plus_2_close_payoff_ratio": [],
            "t_plus_3_close_positive_rate": [],
            "t_plus_3_close_expectancy": [],
            "t_plus_3_close_payoff_ratio": [],
            "downside_p10": [],
            "sample_weight": [],
            "projected_theme_exposure": [],
            "incremental_theme_exposure": [],
            "liquidity_capacity_raw_100": [],
            "crowding_risk_raw_100": [],
            "gap_risk_raw_100": [],
            "max_future_high_return_2_5d_hit_rate_at_20pct": [],
            "runner_capture_count": [],
            "time_to_hit_20pct_median": [],
            "runner_escape_rate": [],
            "avg_composite_score_escaped": [],
        }

        # For metrics that should be sample-weighted, keep a parallel list of weights
        total_metric_weights: dict[str, list[float]] = {
            "next_close_positive_rate": [],
            "next_close_payoff_ratio": [],
            "next_close_expectancy": [],
            "next_high_hit_rate": [],
            "t_plus_2_close_positive_rate": [],
            "t_plus_2_close_payoff_ratio": [],
            "t_plus_3_close_positive_rate": [],
            "t_plus_3_close_expectancy": [],
            "t_plus_3_close_payoff_ratio": [],
            "downside_p10": [],
            "max_future_high_return_2_5d_hit_rate_at_20pct": [],
            "time_to_hit_20pct_median": [],
        }

        # Track selected surfaces for runner median distribution aggregation
        selected_surfaces: list[dict[str, Any]] = []

        window_count = 0
        source_coverage_summaries: list[dict[str, Any]] = []

        for input_path in input_paths:
            try:
                result = analyze_btst_profile_replay_window(
                    input_path,
                    profile_name=base_profile,
                    label=f"trial_{json.dumps(params, sort_keys=True, default=str)}",
                    next_high_hit_threshold=next_high_hit_threshold,
                    profile_overrides=params,
                )
                surfaces = dict(result.get("surface_summaries", {}) or {})
                selected_surface = dict(surfaces.get("selected") or {})
                tradeable_surface = dict(surfaces.get("tradeable") or {})
                primary_surface, primary_scope = _resolve_primary_surface(
                    selected_surface=selected_surface,
                    tradeable_surface=tradeable_surface,
                )

                next_close_positive_rate = _safe_float(primary_surface.get("next_close_positive_rate"))
                next_high_hit_rate = _safe_float(primary_surface.get("next_high_hit_rate_at_threshold"))
                t_plus_2_median = _resolve_distribution_stat(primary_surface, "t_plus_2_close_return_distribution", "median")
                t_plus_3_median = _resolve_distribution_stat(primary_surface, "t_plus_3_close_return_distribution", "median")
                max_dd_proxy = _resolve_distribution_stat(primary_surface, "next_close_return_distribution", "p10")
                next_close_payoff_ratio = _safe_float(primary_surface.get("next_close_payoff_ratio"))
                next_close_expectancy = _safe_float(primary_surface.get("next_close_expectancy"))
                t_plus_2_close_positive_rate = _safe_float(primary_surface.get("t_plus_2_close_positive_rate"))
                t_plus_2_close_payoff_ratio = _safe_float(primary_surface.get("t_plus_2_close_payoff_ratio"))
                t_plus_3_close_positive_rate = _safe_float(primary_surface.get("t_plus_3_close_positive_rate"))
                t_plus_3_close_expectancy = _safe_float(primary_surface.get("t_plus_3_close_expectancy"))
                t_plus_3_close_payoff_ratio = _safe_float(primary_surface.get("t_plus_3_close_payoff_ratio"))
                has_t_plus_2_horizon = t_plus_2_median is not None and t_plus_2_close_positive_rate is not None
                has_t_plus_3_horizon = t_plus_3_median is not None and t_plus_3_close_positive_rate is not None and t_plus_3_close_expectancy is not None

                if t_plus_2_median is None:
                    t_plus_2_median = _resolve_distribution_stat(primary_surface, "next_close_return_distribution", "median")
                if t_plus_2_close_positive_rate is None:
                    t_plus_2_close_positive_rate = next_close_positive_rate
                if t_plus_2_close_payoff_ratio is None:
                    t_plus_2_close_payoff_ratio = next_close_payoff_ratio
                if t_plus_3_median is None:
                    t_plus_3_median = t_plus_2_median
                if t_plus_3_close_positive_rate is None:
                    t_plus_3_close_positive_rate = t_plus_2_close_positive_rate
                if t_plus_3_close_expectancy is None:
                    t_plus_3_close_expectancy = _safe_float(primary_surface.get("t_plus_2_close_expectancy"))
                if t_plus_3_close_expectancy is None:
                    t_plus_3_close_expectancy = next_close_expectancy
                if t_plus_3_close_payoff_ratio is None:
                    t_plus_3_close_payoff_ratio = t_plus_2_close_payoff_ratio

                if next_close_positive_rate is None or next_high_hit_rate is None or t_plus_2_median is None or t_plus_3_median is None or max_dd_proxy is None or next_close_expectancy is None or t_plus_2_close_positive_rate is None or t_plus_3_close_positive_rate is None or t_plus_3_close_expectancy is None:
                    logger.warning("Trial skipped due missing metrics for %s scope=%s", input_path, primary_scope)
                    continue

                scoped_rows = _resolve_scope_rows(list(result.get("rows") or []), primary_scope=primary_scope)
                next_day_count = int(primary_surface.get("next_day_available_count") or 0)
                closed_cycle_count = int(primary_surface.get("closed_cycle_count") or 0)
                next_day_weight = min(1.0, max(0.0, next_day_count / 10.0))
                closed_cycle_weight = min(1.0, max(0.0, closed_cycle_count / 6.0))
                sample_weight = min(next_day_weight, closed_cycle_weight)
                if not has_t_plus_2_horizon:
                    sample_weight *= PARTIAL_HORIZON_WEIGHT_PENALTY
                elif not has_t_plus_3_horizon:
                    sample_weight *= PARTIAL_T3_HORIZON_WEIGHT_PENALTY
                # t_plus_3_cycle_count is only present when build_surface_summary is new enough;
                # fall back to sample_weight when absent to preserve backward compatibility.
                # Must be computed AFTER penalty adjustments so t_plus_3_sample_weight reflects
                # the penalised weight rather than the raw sample_weight.
                t_plus_3_cycle_count_raw = primary_surface.get("t_plus_3_cycle_count")
                if t_plus_3_cycle_count_raw is not None:
                    t_plus_3_cycle_count = int(t_plus_3_cycle_count_raw)
                    t_plus_3_cycle_weight = min(1.0, max(0.0, t_plus_3_cycle_count / 4.0))
                    t_plus_3_sample_weight = min(sample_weight, t_plus_3_cycle_weight)
                else:
                    t_plus_3_sample_weight = sample_weight
                sharpe_proxy = (next_close_positive_rate + next_high_hit_rate) * sample_weight
                sortino_proxy = t_plus_2_median * sample_weight
                total_metrics["sharpe"].append(sharpe_proxy)
                total_metrics["sortino"].append(sortino_proxy)
                total_metrics["max_dd"].append(max_dd_proxy)
                # Primary quality metrics: append values and corresponding sample_weight for later weighted averaging
                total_metrics["next_close_positive_rate"].append(next_close_positive_rate)
                total_metric_weights["next_close_positive_rate"].append(sample_weight)
                if next_close_payoff_ratio is not None:
                    total_metrics["next_close_payoff_ratio"].append(next_close_payoff_ratio)
                    total_metric_weights["next_close_payoff_ratio"].append(sample_weight)
                total_metrics["next_close_expectancy"].append(next_close_expectancy)
                total_metric_weights["next_close_expectancy"].append(sample_weight)
                total_metrics["next_high_hit_rate"].append(next_high_hit_rate)
                total_metric_weights["next_high_hit_rate"].append(sample_weight)
                total_metrics["t_plus_2_close_positive_rate"].append(t_plus_2_close_positive_rate)
                total_metric_weights["t_plus_2_close_positive_rate"].append(sample_weight)
                if t_plus_2_close_payoff_ratio is not None:
                    total_metrics["t_plus_2_close_payoff_ratio"].append(t_plus_2_close_payoff_ratio)
                    total_metric_weights["t_plus_2_close_payoff_ratio"].append(sample_weight)
                total_metrics["t_plus_3_close_positive_rate"].append(t_plus_3_close_positive_rate)
                total_metric_weights["t_plus_3_close_positive_rate"].append(t_plus_3_sample_weight)
                total_metrics["t_plus_3_close_expectancy"].append(t_plus_3_close_expectancy)
                total_metric_weights["t_plus_3_close_expectancy"].append(t_plus_3_sample_weight)
                if t_plus_3_close_payoff_ratio is not None:
                    total_metrics["t_plus_3_close_payoff_ratio"].append(t_plus_3_close_payoff_ratio)
                    total_metric_weights["t_plus_3_close_payoff_ratio"].append(t_plus_3_sample_weight)
                total_metrics["downside_p10"].append(max_dd_proxy)
                total_metric_weights["downside_p10"].append(sample_weight)
                # Still track raw sample_weight list for reporting
                total_metrics["sample_weight"].append(sample_weight)

                # Runner horizon metrics
                runner_tail_hit_rate = _safe_float(primary_surface.get("max_future_high_return_2_5d_hit_rate_at_20pct"))
                runner_capture_count = primary_surface.get("runner_capture_count", 0)
                time_to_hit_20pct = _safe_float(primary_surface.get("time_to_hit_20pct_median"))
                if runner_tail_hit_rate is not None:
                    total_metrics["max_future_high_return_2_5d_hit_rate_at_20pct"].append(runner_tail_hit_rate)
                    total_metric_weights["max_future_high_return_2_5d_hit_rate_at_20pct"].append(sample_weight)
                if isinstance(runner_capture_count, (int, float)):
                    total_metrics["runner_capture_count"].append(float(runner_capture_count))
                if time_to_hit_20pct is not None:
                    total_metrics["time_to_hit_20pct_median"].append(time_to_hit_20pct)
                    total_metric_weights["time_to_hit_20pct_median"].append(sample_weight)
                escape_rate = _safe_float(primary_surface.get("runner_escape_rate"))
                if escape_rate is not None:
                    total_metrics["runner_escape_rate"].append(escape_rate)
                avg_escaped_score = _safe_float(primary_surface.get("avg_composite_score_escaped"))
                if avg_escaped_score is not None:
                    total_metrics["avg_composite_score_escaped"].append(avg_escaped_score)
                if primary_scope == "selected":
                    selected_surfaces.append(primary_surface)

                for metric_key in (
                    "projected_theme_exposure",
                    "incremental_theme_exposure",
                    "liquidity_capacity_raw_100",
                    "crowding_risk_raw_100",
                    "gap_risk_raw_100",
                ):
                    metric_value = _average_scope_metric(scoped_rows, metric_key)
                    if metric_value is not None:
                        total_metrics[metric_key].append(metric_value)
                window_count += 1
                coverage_summary = dict(result.get("source_coverage_summary") or {})
                if coverage_summary:
                    source_coverage_summaries.append(coverage_summary)
            except Exception as e:
                logger.warning("Trial failed for %s: %s", input_path, e)
                continue

        if window_count == 0:
            return {
                "sharpe_ratio": None,
                "sortino_ratio": None,
                "max_drawdown": None,
                "next_close_positive_rate": None,
                "next_close_payoff_ratio": None,
                "next_close_expectancy": None,
                "next_high_hit_rate": None,
                "t_plus_2_close_positive_rate": None,
                "t_plus_2_close_payoff_ratio": None,
                "t_plus_3_close_positive_rate": None,
                "t_plus_3_close_expectancy": None,
                "t_plus_3_close_payoff_ratio": None,
                "downside_p10": None,
                "sample_weight": None,
                "window_coverage": 0.0,
                "window_count": 0,
                "source_coverage_pass_ratio": 0.0,
            }

        avg_sharpe = sum(total_metrics["sharpe"]) / len(total_metrics["sharpe"]) if total_metrics["sharpe"] else None
        avg_sortino = sum(total_metrics["sortino"]) / len(total_metrics["sortino"]) if total_metrics["sortino"] else None
        avg_max_dd = sum(total_metrics["max_dd"]) / len(total_metrics["max_dd"]) if total_metrics["max_dd"] else None

        def _weighted_avg(values: list[float], weights: list[float]) -> float | None:
            if not values:
                return None
            total_w = sum(weights) if weights else 0.0
            if total_w <= 0.0:
                return None
            return sum(v * w for v, w in zip(values, weights)) / total_w

        # Primary quality metrics use sample-weighted averages
        avg_next_close_positive_rate = _weighted_avg(total_metrics["next_close_positive_rate"], total_metric_weights["next_close_positive_rate"])
        avg_next_close_payoff_ratio = _weighted_avg(total_metrics["next_close_payoff_ratio"], total_metric_weights["next_close_payoff_ratio"])
        avg_next_close_expectancy = _weighted_avg(total_metrics["next_close_expectancy"], total_metric_weights["next_close_expectancy"])
        avg_next_high_hit_rate = _weighted_avg(total_metrics["next_high_hit_rate"], total_metric_weights["next_high_hit_rate"])
        avg_t_plus_2_close_positive_rate = _weighted_avg(total_metrics["t_plus_2_close_positive_rate"], total_metric_weights["t_plus_2_close_positive_rate"])
        avg_t_plus_2_close_payoff_ratio = _weighted_avg(total_metrics["t_plus_2_close_payoff_ratio"], total_metric_weights["t_plus_2_close_payoff_ratio"])
        avg_t_plus_3_close_positive_rate = _weighted_avg(total_metrics["t_plus_3_close_positive_rate"], total_metric_weights["t_plus_3_close_positive_rate"])
        avg_t_plus_3_close_expectancy = _weighted_avg(total_metrics["t_plus_3_close_expectancy"], total_metric_weights["t_plus_3_close_expectancy"])
        avg_t_plus_3_close_payoff_ratio = _weighted_avg(total_metrics["t_plus_3_close_payoff_ratio"], total_metric_weights["t_plus_3_close_payoff_ratio"])
        avg_downside_p10 = _weighted_avg(total_metrics["downside_p10"], total_metric_weights["downside_p10"])

        # Runner horizon metrics
        avg_runner_tail_hit_rate = _weighted_avg(total_metrics["max_future_high_return_2_5d_hit_rate_at_20pct"], total_metric_weights["max_future_high_return_2_5d_hit_rate_at_20pct"])
        total_runner_capture_count = int(sum(total_metrics["runner_capture_count"])) if total_metrics["runner_capture_count"] else 0
        avg_time_to_hit_20pct = _weighted_avg(total_metrics["time_to_hit_20pct_median"], total_metric_weights["time_to_hit_20pct_median"])
        avg_runner_escape_rate = sum(total_metrics["runner_escape_rate"]) / len(total_metrics["runner_escape_rate"]) if total_metrics["runner_escape_rate"] else None
        avg_composite_score_escaped = sum(total_metrics["avg_composite_score_escaped"]) / len(total_metrics["avg_composite_score_escaped"]) if total_metrics["avg_composite_score_escaped"] else None

        def _weighted_average_distribution_median(surfaces: list[dict[str, Any]], dist_key: str) -> float | None:
            """Compute sample-weighted average of distribution medians from selected surfaces."""
            medians_and_weights: list[tuple[float, float]] = []
            for surf in surfaces:
                dist = dict(surf.get(dist_key) or {})
                median_val = _safe_float(dist.get("median"))
                next_day = surf.get("next_day_available_count", 0)
                closed = surf.get("closed_cycle_count", 0)
                if median_val is not None and next_day > 0 and closed > 0:
                    w = min(1.0, min(next_day / 10.0, closed / 6.0))
                    medians_and_weights.append((median_val, w))
            if not medians_and_weights:
                return None
            total_w = sum(w for _, w in medians_and_weights)
            if total_w <= 0.0:
                return None
            return sum(m * w for m, w in medians_and_weights) / total_w

        median_max_future_high_return_2_5d = _weighted_average_distribution_median(selected_surfaces, "max_future_high_return_2_5d_distribution")

        # Execution/exposure and other metrics remain simple unweighted means
        avg_sample_weight = sum(total_metrics["sample_weight"]) / len(total_metrics["sample_weight"]) if total_metrics["sample_weight"] else None
        avg_projected_theme_exposure = sum(total_metrics["projected_theme_exposure"]) / len(total_metrics["projected_theme_exposure"]) if total_metrics["projected_theme_exposure"] else None
        avg_incremental_theme_exposure = sum(total_metrics["incremental_theme_exposure"]) / len(total_metrics["incremental_theme_exposure"]) if total_metrics["incremental_theme_exposure"] else None
        avg_liquidity_capacity_raw_100 = sum(total_metrics["liquidity_capacity_raw_100"]) / len(total_metrics["liquidity_capacity_raw_100"]) if total_metrics["liquidity_capacity_raw_100"] else None
        avg_crowding_risk_raw_100 = sum(total_metrics["crowding_risk_raw_100"]) / len(total_metrics["crowding_risk_raw_100"]) if total_metrics["crowding_risk_raw_100"] else None
        avg_gap_risk_raw_100 = sum(total_metrics["gap_risk_raw_100"]) / len(total_metrics["gap_risk_raw_100"]) if total_metrics["gap_risk_raw_100"] else None
        window_coverage = float(window_count) / float(len(input_paths) or 1)
        effective_sample_weight = max(0.0, min(1.0, avg_sample_weight * window_coverage)) if avg_sample_weight is not None else None
        source_coverage_pass_ratio = _compute_source_coverage_pass_ratio(source_coverage_summaries)

        return {
            "sharpe_ratio": avg_sharpe,
            "sortino_ratio": avg_sortino,
            "max_drawdown": avg_max_dd,
            "next_close_positive_rate": avg_next_close_positive_rate,
            "next_close_payoff_ratio": avg_next_close_payoff_ratio,
            "next_close_expectancy": avg_next_close_expectancy,
            "next_high_hit_rate": avg_next_high_hit_rate,
            "t_plus_2_close_positive_rate": avg_t_plus_2_close_positive_rate,
            "t_plus_2_close_payoff_ratio": avg_t_plus_2_close_payoff_ratio,
            "t_plus_3_close_positive_rate": avg_t_plus_3_close_positive_rate,
            "t_plus_3_close_expectancy": avg_t_plus_3_close_expectancy,
            "t_plus_3_close_payoff_ratio": avg_t_plus_3_close_payoff_ratio,
            "downside_p10": avg_downside_p10,
            "sample_weight": effective_sample_weight,
            "window_coverage": window_coverage,
            "window_count": window_count,
            "source_coverage_pass_ratio": source_coverage_pass_ratio,
            "projected_theme_exposure": avg_projected_theme_exposure,
            "incremental_theme_exposure": avg_incremental_theme_exposure,
            "liquidity_capacity_raw_100": avg_liquidity_capacity_raw_100,
            "crowding_risk_raw_100": avg_crowding_risk_raw_100,
            "gap_risk_raw_100": avg_gap_risk_raw_100,
            "max_future_high_return_2_5d_hit_rate_at_20pct": avg_runner_tail_hit_rate,
            "runner_capture_count": total_runner_capture_count,
            "median_max_future_high_return_2_5d": median_max_future_high_return_2_5d,
            "time_to_hit_20pct_median": avg_time_to_hit_20pct,
            "runner_escape_rate": avg_runner_escape_rate,
            "avg_composite_score_escaped": avg_composite_score_escaped,
        }

    return evaluator


# Minimum fraction of exact_tick sources required to pass the source-coverage guardrail.
_IGNITION_SOURCE_COVERAGE_MIN_RATIO = 0.5


def _build_staged_ignition_evaluator(
    input_paths: list[Path],
    *,
    base_profile: str,
    next_high_hit_threshold: float = 0.02,
) -> Callable:
    """Build a staged evaluator that injects baseline-awareness and guardrail metrics.

    Pre-computes ignition_breakout (no overrides) and default profile baselines once,
    then wraps each candidate evaluation to inject:
    - baseline_next_close_positive_rate_delta
    - baseline_next_close_expectancy_delta
    - promotion_guardrail_pass
    - source_coverage_pass_ratio

    Args:
        input_paths: Replay window input paths.
        base_profile: Must be "ignition_breakout" for stage1.
        next_high_hit_threshold: Threshold for next-high hit rate computation.

    Returns:
        Callable evaluator that returns metrics with baseline-aware fields injected.
    """
    assert base_profile == "ignition_breakout", (
        f"_build_staged_ignition_evaluator requires 'ignition_breakout', got '{base_profile}'"
    )

    _ignition_evaluator = _build_replay_evaluator(
        input_paths, base_profile="ignition_breakout", next_high_hit_threshold=next_high_hit_threshold
    )
    _default_evaluator = _build_replay_evaluator(
        input_paths, base_profile="default", next_high_hit_threshold=next_high_hit_threshold
    )

    logger.info("Staged ignition evaluator: pre-computing ignition_breakout baseline…")
    ignition_baseline = _ignition_evaluator({})
    logger.info("Staged ignition evaluator: pre-computing default baseline…")
    default_baseline = _default_evaluator({})

    ignition_win_rate = ignition_baseline.get("next_close_positive_rate")
    ignition_expectancy = ignition_baseline.get("next_close_expectancy")
    default_win_rate = default_baseline.get("next_close_positive_rate")

    if ignition_win_rate is None:
        raise RuntimeError(
            "Staged ignition evaluator: ignition_breakout baseline missing 'next_close_positive_rate'. "
            "Cannot run stage1 promotion guardrail without a valid baseline."
        )
    if ignition_expectancy is None:
        raise RuntimeError(
            "Staged ignition evaluator: ignition_breakout baseline missing 'next_close_expectancy'. "
            "Cannot run stage1 promotion guardrail without a valid baseline."
        )
    if default_win_rate is None:
        raise RuntimeError(
            "Staged ignition evaluator: default profile baseline missing 'next_close_positive_rate'. "
            "Cannot run stage1 promotion guardrail without a valid baseline."
        )

    logger.info(
        "Baselines — ignition_breakout: win_rate=%.4f expectancy=%.4f | default: win_rate=%.4f",
        ignition_win_rate,
        ignition_expectancy,
        default_win_rate,
    )

    _candidate_evaluator = _build_replay_evaluator(
        input_paths, base_profile=base_profile, next_high_hit_threshold=next_high_hit_threshold
    )

    def staged_evaluator(params: dict[str, Any]) -> dict[str, float | None]:
        metrics: dict[str, Any] = dict(_candidate_evaluator(params))

        cand_win_rate = metrics.get("next_close_positive_rate")
        cand_expectancy = metrics.get("next_close_expectancy")

        metrics["baseline_next_close_positive_rate_delta"] = (
            (float(cand_win_rate) - float(ignition_win_rate)) if cand_win_rate is not None else None
        )
        metrics["baseline_next_close_expectancy_delta"] = (
            (float(cand_expectancy) - float(ignition_expectancy)) if cand_expectancy is not None else None
        )

        source_coverage_pass_ratio = float(metrics.get("source_coverage_pass_ratio") or 0.0)
        if cand_win_rate is None or cand_expectancy is None:
            promotion_guardrail_pass = False
        else:
            promotion_guardrail_pass = (
                float(cand_win_rate) >= float(ignition_win_rate)
                and float(cand_expectancy) >= float(ignition_expectancy)
                and float(cand_win_rate) >= float(default_win_rate)
                and source_coverage_pass_ratio >= _IGNITION_SOURCE_COVERAGE_MIN_RATIO
            )
        metrics["promotion_guardrail_pass"] = promotion_guardrail_pass

        return metrics

    return staged_evaluator


def _build_staged_ignition_shortlist(report: SearchReport, *, top_n: int = 5) -> list[dict[str, Any]]:
    """Extract top-N candidates from a stage1 search report and annotate each with a promotion verdict.

    Rows with a valid score are ranked first (descending); guardrail-failed rows (score=None) follow.
    Each row's verdict is derived from the ``promotion_guardrail_pass`` flag injected by the staged
    evaluator.  Row-level context (baseline deltas, source coverage) is surfaced so callers can
    understand *why* a row is or is not promotable.

    Args:
        report: Completed ``SearchReport`` from a stage1 ignition search.
        top_n: Maximum number of shortlist rows to return.

    Returns:
        List of dicts, each containing ``params``, ``score``, ``promotion_verdict``,
        ``baseline_next_close_positive_rate_delta``, ``baseline_next_close_expectancy_delta``,
        and ``source_coverage_pass_ratio``.
    """
    scored = sorted(
        (r for r in report.results if r.score is not None),
        key=lambda r: r.score or 0.0,
        reverse=True,
    )
    unscored = [r for r in report.results if r.score is None]
    candidates = (scored + unscored)[:top_n]

    shortlist: list[dict[str, Any]] = []
    for row in candidates:
        metrics: dict[str, Any] = row.metrics or {}
        guardrail_pass = bool(metrics.get("promotion_guardrail_pass", False))
        shortlist.append(
            {
                "params": row.params,
                "score": row.score,
                "promotion_verdict": "promotable" if guardrail_pass else "not_promotable",
                "baseline_next_close_positive_rate_delta": metrics.get("baseline_next_close_positive_rate_delta"),
                "baseline_next_close_expectancy_delta": metrics.get("baseline_next_close_expectancy_delta"),
                "source_coverage_pass_ratio": metrics.get("source_coverage_pass_ratio"),
            }
        )
    return shortlist


def _format_staged_ignition_summary(report: SearchReport) -> str:
    """Format a human-readable stage1 calibration summary with shortlist and overall verdict.

    Args:
        report: Completed ``SearchReport`` from a stage1 ignition search.

    Returns:
        Markdown-formatted summary string.
    """
    shortlist = _build_staged_ignition_shortlist(report)
    lines: list[str] = ["## Stage 1 Ignition Calibration Summary", ""]

    # Overall verdict is derived from the *full* report.results, not just the displayed shortlist,
    # so that a promotable candidate outside the top-N cap doesn't get silently hidden.
    any_promotable_in_full_report = any(
        bool((r.metrics or {}).get("promotion_guardrail_pass", False)) for r in report.results
    )
    if any_promotable_in_full_report:
        lines.append("**Overall verdict: PROMOTION AVAILABLE** — at least one candidate clears all guardrails.")
    else:
        lines.append("**Overall verdict: KEEP CURRENT IGNITION PROFILE** — no promotable candidates found.")
    lines.append("")

    if not shortlist:
        lines.append("*(no candidates evaluated)*")
        return "\n".join(lines)

    lines.append("### Top Candidates")
    lines.append("")
    for rank, row in enumerate(shortlist, 1):
        score_str = f"{row['score']:.4f}" if row["score"] is not None else "n/a"
        verdict = row.get("promotion_verdict", "n/a")
        marker = "✓" if verdict == "promotable" else "✗"
        lines.append(f"**#{rank}** {marker} score={score_str} | verdict={verdict}")

        delta_wr = row.get("baseline_next_close_positive_rate_delta")
        delta_ex = row.get("baseline_next_close_expectancy_delta")
        cov = row.get("source_coverage_pass_ratio")
        if delta_wr is not None:
            lines.append(f"  - win_rate_delta_vs_baseline: {delta_wr:+.4f}")
        if delta_ex is not None:
            lines.append(f"  - expectancy_delta_vs_baseline: {delta_ex:+.4f}")
        if cov is not None:
            lines.append(f"  - source_coverage_pass_ratio: {cov:.4f}")

        params = row.get("params") or {}
        for k, v in sorted(params.items()):
            lines.append(f"  - {k}={v}")
        lines.append("")

    return "\n".join(lines)


def _build_walk_forward_evaluator(
    *,
    tickers: list[str],
    start_date: str,
    end_date: str,
    initial_capital: float,
    model_name: str,
    model_provider: str,
    selected_analysts: list[str] | None,
    train_months: int = 2,
    test_months: int = 2,
    step_months: int = 1,
    base_profile: str,
) -> Callable:
    from src.backtesting.engine import BacktestEngine
    from src.backtesting.walk_forward import (
        build_walk_forward_windows,
        run_walk_forward,
        summarize_walk_forward,
        WindowMode,
    )
    from src.main import run_hedge_fund
    from src.targets.profiles import use_short_trade_target_profile

    def evaluator(params: dict[str, Any]) -> dict[str, float | None]:
        windows = build_walk_forward_windows(
            start_date,
            end_date,
            train_months=train_months,
            test_months=test_months,
            step_months=step_months,
            window_mode=WindowMode.ROLLING,
        )
        with use_short_trade_target_profile(profile_name=base_profile, overrides=params):
            results = run_walk_forward(
                windows,
                lambda w: BacktestEngine(
                    agent=run_hedge_fund,
                    tickers=tickers,
                    start_date=w.test_start,
                    end_date=w.test_end,
                    initial_capital=initial_capital,
                    model_name=model_name,
                    model_provider=model_provider,
                    selected_analysts=selected_analysts,
                    initial_margin_requirement=0.0,
                    backtest_mode="pipeline",
                ),
            )
        summary = summarize_walk_forward(results)
        return {
            "sharpe_ratio": summary.get("avg_sharpe"),
            "sortino_ratio": summary.get("avg_sortino"),
            "max_drawdown": summary.get("avg_max_drawdown"),
            "window_count": summary.get("window_count", 0),
        }

    return evaluator


MOMENTUM_OPTIMIZED_GRID: dict[str, list[Any]] = {
    "select_threshold": [0.46, 0.50, 0.54],
    "near_miss_threshold": [0.30, 0.34, 0.38],
    "breakout_freshness_weight": [0.12, 0.16],
    "trend_acceleration_weight": [0.18, 0.22],
    "volume_expansion_quality_weight": [0.16, 0.20],
    "close_strength_weight": [0.12, 0.16],
    "catalyst_freshness_weight": [0.10, 0.14],
    "momentum_strength_weight": [0.00, 0.06],
    "short_term_reversal_weight": [0.00, 0.04],
    "stale_penalty_block_threshold": [0.78, 0.82],
    "overhead_penalty_block_threshold": [0.74, 0.78],
    "extension_penalty_block_threshold": [0.80, 0.84],
}

EVENT_CATALYST_GRID: dict[str, list[Any]] = {
    "event_catalyst_selected_uplift": [0.02, 0.03],
    "event_catalyst_near_miss_threshold_relief": [0.01, 0.02],
    "event_catalyst_min_score_for_selected_uplift": [0.68, 0.72],
    "event_catalyst_min_score_for_near_miss_retain": [0.54, 0.58],
    "event_catalyst_sector_resonance_weight": [0.18, 0.22],
}

ROUTED_BTST_COMMITTEE_GRID: dict[str, list[Any]] = {
    "committee_alpha_min_aggressive_trade": [66.0, 68.0, 70.0],
    "committee_beta_min_aggressive_trade": [56.0, 58.0, 60.0],
    "committee_gamma_min_aggressive_trade": [54.0, 56.0, 58.0],
    "committee_score_min_aggressive_trade": [64.0, 66.0, 68.0],
    "committee_alpha_min_normal_trade": [64.0, 66.0, 68.0],
    "committee_beta_min_normal_trade": [60.0, 62.0, 64.0],
    "committee_gamma_min_normal_trade": [56.0, 58.0, 60.0],
    "committee_score_min_normal_trade": [62.0, 64.0, 66.0],
    "committee_fragile_breakout_alpha_weight": [0.08, 0.10, 0.12],
    "committee_fragile_breakout_activation_floor": [56.0, 60.0, 64.0],
    "committee_fragile_breakout_fragility_floor": [52.0, 55.0, 58.0],
    "committee_fragile_breakout_risk_cap": [75.0, 85.0],
}

ROUTED_BTST_COMMITTEE_PROFILES = {
    "ignition_breakout",
    "retention_follow",
    "shadow_research",
}

# Runner escape threshold and composite weight calibration grid for btst_runner_probe.
# Run with --preset-grid --profile btst_runner_probe --objective btst_runner to search over
# escape gate tightness and composite score weight emphasis simultaneously.
BTST_RUNNER_PROBE_GRID: dict[str, list[Any]] = {
    "runner_escape_breakout_freshness_min": [0.25, 0.30, 0.35, 0.40],
    "runner_escape_trend_acceleration_min": [0.45, 0.50, 0.55, 0.60],
    "runner_escape_volume_expansion_quality_min": [0.30, 0.35, 0.40],
    "runner_composite_score_breakout_weight": [0.35, 0.40, 0.45],
    "runner_composite_score_trend_weight": [0.25, 0.30, 0.35],
    "runner_composite_score_volume_weight": [0.15, 0.20, 0.25],
    "runner_composite_score_catalyst_weight": [0.05, 0.10, 0.15],
    "runner_composite_score_close_strength_weight": [0.05, 0.10, 0.15],
    "historical_continuation_score_weight": [0.0, 0.05, 0.10],
    "runner_composite_score_volatility_regime_weight": [0.0, 0.05, 0.10],
    "runner_composite_score_sector_resonance_weight": [0.0, 0.05, 0.10],
    "runner_escape_gap_risk_raw_100_max": [40.0, 45.0, 52.0],
    "runner_escape_projected_theme_exposure_max": [0.24, 0.28, 0.32],
    "runner_escape_candidate_pool_avg_amount_share_of_cutoff_min": [0.85, 1.0, 1.15],
    "runner_escape_composite_score_min": [0.0, 0.40, 0.45, 0.50],
}

IGNITION_STAGE1_GRID: dict[str, list[Any]] = {
    "committee_alpha_min_aggressive_trade": [66.0, 68.0],
    "committee_beta_min_aggressive_trade": [56.0, 58.0],
    "committee_gamma_min_aggressive_trade": [54.0, 56.0],
    "committee_score_min_aggressive_trade": [64.0, 66.0],
    "committee_alpha_min_normal_trade": [64.0, 66.0],
    "committee_beta_min_normal_trade": [60.0, 62.0],
    "committee_gamma_min_normal_trade": [56.0, 58.0],
    "committee_score_min_normal_trade": [62.0, 64.0],
    "committee_fragile_breakout_alpha_weight": [0.08, 0.10],
    "committee_fragile_breakout_activation_floor": [56.0, 60.0],
    "committee_fragile_breakout_fragility_floor": [52.0, 55.0],
    "committee_fragile_breakout_risk_cap": [75.0, 80.0],
}

def resolve_grid_params(
    *,
    grid_params: list[str],
    preset_grid: bool,
    profile_name: str,
    search_stage: str = "full",
    staged_mode: str | None = None,
) -> dict[str, list[Any]]:
    """Resolve grid parameters with optional preset and profile-specific extensions.

    Args:
        grid_params: Raw grid parameter strings to parse
        preset_grid: Whether to include base preset grid
        profile_name: Profile name for profile-specific grid extensions
        search_stage: Optional stage-aware preset variant
        staged_mode: Optional staged calibration mode (e.g. "ignition_stage1")

    Returns:
        Merged grid dictionary with parsed params taking precedence
    """
    resolved = _parse_grid_params(grid_params)
    if staged_mode == "ignition_stage1":
        if profile_name != "ignition_breakout":
            raise ValueError(
                f"--staged-mode ignition_stage1 is only valid for profile 'ignition_breakout', got '{profile_name}'"
            )
        return {**IGNITION_STAGE1_GRID, **resolved}
    base_momentum_grid = MOMENTUM_OPTIMIZED_STAGE_PRESET_GRIDS.get(search_stage, MOMENTUM_OPTIMIZED_GRID)
    if preset_grid and profile_name == "event_catalyst_guarded":
        return {**base_momentum_grid, **EVENT_CATALYST_GRID, **resolved}
    if preset_grid and profile_name in ROUTED_BTST_COMMITTEE_PROFILES:
        return {**ROUTED_BTST_COMMITTEE_GRID, **resolved}
    if preset_grid and profile_name == "btst_runner_probe":
        return {**BTST_RUNNER_PROBE_GRID, **resolved}
    if preset_grid:
        return {**base_momentum_grid, **resolved}
    return resolved


def _build_search_metadata(
    *,
    search_stage: str,
    guardrails: dict[str, GuardrailSpec],
    focus_json: str | None,
    checkpoint_path: str,
    stage_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "search_stage": search_stage,
        "guardrails": guardrails,
        "focus_source": focus_json,
        "checkpoint_path": checkpoint_path,
    }
    if stage_results is not None:
        payload["stage_results"] = stage_results
    return payload


def _build_comparison_entry(*, candidate_metrics: dict[str, Any], baseline_metrics: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "candidate": candidate_metrics,
        "baseline": baseline_metrics,
    }
    for metric in COMPARISON_METRICS:
        candidate_value = _safe_float(candidate_metrics.get(metric))
        baseline_value = _safe_float(baseline_metrics.get(metric))
        entry[f"{metric}_delta"] = None if candidate_value is None or baseline_value is None else candidate_value - baseline_value
    return entry


def _build_replay_comparison_summary(
    *,
    replay_input_paths: list[Path],
    base_profile: str,
    best_params: dict[str, Any],
    next_high_hit_threshold: float,
) -> dict[str, dict[str, Any]]:
    candidate_metrics = _build_replay_evaluator(
        replay_input_paths,
        base_profile=base_profile,
        next_high_hit_threshold=next_high_hit_threshold,
    )(best_params)
    baseline_names = [base_profile]
    if base_profile != "default":
        baseline_names.append("default")

    summary: dict[str, dict[str, Any]] = {}
    for baseline_name in baseline_names:
        baseline_metrics = _build_replay_evaluator(
            replay_input_paths,
            base_profile=baseline_name,
            next_high_hit_threshold=next_high_hit_threshold,
        )({})
        summary[baseline_name] = _build_comparison_entry(
            candidate_metrics=candidate_metrics,
            baseline_metrics=baseline_metrics,
        )
    return summary


def _build_rollout_recommendation_payload(comparison_summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not comparison_summary:
        return {
            "action": "hold",
            "blockers": ["missing_comparison_summary"],
            "baseline_verdicts": {},
        }

    blockers: list[str] = []
    baseline_verdicts: dict[str, dict[str, Any]] = {}
    for baseline_name, entry in comparison_summary.items():
        baseline_blockers: list[str] = []
        for metric in COMPARISON_METRICS:
            delta = _safe_float(entry.get(f"{metric}_delta"))
            if delta is None:
                if metric not in OPTIONAL_COMPARISON_METRICS:
                    baseline_blockers.append(f"missing_{metric}_delta_vs_{baseline_name}")
                continue
            epsilon = float(COMPARISON_METRIC_EPSILON.get(metric, 0.0) or 0.0)
            metric_regressed = delta > epsilon if metric in LOWER_IS_BETTER_COMPARISON_METRICS else delta < -epsilon
            if metric_regressed:
                baseline_blockers.append(f"{metric}_regressed_vs_{baseline_name}")
        blockers.extend(baseline_blockers)
        baseline_verdicts[baseline_name] = {
            "status": "pass" if not baseline_blockers else "blocked",
            "blockers": baseline_blockers,
        }

    deduped_blockers = list(dict.fromkeys(blockers))
    return {
        "action": "promote" if not deduped_blockers else "hold",
        "blockers": deduped_blockers,
        "baseline_verdicts": baseline_verdicts,
    }


def _recommend_rollout_action(comparison_summary: dict[str, dict[str, Any]]) -> str:
    return str(_build_rollout_recommendation_payload(comparison_summary).get("action") or "hold")


def _build_optimized_profile_manifest_publication(
    *,
    objective: SearchObjective,
    replay_mode: bool,
    replay_input_paths: list[Path] | None,
    best_params: dict[str, Any] | None,
    rollout_recommendation: str | None,
    profile_name: str,
    source_path: str | Path,
    manifest_path: str | Path,
) -> dict[str, Any]:
    resolved_manifest_path = Path(manifest_path).expanduser().resolve()
    if objective != SearchObjective.BTST:
        return {
            "status": "skipped",
            "reason": "non_btst_objective",
            "manifest_path": str(resolved_manifest_path),
        }
    if not replay_mode or not replay_input_paths:
        return {
            "status": "skipped",
            "reason": "non_replay_run",
            "manifest_path": str(resolved_manifest_path),
        }
    if best_params is None:
        return {
            "status": "skipped",
            "reason": "missing_best_params",
            "manifest_path": str(resolved_manifest_path),
        }
    return publish_btst_optimized_profile_manifest(
        manifest_path=resolved_manifest_path,
        rollout_recommendation=rollout_recommendation or "hold",
        profile_name=profile_name,
        profile_overrides=best_params,
        source_path=source_path,
        replay_input_paths=replay_input_paths,
    )


def _persist_search_metadata(
    *,
    md_path: Path,
    json_path: Path,
    metadata: dict[str, Any],
    comparison_summary: dict[str, dict[str, Any]] | None = None,
    rollout_recommendation: str | None = None,
    rollout_recommendation_details: dict[str, Any] | None = None,
    optimized_profile_manifest_publication: dict[str, Any] | None = None,
) -> None:
    md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else "# Parameter Search Report\n"
    metadata_lines = [
        "## Search Metadata",
        "",
        f"Search Stage: **{metadata['search_stage']}**",
        f"Checkpoint: `{metadata['checkpoint_path']}`",
    ]
    if metadata.get("focus_source"):
        metadata_lines.append(f"Focus Source: `{metadata['focus_source']}`")
    if metadata.get("guardrails"):
        metadata_lines.append("")
        metadata_lines.append("Guardrails:")
        for key, value in sorted(dict(metadata["guardrails"]).items()):
            metadata_lines.append(f"- `{key}`: {_format_guardrail_spec(value)}")
    md_block = "\n".join(metadata_lines)
    base_md_text = md_text.split("## Search Metadata", 1)[0].rstrip() if "## Search Metadata" in md_text else md_text.rstrip()
    md_sections = [base_md_text, md_block]
    if comparison_summary:
        metric_headers = [COMPARISON_METRIC_LABELS[metric] for metric in COMPARISON_METRICS]
        comparison_lines = [
            "## Baseline Comparison",
            "",
            "| Baseline | " + " | ".join(f"{label} Δ" for label in metric_headers) + " |",
            "| --- | " + " | ".join("---" for _ in metric_headers) + " |",
        ]
        for baseline_name, entry in comparison_summary.items():
            comparison_lines.append(
                "| "
                + baseline_name
                + " | "
                + " | ".join(
                    f"{float(entry[f'{metric}_delta']):.4f}" if _safe_float(entry.get(f"{metric}_delta")) is not None else "N/A"
                    for metric in COMPARISON_METRICS
                )
                + " |"
            )
        md_sections.append("\n".join(comparison_lines))
    if rollout_recommendation:
        rollout_lines = [f"Rollout Recommendation: **{rollout_recommendation}**"]
        blockers = list((rollout_recommendation_details or {}).get("blockers") or [])
        if blockers:
            rollout_lines.append("")
            rollout_lines.append("Rollout Blockers:")
            rollout_lines.extend(f"- `{blocker}`" for blocker in blockers)
        md_sections.append("\n".join(rollout_lines))
    if optimized_profile_manifest_publication:
        publication_lines = [f"Optimized Profile Manifest Publication: **{optimized_profile_manifest_publication['status']}**"]
        manifest_path = optimized_profile_manifest_publication.get("manifest_path")
        if manifest_path:
            publication_lines.append(f"- manifest_path: `{manifest_path}`")
        reason = optimized_profile_manifest_publication.get("reason")
        if reason:
            publication_lines.append(f"- reason: `{reason}`")
        md_sections.append("\n".join(publication_lines))
    md_text = "\n\n".join(section for section in md_sections if section) + "\n"
    md_path.write_text(md_text, encoding="utf-8")

    payload = json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else {}
    payload["metadata"] = metadata
    if comparison_summary is not None:
        payload["comparison_summary"] = comparison_summary
    if rollout_recommendation is not None:
        payload["rollout_recommendation"] = rollout_recommendation
    if rollout_recommendation_details is not None:
        payload["rollout_recommendation_details"] = rollout_recommendation_details
    if optimized_profile_manifest_publication is not None:
        payload["optimized_profile_manifest_publication"] = optimized_profile_manifest_publication
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _load_focus_params(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    best_params = payload.get("best_params")
    if isinstance(best_params, dict):
        return best_params
    completed_trials = [trial for trial in list(payload.get("completed_trials") or []) if isinstance(trial.get("params"), dict)]
    if completed_trials:
        completed_trials.sort(key=lambda trial: float(trial.get("score") or float("-inf")), reverse=True)
        return dict(completed_trials[0]["params"])
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"Could not load best_params from {path}")


def _resolve_focus_params_source(*, focus_json: str | None, checkpoint_path: str | None) -> tuple[dict[str, Any], str]:
    if focus_json:
        return _load_focus_params(focus_json), str(focus_json)
    if checkpoint_path and Path(checkpoint_path).exists():
        return _load_focus_params(checkpoint_path), str(checkpoint_path)
    raise ValueError("focused search stage requires --focus-json or an existing --checkpoint")


def _stage_checkpoint_path(checkpoint_path: str, stage_name: str) -> str:
    path = Path(checkpoint_path)
    if path.suffix:
        return str(path.with_name(f"{path.stem}_{stage_name}{path.suffix}"))
    return f"{checkpoint_path}_{stage_name}"


def _report_best_params(report: Any) -> dict[str, Any] | None:
    if isinstance(report, dict):
        params = report.get("best_params")
        return dict(params) if isinstance(params, dict) else None
    params = getattr(report, "best_params", None)
    return dict(params) if isinstance(params, dict) else None


def _report_best_score(report: Any) -> float | None:
    if isinstance(report, dict):
        return _safe_float(report.get("best_score"))
    return _safe_float(getattr(report, "best_score", None))


def _enforce_max_combinations(space: ParamSpace, max_combinations: int | None) -> None:
    if max_combinations is None:
        return
    size = space.size()
    if size > max_combinations:
        raise ValueError(f"max_combinations exceeded: grid has {size} combinations, limit={max_combinations}")


def build_stage_grid(
    *,
    base_grid: dict[str, list[Any]],
    search_stage: str,
    focus_params: dict[str, Any] | None = None,
) -> dict[str, list[Any]]:
    if search_stage != "focused":
        return base_grid
    if not focus_params:
        raise ValueError("focused search stage requires focus_params")

    focused_grid: dict[str, list[Any]] = {}
    for key, values in base_grid.items():
        focus_value = focus_params.get(key)
        if focus_value is None:
            focused_grid[key] = values
            continue
        if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            if len(values) <= 3:
                focused_grid[key] = values
                continue
            if focus_value in values:
                focus_index = values.index(focus_value)
            else:
                focus_index = min(range(len(values)), key=lambda idx: abs(float(values[idx]) - float(focus_value)))
            start = max(0, focus_index - 1)
            end = min(len(values), start + 3)
            start = max(0, end - 3)
            focused_grid[key] = values[start:end]
            continue
        focused_grid[key] = [focus_value] if focus_value in values else values
    return focused_grid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Optimize short-trade target profile parameters")
    parser.add_argument("--profile", default="momentum_optimized", help="Base profile name")
    parser.add_argument("--objective", choices=[o.value for o in SearchObjective], default="edge")
    parser.add_argument("--input", nargs="+", help="Replay input JSON paths (replay mode)")
    parser.add_argument("--reports-root", default=None, help="Reports root for weekly replay-input auto-discovery")
    parser.add_argument("--weekly-start-date", default=None, help="Weekly replay-input discovery start date")
    parser.add_argument("--weekly-end-date", default=None, help="Weekly replay-input discovery end date")
    parser.add_argument("--grid-params", nargs="+", help="Grid params as key=val1,val2 or path/to.json")
    parser.add_argument("--preset-grid", action="store_true", help="Use built-in momentum_optimized grid")
    parser.add_argument(
        "--staged-mode",
        choices=["ignition_stage1"],
        default=None,
        help="Run a narrow staged calibration workflow for a routed BTST profile.",
    )
    parser.add_argument("--output-json", default=None, help="Output JSON path")
    parser.add_argument("--output-md", default=None, help="Output Markdown path")
    parser.add_argument("--checkpoint", default=None, help="Checkpoint file for resume")
    parser.add_argument("--guardrail", action="append", default=None, help="Guardrail bound as metric=floor, metric>=floor, or metric<=cap; may be repeated")
    parser.add_argument("--search-stage", choices=["full", "coarse", "focused", "staged"], default="full", help="Search stage strategy")
    parser.add_argument("--focus-json", default=None, help="JSON file with best_params for focused stage")
    parser.add_argument("--max-combinations", type=int, default=None, help="Fail fast when grid size exceeds this budget")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    # Walk-forward mode args
    parser.add_argument("--tickers", default=None, help="Tickers for walk-forward mode")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--model-provider", default=None)
    parser.add_argument("--train-months", type=int, default=2)
    parser.add_argument("--test-months", type=int, default=2)
    parser.add_argument("--step-months", type=int, default=1)
    args = parser.parse_args(argv)

    get_short_trade_target_profile(args.profile)

    if args.preset_grid or args.grid_params or args.staged_mode:
        try:
            grid = resolve_grid_params(
                grid_params=args.grid_params or [],
                preset_grid=args.preset_grid,
                profile_name=args.profile,
                search_stage=args.search_stage,
                staged_mode=args.staged_mode,
            )
        except ValueError as exc:
            parser.error(str(exc))
    else:
        parser.error("Specify --preset-grid or --grid-params")

    focus_source = args.focus_json
    if args.search_stage == "focused":
        focus_params, focus_source = _resolve_focus_params_source(
            focus_json=args.focus_json,
            checkpoint_path=args.checkpoint,
        )
        grid = build_stage_grid(
            base_grid=grid,
            search_stage=args.search_stage,
            focus_params=focus_params,
        )

    space = ParamSpace(grid=grid)
    _enforce_max_combinations(space, args.max_combinations)
    logger.info("Grid size: %d combinations", space.size())

    objective = SearchObjective(args.objective)

    replay_input_paths: list[Path] | None = None
    walk_forward_descriptor: str | None = None
    replay_mode = False
    if args.input or (args.reports_root and args.weekly_start_date and args.weekly_end_date):
        replay_mode = True
        replay_input_paths = resolve_replay_input_paths(
            input_paths=args.input,
            reports_root=args.reports_root,
            weekly_start_date=args.weekly_start_date,
            weekly_end_date=args.weekly_end_date,
        )
        if args.staged_mode == "ignition_stage1":
            evaluator = _build_staged_ignition_evaluator(
                replay_input_paths,
                base_profile=args.profile,
                next_high_hit_threshold=args.next_high_hit_threshold,
            )
        else:
            evaluator = _build_replay_evaluator(
                replay_input_paths,
                base_profile=args.profile,
                next_high_hit_threshold=args.next_high_hit_threshold,
            )
    elif args.tickers and args.start_date and args.end_date:
        if args.staged_mode == "ignition_stage1":
            parser.error(
                "--staged-mode ignition_stage1 requires replay inputs (--input or --reports-root). "
                "Walk-forward mode does not support staged evaluation."
            )
        walk_forward_descriptor = "|".join(
            [
                str(args.tickers),
                str(args.start_date),
                str(args.end_date),
                str(args.initial_capital),
                str(args.model_name),
                str(args.model_provider),
                str(args.train_months),
                str(args.test_months),
                str(args.step_months),
            ]
        )
        evaluator = _build_walk_forward_evaluator(
            tickers=args.tickers.split(","),
            start_date=args.start_date,
            end_date=args.end_date,
            initial_capital=args.initial_capital,
            model_name=args.model_name,
            model_provider=args.model_provider,
            selected_analysts=None,
            train_months=args.train_months,
            test_months=args.test_months,
            step_months=args.step_months,
            base_profile=args.profile,
        )
    else:
        parser.error("Specify --input, or --reports-root with --weekly-start-date and --weekly-end-date, or --tickers --start-date --end-date for walk-forward mode")

    checkpoint = args.checkpoint or _build_default_checkpoint_path(
        profile=args.profile,
        objective=args.objective,
        replay_input_paths=replay_input_paths,
        walk_forward_descriptor=walk_forward_descriptor,
    )
    guardrails = resolve_guardrails(
        profile_name=args.profile,
        objective=args.objective,
        replay_mode=replay_mode,
        raw_guardrails=args.guardrail or [],
    )
    stage_results = None
    if args.search_stage == "staged":
        coarse_grid = resolve_grid_params(
            grid_params=args.grid_params or [],
            preset_grid=args.preset_grid,
            profile_name=args.profile,
            search_stage="coarse",
        )
        coarse_space = ParamSpace(grid=coarse_grid)
        _enforce_max_combinations(coarse_space, args.max_combinations)
        coarse_checkpoint = _stage_checkpoint_path(checkpoint, "coarse")
        coarse_report = run_param_search(
            space=coarse_space,
            objective=objective,
            evaluator=evaluator,
            checkpoint_path=coarse_checkpoint,
            guardrails=guardrails or None,
        )
        coarse_best_params = _report_best_params(coarse_report)

        focused_grid = resolve_grid_params(
            grid_params=args.grid_params or [],
            preset_grid=args.preset_grid,
            profile_name=args.profile,
            search_stage="focused",
        )
        focused_grid = build_stage_grid(
            base_grid=focused_grid,
            search_stage="focused",
            focus_params=coarse_best_params,
        )
        space = ParamSpace(grid=focused_grid)
        _enforce_max_combinations(space, args.max_combinations)
        checkpoint = _stage_checkpoint_path(checkpoint, "focused")
        report = run_param_search(
            space=space,
            objective=objective,
            evaluator=evaluator,
            checkpoint_path=checkpoint,
            guardrails=guardrails or None,
        )
        stage_results = {
            "coarse": {
                "best_params": coarse_best_params,
                "best_score": _report_best_score(coarse_report),
                "checkpoint_path": coarse_checkpoint,
            },
            "focused": {
                "best_params": _report_best_params(report),
                "best_score": _report_best_score(report),
                "checkpoint_path": checkpoint,
            },
        }
        focus_source = coarse_checkpoint
    else:
        report = run_param_search(
            space=space,
            objective=objective,
            evaluator=evaluator,
            checkpoint_path=checkpoint,
            guardrails=guardrails or None,
        )

    md_path = save_search_report(report, args.output_md)
    json_path = save_search_payload(report, args.output_json)
    metadata = _build_search_metadata(
        search_stage=args.search_stage,
        guardrails=guardrails,
        focus_json=focus_source,
        checkpoint_path=checkpoint,
        stage_results=stage_results,
    )
    comparison_summary = None
    rollout_recommendation = None
    rollout_recommendation_details = None
    best_params = _report_best_params(report)
    if replay_mode and replay_input_paths and best_params is not None:
        comparison_summary = _build_replay_comparison_summary(
            replay_input_paths=replay_input_paths,
            base_profile=args.profile,
            best_params=best_params,
            next_high_hit_threshold=args.next_high_hit_threshold,
        )
        rollout_recommendation_details = _build_rollout_recommendation_payload(comparison_summary)
        rollout_recommendation = str(rollout_recommendation_details.get("action") or "hold")
    optimized_profile_manifest_publication = _build_optimized_profile_manifest_publication(
        objective=objective,
        replay_mode=replay_mode,
        replay_input_paths=replay_input_paths,
        best_params=best_params,
        rollout_recommendation=rollout_recommendation,
        profile_name=args.profile,
        source_path=json_path,
        manifest_path=REPORTS_DIR / "btst_latest_optimized_profile.json",
    )
    _persist_search_metadata(
        md_path=md_path,
        json_path=json_path,
        metadata=metadata,
        comparison_summary=comparison_summary,
        rollout_recommendation=rollout_recommendation,
        rollout_recommendation_details=rollout_recommendation_details,
        optimized_profile_manifest_publication=optimized_profile_manifest_publication,
    )
    print(format_search_report(report))
    if args.staged_mode == "ignition_stage1":
        print(_format_staged_ignition_summary(report))
    print(f"\nReport: {md_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
