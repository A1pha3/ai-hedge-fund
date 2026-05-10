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

from scripts.analyze_btst_weekly_validation import analyze_btst_weekly_validation
from src.backtesting.param_search import (
    format_search_report,
    ParamSpace,
    run_param_search,
    save_search_payload,
    save_search_report,
    SearchObjective,
)
from src.targets import get_short_trade_target_profile
from src.utils.logging import get_logger

logger = get_logger(__name__)

REPORTS_DIR = Path("data/reports")
PARTIAL_HORIZON_WEIGHT_PENALTY = 0.85
PARTIAL_T3_HORIZON_WEIGHT_PENALTY = 0.92
DEFAULT_BTST_REPLAY_GUARDRAILS: dict[str, float] = {
    "next_close_positive_rate": 0.54,
    "next_high_hit_rate": 0.56,
    "downside_p10": -0.06,
    "window_coverage": 0.60,
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
)


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


def _parse_guardrails(raw: list[str]) -> dict[str, float]:
    guardrails: dict[str, float] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"Invalid guardrail {item!r}; expected metric=floor")
        key, raw_value = item.split("=", 1)
        value = _safe_float(raw_value)
        if value is None:
            raise ValueError(f"Invalid guardrail floor for {key!r}: {raw_value!r}")
        guardrails[key.strip()] = float(value)
    return guardrails


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_guardrails(
    *,
    profile_name: str,
    objective: str,
    replay_mode: bool,
    raw_guardrails: list[str],
) -> dict[str, float]:
    resolved: dict[str, float] = {}
    if replay_mode and profile_name == "momentum_optimized" and objective == SearchObjective.BTST.value:
        resolved.update(DEFAULT_BTST_REPLAY_GUARDRAILS)
    resolved.update(_parse_guardrails(raw_guardrails))
    return resolved


def _resolve_distribution_stat(surface: dict[str, Any], distribution_key: str, stat_key: str) -> float | None:
    distribution = dict(surface.get(distribution_key) or {})
    return _safe_float(distribution.get(stat_key))


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
                "t_plus_3_close_positive_rate": None,
                "t_plus_3_close_expectancy": None,
                "downside_p10": None,
                "sample_weight": None,
                "window_coverage": 0.0,
                "window_count": 0,
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
            "t_plus_3_close_positive_rate": [],
            "t_plus_3_close_expectancy": [],
            "downside_p10": [],
            "sample_weight": [],
        }
        window_count = 0

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
                t_plus_3_close_positive_rate = _safe_float(primary_surface.get("t_plus_3_close_positive_rate"))
                t_plus_3_close_expectancy = _safe_float(primary_surface.get("t_plus_3_close_expectancy"))
                has_t_plus_2_horizon = t_plus_2_median is not None and t_plus_2_close_positive_rate is not None
                has_t_plus_3_horizon = t_plus_3_median is not None and t_plus_3_close_positive_rate is not None and t_plus_3_close_expectancy is not None

                if t_plus_2_median is None:
                    t_plus_2_median = _resolve_distribution_stat(primary_surface, "next_close_return_distribution", "median")
                if t_plus_2_close_positive_rate is None:
                    t_plus_2_close_positive_rate = next_close_positive_rate
                if t_plus_3_median is None:
                    t_plus_3_median = t_plus_2_median
                if t_plus_3_close_positive_rate is None:
                    t_plus_3_close_positive_rate = t_plus_2_close_positive_rate
                if t_plus_3_close_expectancy is None:
                    t_plus_3_close_expectancy = _safe_float(primary_surface.get("t_plus_2_close_expectancy"))
                if t_plus_3_close_expectancy is None:
                    t_plus_3_close_expectancy = next_close_expectancy

                if next_close_positive_rate is None or next_high_hit_rate is None or t_plus_2_median is None or t_plus_3_median is None or max_dd_proxy is None or next_close_expectancy is None or t_plus_2_close_positive_rate is None or t_plus_3_close_positive_rate is None or t_plus_3_close_expectancy is None:
                    logger.warning("Trial skipped due missing metrics for %s scope=%s", input_path, primary_scope)
                    continue

                next_day_count = int(primary_surface.get("next_day_available_count") or 0)
                closed_cycle_count = int(primary_surface.get("closed_cycle_count") or 0)
                next_day_weight = min(1.0, max(0.0, next_day_count / 10.0))
                closed_cycle_weight = min(1.0, max(0.0, closed_cycle_count / 6.0))
                sample_weight = min(next_day_weight, closed_cycle_weight)
                if not has_t_plus_2_horizon:
                    sample_weight *= PARTIAL_HORIZON_WEIGHT_PENALTY
                elif not has_t_plus_3_horizon:
                    sample_weight *= PARTIAL_T3_HORIZON_WEIGHT_PENALTY
                sharpe_proxy = (next_close_positive_rate + next_high_hit_rate) * sample_weight
                sortino_proxy = t_plus_2_median * sample_weight
                total_metrics["sharpe"].append(sharpe_proxy)
                total_metrics["sortino"].append(sortino_proxy)
                total_metrics["max_dd"].append(max_dd_proxy)
                total_metrics["next_close_positive_rate"].append(next_close_positive_rate)
                if next_close_payoff_ratio is not None:
                    total_metrics["next_close_payoff_ratio"].append(next_close_payoff_ratio)
                total_metrics["next_close_expectancy"].append(next_close_expectancy)
                total_metrics["next_high_hit_rate"].append(next_high_hit_rate)
                total_metrics["t_plus_2_close_positive_rate"].append(t_plus_2_close_positive_rate)
                total_metrics["t_plus_3_close_positive_rate"].append(t_plus_3_close_positive_rate)
                total_metrics["t_plus_3_close_expectancy"].append(t_plus_3_close_expectancy)
                total_metrics["downside_p10"].append(max_dd_proxy)
                total_metrics["sample_weight"].append(sample_weight)
                window_count += 1
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
                "t_plus_3_close_positive_rate": None,
                "t_plus_3_close_expectancy": None,
                "downside_p10": None,
                "sample_weight": None,
                "window_coverage": 0.0,
                "window_count": 0,
            }

        avg_sharpe = sum(total_metrics["sharpe"]) / len(total_metrics["sharpe"]) if total_metrics["sharpe"] else None
        avg_sortino = sum(total_metrics["sortino"]) / len(total_metrics["sortino"]) if total_metrics["sortino"] else None
        avg_max_dd = sum(total_metrics["max_dd"]) / len(total_metrics["max_dd"]) if total_metrics["max_dd"] else None
        avg_next_close_positive_rate = sum(total_metrics["next_close_positive_rate"]) / len(total_metrics["next_close_positive_rate"]) if total_metrics["next_close_positive_rate"] else None
        avg_next_close_payoff_ratio = sum(total_metrics["next_close_payoff_ratio"]) / len(total_metrics["next_close_payoff_ratio"]) if total_metrics["next_close_payoff_ratio"] else None
        avg_next_close_expectancy = sum(total_metrics["next_close_expectancy"]) / len(total_metrics["next_close_expectancy"]) if total_metrics["next_close_expectancy"] else None
        avg_next_high_hit_rate = sum(total_metrics["next_high_hit_rate"]) / len(total_metrics["next_high_hit_rate"]) if total_metrics["next_high_hit_rate"] else None
        avg_t_plus_2_close_positive_rate = sum(total_metrics["t_plus_2_close_positive_rate"]) / len(total_metrics["t_plus_2_close_positive_rate"]) if total_metrics["t_plus_2_close_positive_rate"] else None
        avg_t_plus_3_close_positive_rate = sum(total_metrics["t_plus_3_close_positive_rate"]) / len(total_metrics["t_plus_3_close_positive_rate"]) if total_metrics["t_plus_3_close_positive_rate"] else None
        avg_t_plus_3_close_expectancy = sum(total_metrics["t_plus_3_close_expectancy"]) / len(total_metrics["t_plus_3_close_expectancy"]) if total_metrics["t_plus_3_close_expectancy"] else None
        avg_downside_p10 = sum(total_metrics["downside_p10"]) / len(total_metrics["downside_p10"]) if total_metrics["downside_p10"] else None
        avg_sample_weight = sum(total_metrics["sample_weight"]) / len(total_metrics["sample_weight"]) if total_metrics["sample_weight"] else None
        window_coverage = float(window_count) / float(len(input_paths) or 1)
        effective_sample_weight = max(0.0, min(1.0, avg_sample_weight * window_coverage)) if avg_sample_weight is not None else None

        return {
            "sharpe_ratio": avg_sharpe,
            "sortino_ratio": avg_sortino,
            "max_drawdown": avg_max_dd,
            "next_close_positive_rate": avg_next_close_positive_rate,
            "next_close_payoff_ratio": avg_next_close_payoff_ratio,
            "next_close_expectancy": avg_next_close_expectancy,
            "next_high_hit_rate": avg_next_high_hit_rate,
            "t_plus_2_close_positive_rate": avg_t_plus_2_close_positive_rate,
            "t_plus_3_close_positive_rate": avg_t_plus_3_close_positive_rate,
            "t_plus_3_close_expectancy": avg_t_plus_3_close_expectancy,
            "downside_p10": avg_downside_p10,
            "sample_weight": effective_sample_weight,
            "window_coverage": window_coverage,
            "window_count": window_count,
        }

    return evaluator


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


def resolve_grid_params(*, grid_params: list[str], preset_grid: bool, profile_name: str, search_stage: str = "full") -> dict[str, list[Any]]:
    """Resolve grid parameters with optional preset and profile-specific extensions.

    Args:
        grid_params: Raw grid parameter strings to parse
        preset_grid: Whether to include base preset grid
        profile_name: Profile name for profile-specific grid extensions

    Returns:
        Merged grid dictionary with parsed params taking precedence
    """
    resolved = _parse_grid_params(grid_params)
    base_momentum_grid = MOMENTUM_OPTIMIZED_STAGE_PRESET_GRIDS.get(search_stage, MOMENTUM_OPTIMIZED_GRID)
    if preset_grid and profile_name == "event_catalyst_guarded":
        return {**base_momentum_grid, **EVENT_CATALYST_GRID, **resolved}
    if preset_grid and profile_name in ROUTED_BTST_COMMITTEE_PROFILES:
        return {**ROUTED_BTST_COMMITTEE_GRID, **resolved}
    if preset_grid:
        return {**base_momentum_grid, **resolved}
    return resolved


def _build_search_metadata(
    *,
    search_stage: str,
    guardrails: dict[str, float],
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


def _recommend_rollout_action(comparison_summary: dict[str, dict[str, Any]]) -> str:
    if not comparison_summary:
        return "hold"
    for entry in comparison_summary.values():
        for metric in COMPARISON_METRICS:
            delta = _safe_float(entry.get(f"{metric}_delta"))
            if delta is None or delta < 0:
                return "hold"
    return "promote"


def _persist_search_metadata(
    *,
    md_path: Path,
    json_path: Path,
    metadata: dict[str, Any],
    comparison_summary: dict[str, dict[str, Any]] | None = None,
    rollout_recommendation: str | None = None,
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
            metadata_lines.append(f"- `{key}`: {value}")
    md_block = "\n".join(metadata_lines)
    base_md_text = md_text.split("## Search Metadata", 1)[0].rstrip() if "## Search Metadata" in md_text else md_text.rstrip()
    md_sections = [base_md_text, md_block]
    if comparison_summary:
        comparison_lines = [
            "## Baseline Comparison",
            "",
            "| Baseline | Close+ Δ | High-hit Δ | Expectancy Δ | Downside P10 Δ | Coverage Δ |",
            "| --- | --- | --- | --- | --- | --- |",
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
        md_sections.append(f"Rollout Recommendation: **{rollout_recommendation}**")
    md_text = "\n\n".join(section for section in md_sections if section) + "\n"
    md_path.write_text(md_text, encoding="utf-8")

    payload = json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else {}
    payload["metadata"] = metadata
    if comparison_summary is not None:
        payload["comparison_summary"] = comparison_summary
    if rollout_recommendation is not None:
        payload["rollout_recommendation"] = rollout_recommendation
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


def _report_best_params(report: Any) -> dict[str, Any]:
    if isinstance(report, dict):
        params = report.get("best_params")
        return dict(params) if isinstance(params, dict) else {}
    params = getattr(report, "best_params", None)
    return dict(params) if isinstance(params, dict) else {}


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
    parser.add_argument("--output-json", default=None, help="Output JSON path")
    parser.add_argument("--output-md", default=None, help="Output Markdown path")
    parser.add_argument("--checkpoint", default=None, help="Checkpoint file for resume")
    parser.add_argument("--guardrail", action="append", default=None, help="Guardrail floor as metric=floor; may be repeated")
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

    if args.preset_grid or args.grid_params:
        grid = resolve_grid_params(
            grid_params=args.grid_params or [],
            preset_grid=args.preset_grid,
            profile_name=args.profile,
            search_stage=args.search_stage,
        )
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
        evaluator = _build_replay_evaluator(
            replay_input_paths,
            base_profile=args.profile,
            next_high_hit_threshold=args.next_high_hit_threshold,
        )
    elif args.tickers and args.start_date and args.end_date:
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
    best_params = _report_best_params(report)
    if replay_mode and replay_input_paths and best_params:
        comparison_summary = _build_replay_comparison_summary(
            replay_input_paths=replay_input_paths,
            base_profile=args.profile,
            best_params=best_params,
            next_high_hit_threshold=args.next_high_hit_threshold,
        )
        rollout_recommendation = _recommend_rollout_action(comparison_summary)
    _persist_search_metadata(
        md_path=md_path,
        json_path=json_path,
        metadata=metadata,
        comparison_summary=comparison_summary,
        rollout_recommendation=rollout_recommendation,
    )
    print(format_search_report(report))
    print(f"\nReport: {md_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
