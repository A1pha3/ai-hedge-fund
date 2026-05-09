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
    SearchReport,
)
from src.targets import get_short_trade_target_profile
from src.utils.logging import get_logger

logger = get_logger(__name__)

REPORTS_DIR = Path("data/reports")
PARTIAL_HORIZON_WEIGHT_PENALTY = 0.85
PARTIAL_T3_HORIZON_WEIGHT_PENALTY = 0.92


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


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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
                "t_plus_3_close_positive_rate": None,
                "t_plus_3_close_expectancy": None,
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
            "t_plus_3_close_positive_rate": [],
            "t_plus_3_close_expectancy": [],
            "downside_p10": [],
            "sample_weight": [],
        }
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
                "t_plus_3_close_positive_rate": None,
                "t_plus_3_close_expectancy": None,
                "downside_p10": None,
                "sample_weight": None,
                "window_coverage": 0.0,
                "window_count": 0,
                "source_coverage_pass_ratio": 0.0,
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
            "t_plus_3_close_positive_rate": avg_t_plus_3_close_positive_rate,
            "t_plus_3_close_expectancy": avg_t_plus_3_close_expectancy,
            "downside_p10": avg_downside_p10,
            "sample_weight": effective_sample_weight,
            "window_coverage": window_coverage,
            "window_count": window_count,
            "source_coverage_pass_ratio": source_coverage_pass_ratio,
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


def resolve_grid_params(*, grid_params: list[str], preset_grid: bool, profile_name: str, staged_mode: str | None = None) -> dict[str, list[Any]]:
    """Resolve grid parameters with optional preset and profile-specific extensions.

    Args:
        grid_params: Raw grid parameter strings to parse
        preset_grid: Whether to include base preset grid
        profile_name: Profile name for profile-specific grid extensions
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
    if preset_grid and profile_name == "event_catalyst_guarded":
        return {**MOMENTUM_OPTIMIZED_GRID, **EVENT_CATALYST_GRID, **resolved}
    if preset_grid and profile_name in ROUTED_BTST_COMMITTEE_PROFILES:
        return {**ROUTED_BTST_COMMITTEE_GRID, **resolved}
    if preset_grid:
        return {**MOMENTUM_OPTIMIZED_GRID, **resolved}
    return resolved


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
                staged_mode=args.staged_mode,
            )
        except ValueError as exc:
            parser.error(str(exc))
    else:
        parser.error("Specify --preset-grid or --grid-params")

    space = ParamSpace(grid=grid)
    logger.info("Grid size: %d combinations", space.size())

    objective = SearchObjective(args.objective)

    replay_input_paths: list[Path] | None = None
    walk_forward_descriptor: str | None = None
    if args.input or (args.reports_root and args.weekly_start_date and args.weekly_end_date):
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
    report = run_param_search(
        space=space,
        objective=objective,
        evaluator=evaluator,
        checkpoint_path=checkpoint,
    )

    md_path = save_search_report(report, args.output_md)
    json_path = save_search_payload(report, args.output_json)
    print(format_search_report(report))
    if args.staged_mode == "ignition_stage1":
        print(_format_staged_ignition_summary(report))
    print(f"\nReport: {md_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
