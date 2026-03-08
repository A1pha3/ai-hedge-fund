from __future__ import annotations

import argparse
import sys
from datetime import datetime
import os

import questionary
from colorama import Fore, init, Style
from dateutil.relativedelta import relativedelta

from src.llm.models import get_model_info, LLM_ORDER, ModelProvider, OLLAMA_LLM_ORDER
from src.main import run_hedge_fund
from src.utils.analysts import ANALYST_ORDER
from src.utils.logging import get_logger
from src.utils.ollama import ensure_ollama_and_model

from .compare import build_ab_comparison_payload, format_ab_comparison_report, run_ab_comparison_walk_forward, save_ab_comparison_payload, save_ab_comparison_report
from .engine import BacktestEngine
from .walk_forward import build_walk_forward_windows, run_walk_forward, summarize_walk_forward

logger = get_logger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run backtesting engine (modular)")
    parser.add_argument("--tickers", type=str, required=False, help="Comma-separated tickers")
    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date YYYY-MM-DD",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=(datetime.now() - relativedelta(months=1)).strftime("%Y-%m-%d"),
        help="Start date YYYY-MM-DD",
    )
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--margin-requirement", type=float, default=0.0)
    parser.add_argument("--mode", choices=["agent", "pipeline"], default="agent", help="Backtest execution mode")
    parser.add_argument("--walk-forward", action="store_true", help="Run walk-forward validation")
    parser.add_argument("--ab-compare", action="store_true", help="Run Group A vs Group B walk-forward comparison")
    parser.add_argument("--train-months", type=int, default=2, help="Training window size in months for walk-forward")
    parser.add_argument("--test-months", type=int, default=1, help="Test window size in months for walk-forward")
    parser.add_argument("--step-months", type=int, default=1, help="Step size in months for walk-forward")
    parser.add_argument("--baseline-pct-threshold", type=float, default=3.0, help="Baseline daily gainers threshold")
    parser.add_argument("--baseline-top-n", type=int, default=10, help="Baseline top N gainers passed to multi-agent analysis")
    parser.add_argument("--report-file", type=str, default=None, help="Optional output path for generated markdown report")
    parser.add_argument("--report-json", type=str, default=None, help="Optional output path for generated JSON report")
    parser.add_argument("--model-name", type=str, default=None, help="Run non-interactively with an explicit model name")
    parser.add_argument("--model-provider", type=str, default=None, help="Run non-interactively with an explicit model provider")
    parser.add_argument("--analysts", type=str, required=False)
    parser.add_argument("--analysts-all", action="store_true")
    parser.add_argument("--ollama", action="store_true")

    args = parser.parse_args()
    init(autoreset=True)

    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else []

    # Analysts selection is simplified; no interactive prompts here
    if args.analysts_all:
        selected_analysts = [a[1] for a in ANALYST_ORDER]
    elif args.analysts:
        selected_analysts = [a.strip() for a in args.analysts.split(",") if a.strip()]
    elif args.ab_compare or args.walk_forward:
        selected_analysts = [a[1] for a in ANALYST_ORDER]
    else:
        # Interactive analyst selection (same as legacy backtester)
        choices = questionary.checkbox(
            "Use the Space bar to select/unselect analysts.",
            choices=[questionary.Choice(display, value=value) for display, value in ANALYST_ORDER],
            instruction="\n\nPress 'a' to toggle all.\n\nPress Enter when done to run the hedge fund.",
            validate=lambda x: len(x) > 0 or "You must select at least one analyst.",
            style=questionary.Style(
                [
                    ("checkbox-selected", "fg:green"),
                    ("selected", "fg:green noinherit"),
                    ("highlighted", "noinherit"),
                    ("pointer", "noinherit"),
                ]
            ),
        ).ask()
        if not choices:
            logger.info("Interrupt received. Exiting...")
            print("\n\nInterrupt received. Exiting...")
            return 1
        selected_analysts = choices
        logger.info(f"Selected analysts: {', '.join(choice.title().replace('_', ' ') for choice in choices)}")
        print(f"\nSelected analysts: " f"{', '.join(Fore.GREEN + choice.title().replace('_', ' ') + Style.RESET_ALL for choice in choices)}\n")

    # Model selection simplified: default to first ordered model or Ollama flag
    if args.model_name and args.model_provider:
        model_name = args.model_name
        model_provider = args.model_provider
        logger.info(f"Using non-interactive model selection: {model_provider} / {model_name}")
        print(f"\nSelected {Fore.CYAN}{model_provider}{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n")
    elif args.ollama:
        logger.info("Using Ollama for local LLM inference.")
        print(f"{Fore.CYAN}Using Ollama for local LLM inference.{Style.RESET_ALL}")
        model_name = questionary.select(
            "Select your Ollama model:",
            choices=[questionary.Choice(display, value=value) for display, value, _ in OLLAMA_LLM_ORDER],
            style=questionary.Style(
                [
                    ("selected", "fg:green bold"),
                    ("pointer", "fg:green bold"),
                    ("highlighted", "fg:green"),
                    ("answer", "fg:green bold"),
                ]
            ),
        ).ask()
        if not model_name:
            logger.info("Interrupt received. Exiting...")
            print("\n\nInterrupt received. Exiting...")
            return 1
        if model_name == "-":
            model_name = questionary.text("Enter the custom model name:").ask()
            if not model_name:
                logger.info("Interrupt received. Exiting...")
                print("\n\nInterrupt received. Exiting...")
                return 1
        if not ensure_ollama_and_model(model_name):
            logger.error("Cannot proceed without Ollama and the selected model.")
            print(f"{Fore.RED}Cannot proceed without Ollama and the selected model.{Style.RESET_ALL}")
            return 1
        model_provider = ModelProvider.OLLAMA.value
        logger.info(f"Selected Ollama model: {model_name}")
        print(f"\nSelected {Fore.CYAN}Ollama{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n")
    else:
        model_choice = questionary.select(
            "Select your LLM model:",
            choices=[questionary.Choice(display, value=(name, provider)) for display, name, provider in LLM_ORDER],
            style=questionary.Style(
                [
                    ("selected", "fg:green bold"),
                    ("pointer", "fg:green bold"),
                    ("highlighted", "fg:green"),
                    ("answer", "fg:green bold"),
                ]
            ),
        ).ask()
        if not model_choice:
            logger.info("Interrupt received. Exiting...")
            print("\n\nInterrupt received. Exiting...")
            return 1
        model_name, model_provider = model_choice
        model_info = get_model_info(model_name, model_provider)
        if model_info and model_info.is_custom():
            model_name = questionary.text("Enter the custom model name:").ask()
            if not model_name:
                logger.info("Interrupt received. Exiting...")
                print("\n\nInterrupt received. Exiting...")
                return 1
        logger.info(f"Selected {model_provider} model: {model_name}")
        print(f"\nSelected {Fore.CYAN}{model_provider}{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n")

    def _build_engine(start_date: str, end_date: str) -> BacktestEngine:
        return BacktestEngine(
            agent=run_hedge_fund,
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_capital=args.initial_capital,
            model_name=model_name,
            model_provider=model_provider,
            selected_analysts=selected_analysts,
            initial_margin_requirement=args.margin_requirement,
            backtest_mode=args.mode,
        )

    if args.ab_compare:
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
            model_name=model_name,
            model_provider=model_provider,
            selected_analysts=selected_analysts,
            initial_margin_requirement=args.margin_requirement,
            agent=run_hedge_fund,
            train_months=args.train_months,
            test_months=args.test_months,
            step_months=args.step_months,
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

    if args.walk_forward:
        windows = build_walk_forward_windows(
            args.start_date,
            args.end_date,
            train_months=args.train_months,
            test_months=args.test_months,
            step_months=args.step_months,
        )
        results = run_walk_forward(
            windows,
            lambda window: _build_engine(window.test_start, window.test_end),
        )
        summary = summarize_walk_forward(results)
        print(f"Walk-Forward Windows: {summary['window_count']}")
        if summary["avg_sharpe"] is not None:
            print(f"Average Sharpe: {summary['avg_sharpe']:.2f}")
        if summary["avg_sortino"] is not None:
            print(f"Average Sortino: {summary['avg_sortino']:.2f}")
        if summary["avg_max_drawdown"] is not None:
            print(f"Average Max Drawdown: {abs(summary['avg_max_drawdown']):.2f}%")
        return 0

    engine = _build_engine(args.start_date, args.end_date)

    metrics = engine.run_backtest()
    values = engine.get_portfolio_values()

    # Minimal terminal output (no plots)
    if values:
        logger.info("ENGINE RUN COMPLETE")
        print(f"\n{Fore.WHITE}{Style.BRIGHT}ENGINE RUN COMPLETE{Style.RESET_ALL}")
        last_value = values[-1]["Portfolio Value"]
        start_value = values[0]["Portfolio Value"]
        total_return = (last_value / start_value - 1.0) * 100.0 if start_value else 0.0
        logger.info(f"Total Return: {total_return:.2f}%")
        print(f"Total Return: {Fore.GREEN if total_return >= 0 else Fore.RED}{total_return:.2f}%{Style.RESET_ALL}")
    if metrics.get("sharpe_ratio") is not None:
        logger.info(f"Sharpe: {metrics['sharpe_ratio']:.2f}")
        print(f"Sharpe: {metrics['sharpe_ratio']:.2f}")
    if metrics.get("sortino_ratio") is not None:
        logger.info(f"Sortino: {metrics['sortino_ratio']:.2f}")
        print(f"Sortino: {metrics['sortino_ratio']:.2f}")
    if metrics.get("max_drawdown") is not None:
        md = abs(metrics["max_drawdown"]) if metrics["max_drawdown"] is not None else 0.0
        if metrics.get("max_drawdown_date"):
            logger.info(f"Max DD: {md:.2f}% on {metrics['max_drawdown_date']}")
            print(f"Max DD: {md:.2f}% on {metrics['max_drawdown_date']}")
        else:
            logger.info(f"Max DD: {md:.2f}%")
            print(f"Max DD: {md:.2f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
