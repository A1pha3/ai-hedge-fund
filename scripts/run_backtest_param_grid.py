"""CLI entry point for batch parameter-grid backtest comparison.

This is the user-facing wrapper around :mod:`src.backtesting.param_grid`.
It accepts the standard backtest CLI flags (tickers / dates / model / walk-
forward window) plus a ``--param-grid`` spec string and runs every
combination through :class:`BacktestEngine` in parallel.  Output is written
as CSV / Markdown / JSON, and a colourised comparison table is printed to
stdout.

Example::

    uv run python scripts/run_backtest_param_grid.py \\
        --tickers AAPL,MSFT \\
        --start-date 2026-01-01 --end-date 2026-04-30 \\
        --model-name gpt-4o --model-provider openai \\
        --param-grid "baseline_pct_threshold=2.0,3.0,4.0;baseline_top_n=5,10" \\
        --output data/reports/param_grid
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

# Make the project root importable when the script is executed via
# ``uv run python scripts/run_backtest_param_grid.py`` (where ``src/`` is
# not automatically on sys.path).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.backtesting.engine import BacktestEngine  # noqa: E402
from src.backtesting.param_grid import (  # noqa: E402
    DEFAULT_GRID_MAX_WORKERS,
    grid_combinations,
    GRID_ENV_VAR,
    ParamGridError,
    ParamGridReport,
    parse_param_grid,
    render_console_table,
    render_markdown_table,
    run_param_grid,
    save_csv_report,
    save_json_report,
    save_markdown_report,
)
from src.utils.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------


def _add_backtest_args(parser: argparse.ArgumentParser) -> None:
    """Attach the standard backtester flags to *parser*.

    These mirror ``src/backtesting/cli_helpers.build_backtest_parser`` but
    avoid pulling in the interactive questionary prompts — the grid runner
    is non-interactive by design.
    """
    parser.add_argument("--tickers", type=str, required=True, help="Comma-separated tickers (e.g. AAPL,MSFT)")
    parser.add_argument("--start-date", type=str, default=(datetime.now().replace(day=1)).strftime("%Y-%m-%d"))
    parser.add_argument("--end-date", type=str, default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument("--margin-requirement", type=float, default=0.0)
    parser.add_argument(
        "--mode",
        choices=["agent", "pipeline"],
        default="agent",
        help="Backtest execution mode (matches BacktestEngine backtest_mode)",
    )
    parser.add_argument(
        "--analysts",
        type=str,
        default=None,
        help="Comma-separated analyst ids.  Default: run all analysts.",
    )
    parser.add_argument("--model-name", type=str, required=True)
    parser.add_argument("--model-provider", type=str, required=True)
    parser.add_argument(
        "--ollama",
        action="store_true",
        help="Use the Ollama provider (sets model_provider=ollama if --model-provider is not supplied).",
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="If set, run walk-forward over the date range and use the per-window Sharpe / drawdown "
        "averages as the comparison metric.",
    )
    parser.add_argument("--train-months", type=int, default=2)
    parser.add_argument("--test-months", type=int, default=1)
    parser.add_argument("--step-months", type=int, default=1)
    parser.add_argument("--max-test-trading-days", type=int, default=None)
    parser.add_argument(
        "--window-mode",
        choices=["rolling", "expanding"],
        default="rolling",
    )
    parser.add_argument(
        "--walk-forward-preset",
        choices=["fast", "standard", "extended", "seasonal"],
        default=None,
    )


def _add_grid_args(parser: argparse.ArgumentParser) -> None:
    """Attach the parameter-grid specific flags."""
    parser.add_argument(
        "--param-grid",
        type=str,
        required=True,
        help='Grid spec: "key1=v1,v2;key2=v3,v4".  Each dimension expands into a list and the '
        "runner takes the cartesian product.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/param_grid"),
        help="Directory for CSV / Markdown / JSON outputs (default: data/reports/param_grid).",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help=f"Override the worker thread count.  Defaults to the {GRID_ENV_VAR} env var "
        f"({DEFAULT_GRID_MAX_WORKERS} if unset).",
    )
    parser.add_argument(
        "--sort-by",
        choices=["sharpe_ratio", "sortino_ratio", "win_rate", "total_return"],
        default="sharpe_ratio",
        help="Primary sort metric for the comparison table (default: sharpe_ratio).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the console comparison table (still writes the on-disk reports).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a backtest parameter grid in parallel and print a comparison table.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_backtest_args(parser)
    _add_grid_args(parser)
    return parser


# ---------------------------------------------------------------------------
# Evaluator: build a BacktestEngine per trial, capture key metrics
# ---------------------------------------------------------------------------


# Metric columns the runner cares about for the comparison table.  These
# must be a subset of ``src.backtesting.param_grid.COMPARISON_METRICS`` keys.
_METRIC_KEYS: tuple[str, ...] = (
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown",
    "win_rate",
    "total_return",
    "window_count",
)


def _resolve_analysts(args: argparse.Namespace) -> list[str] | None:
    """Resolve the --analysts flag (or fall back to ``None`` = all).

    Returning ``None`` matches :class:`BacktestEngine`'s convention: a
    ``None`` ``selected_analysts`` means "use every analyst registered in
    the analyst order".
    """
    if not args.analysts:
        return None
    return [item.strip() for item in args.analysts.split(",") if item.strip()]


def _compute_total_return(portfolio_values: Sequence[dict[str, Any]], logger_: logging.Logger) -> float | None:
    """Compute total return as a fraction (e.g. 0.05 == +5%%) from equity curve points.

    Returns ``None`` when the curve is empty or the start value is non-positive.
    """
    if not portfolio_values:
        return None
    try:
        start_value = float(portfolio_values[0]["Portfolio Value"])
        end_value = float(portfolio_values[-1]["Portfolio Value"])
    except (KeyError, TypeError, ValueError) as exc:
        logger_.debug("Could not derive total return from portfolio values: %s", exc)
        return None
    if start_value <= 0:
        return None
    return (end_value / start_value) - 1.0


def _summarize_walk_forward(args: argparse.Namespace, base_args: dict[str, Any]) -> dict[str, Any]:
    """Run walk-forward for a single trial and average the per-window metrics.

    The summary dict's numeric fields are compatible with the comparison
    table so :func:`run_param_grid` can render the trial without
    special-casing.
    """
    # Imports are deferred so unit tests can mock the engine without
    # paying for the heavy LangGraph import cost.
    from src.backtesting.walk_forward import (
        build_walk_forward_windows,
        run_walk_forward,
        summarize_walk_forward,
        WALK_FORWARD_PRESETS,
        WindowMode,
    )

    preset_kwargs: dict[str, Any] = {}
    if args.walk_forward_preset:
        preset_kwargs = {k: v for k, v in WALK_FORWARD_PRESETS[args.walk_forward_preset].items() if v is not None}

    overlap_ok = args.walk_forward_preset in ("extended",)
    windows = build_walk_forward_windows(
        args.start_date,
        args.end_date,
        train_months=preset_kwargs.get("train_months", args.train_months),
        test_months=preset_kwargs.get("test_months", args.test_months),
        step_months=preset_kwargs.get("step_months", args.step_months),
        max_test_trading_days=preset_kwargs.get("max_test_trading_days", args.max_test_trading_days),
        window_mode=WindowMode(args.window_mode),
        allow_overlapping_tests=overlap_ok,
    )

    from src.main import run_hedge_fund  # local import keeps the CLI light

    def _build_engine(test_start: str, test_end: str) -> BacktestEngine:
        return BacktestEngine(
            agent=run_hedge_fund,
            start_date=test_start,
            end_date=test_end,
            **base_args,
        )

    results = run_walk_forward(windows, _build_engine)
    summary = summarize_walk_forward(results)
    return {
        "sharpe_ratio": summary.get("avg_sharpe"),
        "sortino_ratio": summary.get("avg_sortino"),
        "max_drawdown": summary.get("avg_max_drawdown"),
        "win_rate": None,  # Walk-forward summaries don't surface a per-window win-rate average.
        "total_return": None,
        "window_count": summary.get("window_count"),
    }


def make_evaluator(args: argparse.Namespace) -> Any:
    """Return a thread-safe evaluator closure bound to *args*.

    The closure maps a ``params`` dict -> ``metrics`` dict.  It captures
    the resolved baseline CLI flags (tickers / model / mode / analysts)
    and overrides them with the per-trial grid values, so the trial loop
    can stay free of argparse.
    """
    from src.main import run_hedge_fund  # local import keeps the CLI light

    selected_analysts = _resolve_analysts(args)
    model_provider = "ollama" if args.ollama and not args.model_provider else args.model_provider

    # Keys that may be swept via the grid.  Anything else in *args* is
    # treated as a static base configuration.  This whitelist keeps
    # surprising mutations (e.g. swapping tickers mid-grid) out of reach.
    SWEEPABLE_KEYS: frozenset[str] = frozenset(
        {
            "baseline_pct_threshold",
            "baseline_top_n",
            "initial_capital",
            "margin_requirement",
        }
    )

    base_args: dict[str, Any] = {
        "agent": run_hedge_fund,
        "tickers": [t.strip() for t in args.tickers.split(",") if t.strip()],
        "initial_capital": args.initial_capital,
        "model_name": args.model_name,
        "model_provider": model_provider,
        "selected_analysts": selected_analysts,
        "initial_margin_requirement": args.margin_requirement,
        "backtest_mode": args.mode,
    }

    def _evaluator(params: dict[str, Any]) -> dict[str, Any]:
        trial_args = dict(base_args)
        for key, value in params.items():
            if key not in SWEEPABLE_KEYS:
                raise ParamGridError(
                    f"unsupported grid dimension {key!r}; allowed: {sorted(SWEEPABLE_KEYS)}"
                )
            # baseline_* dimensions only apply to pipeline-mode backtests;
            # in agent mode they're quietly ignored so the grid can be
            # shared between the two execution modes.
            if key.startswith("baseline_") and args.mode != "pipeline":
                continue
            if key == "initial_capital":
                trial_args["initial_capital"] = value
            elif key == "margin_requirement":
                trial_args["initial_margin_requirement"] = value
            else:
                trial_args[key] = value

        if args.walk_forward:
            return _summarize_walk_forward(args, trial_args)

        engine = BacktestEngine(
            start_date=args.start_date,
            end_date=args.end_date,
            **trial_args,
        )
        metrics = engine.run_backtest()
        portfolio_values = engine.get_portfolio_values()
        return {
            "sharpe_ratio": metrics.get("sharpe_ratio"),
            "sortino_ratio": metrics.get("sortino_ratio"),
            "max_drawdown": metrics.get("max_drawdown"),
            "win_rate": metrics.get("win_rate"),
            "total_return": _compute_total_return(portfolio_values, logger),
        }

    return _evaluator


# ---------------------------------------------------------------------------
# Output side
# ---------------------------------------------------------------------------


def _write_reports(report: ParamGridReport, output_dir: Path, sort_by: str) -> dict[str, Path]:
    """Persist the report in three formats; return a path map."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = {
        "csv": save_csv_report(report, output_dir / f"param_grid_{timestamp}.csv"),
        "md": save_markdown_report(report, output_dir / f"param_grid_{timestamp}.md", sort_by=sort_by),
        "json": save_json_report(report, output_dir / f"param_grid_{timestamp}.json", sort_by=sort_by),
    }
    return paths


def _print_summary(report: ParamGridReport, paths: dict[str, Path], sort_by: str) -> None:
    best = report.best_trial(sort_by)
    print(f"\nCompleted {report.completed}/{report.total_combinations} trials ({report.failed} failed).")
    if best is not None:
        print("Best trial (by " + sort_by + "):")
        for key, value in sorted(best.params.items()):
            print(f"  {key}={value}")
        for metric in ("sharpe_ratio", "sortino_ratio", "max_drawdown", "win_rate", "total_return"):
            value = best.metrics.get(metric)
            if value is not None:
                print(f"  {metric}={value}")
    for label, path in paths.items():
        print(f"{label.upper()} report: {path}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        grid = parse_param_grid(args.param_grid)
    except ParamGridError as exc:
        parser.error(str(exc))
        return 2  # unreachable; parser.error exits

    combinations = grid_combinations(grid)
    logger.info(
        "Parameter grid: %d dimensions, %d combinations.  sweepable_keys=%s",
        len(grid),
        len(combinations),
        sorted({"baseline_pct_threshold", "baseline_top_n", "initial_capital", "margin_requirement"}),
    )
    for index, params in enumerate(combinations):
        logger.info("Trial %d/%d: %s", index + 1, len(combinations), params)

    evaluator = make_evaluator(args)
    report = run_param_grid(grid=grid, evaluator=evaluator, max_workers=args.max_workers)

    paths = _write_reports(report, args.output, args.sort_by)
    _print_summary(report, paths, args.sort_by)

    if not args.quiet:
        print()
        print(render_console_table(report))
        print()
        print(render_markdown_table(report, sort_by=args.sort_by))

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    # Set a sane default for the LLM-side concurrency so per-trial backtests
    # don't oversubscribe the provider.  Users can still override via env.
    os.environ.setdefault("ANALYST_CONCURRENCY_LIMIT", str(DEFAULT_GRID_MAX_WORKERS))
    raise SystemExit(main())
