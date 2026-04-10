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

from .compare import build_ab_comparison_payload, format_ab_comparison_report, run_ab_comparison_walk_forward, save_ab_comparison_payload, save_ab_comparison_report
from .engine import BacktestEngine
from .walk_forward import build_walk_forward_windows, run_walk_forward, summarize_walk_forward

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
    windows = build_walk_forward_windows(
        args.start_date,
        args.end_date,
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
        max_test_trading_days=args.max_test_trading_days,
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
    return 0


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

    engine = _build_engine(args.start_date, args.end_date)

    metrics = engine.run_backtest()
    values = engine.get_portfolio_values()
    print_backtest_summary(metrics, values, logger)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
