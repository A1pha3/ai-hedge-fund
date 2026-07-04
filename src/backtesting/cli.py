from __future__ import annotations

import os

from colorama import init

from src.backtesting.cli_helpers import (
    build_backtest_parser,
    parse_tickers,
    print_backtest_summary,
    print_default_model,
    resolve_model_selection,
    resolve_selected_analysts,
)
from src.main import run_hedge_fund
from src.utils.logging import get_logger

from .compare import (
    build_ab_comparison_payload,
    format_ab_comparison_report,
    run_ab_comparison_walk_forward,
    save_ab_comparison_payload,
    save_ab_comparison_report,
)
from .engine import BacktestEngine
from .walk_forward import (
    build_walk_forward_windows,
    run_walk_forward,
    summarize_walk_forward,
    WALK_FORWARD_PRESETS,
    WindowMode,
)

logger = get_logger(__name__)


def _run_ab_compare(args, tickers: list[str], selected_analysts: list[str], model_selection) -> int:
    checkpoint_path = None
    if args.report_json:
        checkpoint_path = str(os.path.splitext(args.report_json)[0] + ".checkpoint.json")
    elif args.report_file:
        checkpoint_path = str(os.path.splitext(args.report_file)[0] + ".checkpoint.json")
    results, summary = run_ab_comparison_walk_forward(
        tickers=tickers,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        model_name=model_selection.name,
        model_provider=model_selection.provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=args.margin_requirement,
        agent=run_hedge_fund,
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
        max_test_trading_days=args.max_test_trading_days,
        baseline_pct_threshold=args.baseline_pct_threshold,
        baseline_top_n=args.baseline_top_n,
        checkpoint_path=checkpoint_path,
        window_mode=WindowMode(args.window_mode),
        walk_forward_preset=args.walk_forward_preset,
    )
    report = format_ab_comparison_report(results, summary)
    payload = build_ab_comparison_payload(results, summary)
    report_path = save_ab_comparison_report(report, args.report_file)
    json_path = save_ab_comparison_payload(payload, args.report_json)
    print(report)
    print(f"\nReport saved to: {report_path}")
    print(f"JSON saved to: {json_path}")
    return 0


def _run_walk_forward_mode(args, build_engine) -> int:
    preset_kwargs = {}
    if args.walk_forward_preset:
        preset_kwargs = {k: v for k, v in WALK_FORWARD_PRESETS[args.walk_forward_preset].items() if v is not None}

    window_mode = WindowMode(args.window_mode)
    # ALPHA-005: "extended" preset has step < test → overlapping windows.
    # Allow overlap for known presets that were designed with it.
    overlap_ok = args.walk_forward_preset in ("extended",)
    windows = build_walk_forward_windows(
        args.start_date,
        args.end_date,
        train_months=preset_kwargs.get("train_months", args.train_months),
        test_months=preset_kwargs.get("test_months", args.test_months),
        step_months=preset_kwargs.get("step_months", args.step_months),
        max_test_trading_days=preset_kwargs.get("max_test_trading_days", args.max_test_trading_days),
        window_mode=window_mode,
        allow_overlapping_tests=overlap_ok,
    )
    results = run_walk_forward(windows, lambda window: build_engine(window.test_start, window.test_end))
    summary = summarize_walk_forward(results)
    print(f"Walk-Forward Windows: {summary['window_count']}")
    if summary["avg_sharpe"] is not None:
        print(f"Average Sharpe: {summary['avg_sharpe']:.2f}")
    if summary["avg_sortino"] is not None:
        print(f"Average Sortino: {summary['avg_sortino']:.2f}")
    if summary["avg_max_drawdown"] is not None:
        print(f"Average Max Drawdown: {abs(summary['avg_max_drawdown']):.2f}%")
    if summary["positive_sharpe_window_ratio"] is not None:
        print("Positive Sharpe Windows: " f"{int(summary['positive_sharpe_window_count'])}/{summary['window_count']} " f"({float(summary['positive_sharpe_window_ratio']):.0%})")
    if int(summary.get("zero_sharpe_window_count") or 0) > 0:
        print(f"Zero Sharpe Windows: {int(summary['zero_sharpe_window_count'])}")
    if summary["worst_sharpe"] is not None:
        print(f"Worst Window Sharpe: {summary['worst_sharpe']:.2f}")
    if summary["worst_max_drawdown"] is not None:
        print(f"Worst Window Max Drawdown: {abs(summary['worst_max_drawdown']):.2f}%")
    if summary.get("max_non_positive_sharpe_streak") is not None:
        print(f"Max Non-Positive Sharpe Streak: {int(summary['max_non_positive_sharpe_streak'])}")
    if summary.get("rollout_ready") is not None:
        print(f"Rollout Ready: {'YES' if bool(summary['rollout_ready']) else 'NO'}")
        rollout_blockers = [str(blocker) for blocker in list(summary.get("rollout_blockers") or []) if str(blocker or "").strip()]
        if rollout_blockers:
            print(f"Rollout Blockers: {', '.join(rollout_blockers)}")
    if "promotion_ready" in summary:
        print(f"Promotion Ready: {'YES' if summary['promotion_ready'] else 'NO'}")
    promotion_blockers = [str(item) for item in list(summary.get("promotion_blockers") or []) if str(item).strip()]
    if promotion_blockers:
        print(f"Promotion Blockers: {', '.join(promotion_blockers)}")
    # Finance-quant risk disclosure (gamma lens): walk-forward Sharpe/drawdown are
    # in-sample statistics over a finite window, not predictive guarantees. Echoing
    # the project-level disclaimer inline keeps users from over-reading the numbers.
    print("⚠ 回测/滚动验证为历史样本统计，不代表未来收益；实际交易还需计入滑点、流动性、政策与择时风险。")
    # R44 (gamma trust calibration): disclose the point-in-time (PIT) look-ahead
    # surface that has been hardened (R37-R41, R74) so users can calibrate how
    # much to trust the numbers. R42 is now closed by product decision: this
    # product does not research delisted names, so historical backtests keep the
    # current-listed A-share universe and disclose that sample boundary
    # explicitly. R74 extended ann_date PIT filtering from the fina_indicator
    # metrics path (R41) to the balancesheet/cashflow/income line_items path.
    print("ℹ 已加固的前瞻数据路径 (R37-R41, R74): 价格前复权 / A 股真实交易日历 / 宏观 as_of 过滤 / 财报 ann_date 过滤 (含三大报表 line_items)。" "当前股票池口径: 仅覆盖当前上市 A 股；退市标的不进入回测候选池。")
    return 0


def _run_param_grid_mode(args, model_selection) -> int:
    """Delegate the new ``--param-grid`` mode to the dedicated runner script.

    The actual grid logic lives in :mod:`scripts.run_backtest_param_grid` so
    the dependency surface (langgraph / backtester / LLM provider) is only
    paid for by callers that opt into batch mode.  We construct the same
    argv the script would receive from a shell so behaviour is identical
    regardless of entry point.
    """
    from pathlib import Path

    from scripts.run_backtest_param_grid import main as grid_main

    argv: list[str] = []
    tickers = parse_tickers(args.tickers)
    if not tickers:
        print("--tickers is required for --param-grid", flush=True)
        return 1
    argv.extend(["--tickers", ",".join(tickers)])
    argv.extend(["--start-date", str(args.start_date)])
    argv.extend(["--end-date", str(args.end_date)])
    argv.extend(["--initial-capital", str(args.initial_capital)])
    argv.extend(["--margin-requirement", str(args.margin_requirement)])
    argv.extend(["--mode", str(args.mode)])
    argv.extend(["--model-name", model_selection.name])
    argv.extend(["--model-provider", model_selection.provider])
    if args.walk_forward:
        argv.append("--walk-forward")
        if args.walk_forward_preset:
            argv.extend(["--walk-forward-preset", str(args.walk_forward_preset)])
        argv.extend(["--train-months", str(args.train_months)])
        argv.extend(["--test-months", str(args.test_months)])
        argv.extend(["--step-months", str(args.step_months)])
        if args.max_test_trading_days is not None:
            argv.extend(["--max-test-trading-days", str(args.max_test_trading_days)])
        argv.extend(["--window-mode", str(args.window_mode)])
    if args.analysts:
        argv.extend(["--analysts", str(args.analysts)])
    elif args.analysts_all:
        argv.append("--analysts-all")
    argv.extend(["--param-grid", str(args.param_grid)])
    if args.output:
        argv.extend(["--output", str(args.output)])
    if args.max_workers is not None:
        argv.extend(["--max-workers", str(args.max_workers)])
    argv.extend(["--sort-by", str(args.sort_by)])
    # Surface but ignore the param-grid destination path so downstream
    # tools that read ``args`` see the choice; the grid runner owns the
    # actual file writes.
    if args.output:
        Path(args.output).mkdir(parents=True, exist_ok=True)
    return int(grid_main(argv))


def main() -> int:
    parser = build_backtest_parser()
    args = parser.parse_args()
    init(autoreset=True)

    if args.show_default_model:
        print_default_model()
        return 0

    tickers = parse_tickers(args.tickers)
    selected_analysts = resolve_selected_analysts(args, logger)
    if selected_analysts is None:
        return 1
    model_selection = resolve_model_selection(args, logger)
    if model_selection is None:
        return 1

    def _build_engine(start_date: str, end_date: str) -> BacktestEngine:
        return BacktestEngine(
            agent=run_hedge_fund,
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_capital=args.initial_capital,
            model_name=model_selection.name,
            model_provider=model_selection.provider,
            selected_analysts=selected_analysts,
            initial_margin_requirement=args.margin_requirement,
            backtest_mode=args.mode,
        )

    if args.ab_compare:
        return _run_ab_compare(args, tickers, selected_analysts, model_selection)

    if args.walk_forward:
        return _run_walk_forward_mode(args, _build_engine)

    if args.param_grid:
        return _run_param_grid_mode(args, model_selection)

    engine = _build_engine(args.start_date, args.end_date)

    metrics = engine.run_backtest()
    values = engine.get_portfolio_values()
    print_backtest_summary(metrics, values, logger)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
