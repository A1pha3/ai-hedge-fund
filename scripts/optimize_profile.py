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

from src.backtesting.param_search import (
    ParamSpace,
    SearchObjective,
    format_search_report,
    run_param_search,
    save_search_payload,
    save_search_report,
)
from src.targets import get_short_trade_target_profile
from src.utils.logging import get_logger

logger = get_logger(__name__)

REPORTS_DIR = Path("data/reports")
PARTIAL_HORIZON_WEIGHT_PENALTY = 0.85


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
    grid: dict[str, list[Any]] = {}
    for item in raw:
        if "=" in item:
            key, values_str = item.split("=", 1)
            values = [float(v.strip()) if "." in v else int(v.strip()) if v.strip().isdigit() else v.strip() for v in values_str.split(",")]
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
                max_dd_proxy = _resolve_distribution_stat(primary_surface, "next_close_return_distribution", "p10")
                next_close_payoff_ratio = _safe_float(primary_surface.get("next_close_payoff_ratio"))
                next_close_expectancy = _safe_float(primary_surface.get("next_close_expectancy"))
                t_plus_2_close_positive_rate = _safe_float(primary_surface.get("t_plus_2_close_positive_rate"))
                has_t_plus_2_horizon = t_plus_2_median is not None and t_plus_2_close_positive_rate is not None

                if t_plus_2_median is None:
                    t_plus_2_median = _resolve_distribution_stat(primary_surface, "next_close_return_distribution", "median")
                if t_plus_2_close_positive_rate is None:
                    t_plus_2_close_positive_rate = next_close_positive_rate

                if (
                    next_close_positive_rate is None
                    or next_high_hit_rate is None
                    or t_plus_2_median is None
                    or max_dd_proxy is None
                    or next_close_expectancy is None
                    or t_plus_2_close_positive_rate is None
                ):
                    logger.warning("Trial skipped due missing metrics for %s scope=%s", input_path, primary_scope)
                    continue

                next_day_count = int(primary_surface.get("next_day_available_count") or 0)
                closed_cycle_count = int(primary_surface.get("closed_cycle_count") or 0)
                next_day_weight = min(1.0, max(0.0, next_day_count / 10.0))
                closed_cycle_weight = min(1.0, max(0.0, closed_cycle_count / 6.0))
                sample_weight = min(next_day_weight, closed_cycle_weight)
                if not has_t_plus_2_horizon:
                    sample_weight *= PARTIAL_HORIZON_WEIGHT_PENALTY
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
                "downside_p10": None,
                "sample_weight": None,
                "window_coverage": 0.0,
                "window_count": 0,
            }

        avg_sharpe = sum(total_metrics["sharpe"]) / len(total_metrics["sharpe"]) if total_metrics["sharpe"] else None
        avg_sortino = sum(total_metrics["sortino"]) / len(total_metrics["sortino"]) if total_metrics["sortino"] else None
        avg_max_dd = sum(total_metrics["max_dd"]) / len(total_metrics["max_dd"]) if total_metrics["max_dd"] else None
        avg_next_close_positive_rate = (
            sum(total_metrics["next_close_positive_rate"]) / len(total_metrics["next_close_positive_rate"]) if total_metrics["next_close_positive_rate"] else None
        )
        avg_next_close_payoff_ratio = (
            sum(total_metrics["next_close_payoff_ratio"]) / len(total_metrics["next_close_payoff_ratio"]) if total_metrics["next_close_payoff_ratio"] else None
        )
        avg_next_close_expectancy = (
            sum(total_metrics["next_close_expectancy"]) / len(total_metrics["next_close_expectancy"]) if total_metrics["next_close_expectancy"] else None
        )
        avg_next_high_hit_rate = sum(total_metrics["next_high_hit_rate"]) / len(total_metrics["next_high_hit_rate"]) if total_metrics["next_high_hit_rate"] else None
        avg_t_plus_2_close_positive_rate = (
            sum(total_metrics["t_plus_2_close_positive_rate"]) / len(total_metrics["t_plus_2_close_positive_rate"]) if total_metrics["t_plus_2_close_positive_rate"] else None
        )
        avg_downside_p10 = sum(total_metrics["downside_p10"]) / len(total_metrics["downside_p10"]) if total_metrics["downside_p10"] else None
        avg_sample_weight = sum(total_metrics["sample_weight"]) / len(total_metrics["sample_weight"]) if total_metrics["sample_weight"] else None
        window_coverage = float(window_count) / float(len(input_paths) or 1)
        effective_sample_weight = (
            max(0.0, min(1.0, avg_sample_weight * window_coverage))
            if avg_sample_weight is not None
            else None
        )

        return {
            "sharpe_ratio": avg_sharpe,
            "sortino_ratio": avg_sortino,
            "max_drawdown": avg_max_dd,
            "next_close_positive_rate": avg_next_close_positive_rate,
            "next_close_payoff_ratio": avg_next_close_payoff_ratio,
            "next_close_expectancy": avg_next_close_expectancy,
            "next_high_hit_rate": avg_next_high_hit_rate,
            "t_plus_2_close_positive_rate": avg_t_plus_2_close_positive_rate,
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
    from src.backtesting.walk_forward import WindowMode, build_walk_forward_windows, run_walk_forward, summarize_walk_forward
    from src.main import run_hedge_fund
    from src.targets.profiles import use_short_trade_target_profile

    def evaluator(params: dict[str, Any]) -> dict[str, float | None]:
        windows = build_walk_forward_windows(
            start_date, end_date,
            train_months=train_months, test_months=test_months, step_months=step_months,
            window_mode=WindowMode.ROLLING,
        )
        with use_short_trade_target_profile(profile_name=base_profile, overrides=params):
            results = run_walk_forward(windows, lambda w: BacktestEngine(
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
            ))
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize short-trade target profile parameters")
    parser.add_argument("--profile", default="momentum_optimized", help="Base profile name")
    parser.add_argument("--objective", choices=[o.value for o in SearchObjective], default="edge")
    parser.add_argument("--input", nargs="+", help="Replay input JSON paths (replay mode)")
    parser.add_argument("--grid-params", nargs="+", help="Grid params as key=val1,val2 or path/to.json")
    parser.add_argument("--preset-grid", action="store_true", help="Use built-in momentum_optimized grid")
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
    args = parser.parse_args()

    get_short_trade_target_profile(args.profile)

    if args.preset_grid:
        grid = MOMENTUM_OPTIMIZED_GRID
    elif args.grid_params:
        grid = _parse_grid_params(args.grid_params)
    else:
        parser.error("Specify --preset-grid or --grid-params")

    space = ParamSpace(grid=grid)
    logger.info("Grid size: %d combinations", space.size())

    objective = SearchObjective(args.objective)

    replay_input_paths: list[Path] | None = None
    walk_forward_descriptor: str | None = None
    if args.input:
        input_paths = [Path(p) for p in args.input]
        replay_input_paths = input_paths
        evaluator = _build_replay_evaluator(
            input_paths,
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
        parser.error("Specify --input for replay mode, or --tickers --start-date --end-date for walk-forward mode")

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
    print(f"\nReport: {md_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
