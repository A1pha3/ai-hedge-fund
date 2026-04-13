"""Optimize short-trade target profile parameters via grid search.

Uses replay-based multi-window analysis to evaluate parameter combinations.
Supports checkpointing for long-running searches.
"""
from __future__ import annotations

import argparse
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
            return {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None, "window_count": 0}

        total_metrics: dict[str, list[float]] = {"sharpe": [], "sortino": [], "max_dd": []}
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
                surface = dict(result.get("surface_summaries", {}).get("tradeable", {}))
                next_close_positive_rate = float(surface.get("next_close_positive_rate", 0) or 0)
                next_high_hit_rate = float(surface.get("next_high_hit_rate_at_threshold", 0) or 0)
                t_plus_2_median = float(surface.get("t_plus_2_close_return_median", 0) or 0)
                sharpe_proxy = next_close_positive_rate + next_high_hit_rate
                sortino_proxy = t_plus_2_median
                max_dd_proxy = -abs(float(surface.get("next_close_return_p10", 0) or 0))
                total_metrics["sharpe"].append(sharpe_proxy)
                total_metrics["sortino"].append(sortino_proxy)
                total_metrics["max_dd"].append(max_dd_proxy)
                window_count += 1
            except Exception as e:
                logger.warning("Trial failed for %s: %s", input_path, e)
                continue

        if window_count == 0:
            return {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None, "window_count": 0}

        avg_sharpe = sum(total_metrics["sharpe"]) / len(total_metrics["sharpe"]) if total_metrics["sharpe"] else None
        avg_sortino = sum(total_metrics["sortino"]) / len(total_metrics["sortino"]) if total_metrics["sortino"] else None
        avg_max_dd = sum(total_metrics["max_dd"]) / len(total_metrics["max_dd"]) if total_metrics["max_dd"] else None

        return {
            "sharpe_ratio": avg_sharpe,
            "sortino_ratio": avg_sortino,
            "max_drawdown": avg_max_dd,
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
    "select_threshold": [0.40, 0.42, 0.44, 0.46, 0.48],
    "near_miss_threshold": [0.28, 0.30, 0.32, 0.34, 0.36],
    "breakout_freshness_weight": [0.10, 0.14, 0.18],
    "trend_acceleration_weight": [0.20, 0.24, 0.28],
    "volume_expansion_quality_weight": [0.14, 0.16, 0.18, 0.20],
    "close_strength_weight": [0.10, 0.12, 0.14, 0.16],
    "stale_penalty_block_threshold": [0.76, 0.80, 0.82],
    "overhead_penalty_block_threshold": [0.72, 0.76, 0.78],
    "extension_penalty_block_threshold": [0.78, 0.80, 0.84],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize short-trade target profile parameters")
    parser.add_argument("--profile", default="momentum_optimized", help="Base profile name")
    parser.add_argument("--objective", choices=[o.value for o in SearchObjective], default="composite")
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

    if args.input:
        input_paths = [Path(p) for p in args.input]
        evaluator = _build_replay_evaluator(
            input_paths,
            base_profile=args.profile,
            next_high_hit_threshold=args.next_high_hit_threshold,
        )
    elif args.tickers and args.start_date and args.end_date:
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

    checkpoint = args.checkpoint or str(REPORTS_DIR / f"param_search_{args.profile}_checkpoint.json")
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
