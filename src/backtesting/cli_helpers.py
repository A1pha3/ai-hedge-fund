from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime

import questionary
from colorama import Fore, Style
from dateutil.relativedelta import relativedelta

from src.llm.defaults import get_default_model_config
from src.llm.models import ModelProvider, OLLAMA_LLM_ORDER
from src.utils.analysts import ANALYST_ORDER
from src.utils.ollama import ensure_ollama_and_model


@dataclass(frozen=True)
class ModelSelection:
    name: str
    provider: str


def build_backtest_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run backtesting engine (modular)")
    parser.add_argument("--show-default-model", action="store_true", help="Print the currently resolved default model/provider from .env and exit")
    parser.add_argument("--tickers", type=str, required=False, help="Comma-separated tickers")
    parser.add_argument("--end-date", type=str, default=datetime.now().strftime("%Y-%m-%d"), help="End date YYYY-MM-DD")
    parser.add_argument("--start-date", type=str, default=(datetime.now() - relativedelta(months=1)).strftime("%Y-%m-%d"), help="Start date YYYY-MM-DD")
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--margin-requirement", type=float, default=0.0)
    parser.add_argument("--mode", choices=["agent", "pipeline"], default="agent", help="Backtest execution mode")
    parser.add_argument("--walk-forward", action="store_true", help="Run walk-forward validation")
    parser.add_argument("--ab-compare", action="store_true", help="Run Group A vs Group B walk-forward comparison")
    parser.add_argument("--train-months", type=int, default=2, help="Training window size in months for walk-forward")
    parser.add_argument("--test-months", type=int, default=1, help="Test window size in months for walk-forward")
    parser.add_argument("--step-months", type=int, default=1, help="Step size in months for walk-forward")
    parser.add_argument("--max-test-trading-days", type=int, default=None, help="Optional cap on real trading days inside each test window")
    parser.add_argument("--baseline-pct-threshold", type=float, default=3.0, help="Baseline daily gainers threshold")
    parser.add_argument("--baseline-top-n", type=int, default=10, help="Baseline top N gainers passed to multi-agent analysis")
    parser.add_argument("--report-file", type=str, default=None, help="Optional output path for generated markdown report")
    parser.add_argument("--report-json", type=str, default=None, help="Optional output path for generated JSON report")
    parser.add_argument("--model-name", type=str, default=None, help="Run non-interactively with an explicit model name")
    parser.add_argument("--model-provider", type=str, default=None, help="Run non-interactively with an explicit model provider")
    parser.add_argument("--analysts", type=str, required=False)
    parser.add_argument("--analysts-all", action="store_true")
    parser.add_argument("--ollama", action="store_true")
    return parser


def parse_tickers(raw_tickers: str | None) -> list[str]:
    return [ticker.strip() for ticker in raw_tickers.split(",")] if raw_tickers else []


def resolve_selected_analysts(args, logger) -> list[str] | None:
    if args.analysts_all:
        return [analyst[1] for analyst in ANALYST_ORDER]
    if args.analysts:
        return [analyst.strip() for analyst in args.analysts.split(",") if analyst.strip()]
    if args.ab_compare or args.walk_forward:
        return [analyst[1] for analyst in ANALYST_ORDER]

    choices = questionary.checkbox(
        "Use the Space bar to select/unselect analysts.",
        choices=[questionary.Choice(display, value=value) for display, value in ANALYST_ORDER],
        instruction="\n\nPress 'a' to toggle all.\n\nPress Enter when done to run the hedge fund.",
        validate=lambda selected: len(selected) > 0 or "You must select at least one analyst.",
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
        return None

    logger.info(f"Selected analysts: {', '.join(choice.title().replace('_', ' ') for choice in choices)}")
    print(f"\nSelected analysts: {', '.join(Fore.GREEN + choice.title().replace('_', ' ') + Style.RESET_ALL for choice in choices)}\n")
    return choices


def resolve_model_selection(args, logger) -> ModelSelection | None:
    if args.model_name and args.model_provider:
        logger.info(f"Using non-interactive model selection: {args.model_provider} / {args.model_name}")
        print(f"\nSelected {Fore.CYAN}{args.model_provider}{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{args.model_name}{Style.RESET_ALL}\n")
        return ModelSelection(name=args.model_name, provider=args.model_provider)

    if args.ollama:
        return _resolve_ollama_selection(logger)

    model_name, model_provider = get_default_model_config()
    logger.info(f"Selected {model_provider} model: {model_name}")
    print(f"\nSelected {Fore.CYAN}{model_provider}{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n")
    return ModelSelection(name=model_name, provider=model_provider)


def _resolve_ollama_selection(logger) -> ModelSelection | None:
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
        return None
    if model_name == "-":
        model_name = questionary.text("Enter the custom model name:").ask()
        if not model_name:
            logger.info("Interrupt received. Exiting...")
            print("\n\nInterrupt received. Exiting...")
            return None
    if not ensure_ollama_and_model(model_name):
        logger.error("Cannot proceed without Ollama and the selected model.")
        print(f"{Fore.RED}Cannot proceed without Ollama and the selected model.{Style.RESET_ALL}")
        return None

    logger.info(f"Selected Ollama model: {model_name}")
    print(f"\nSelected {Fore.CYAN}Ollama{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n")
    return ModelSelection(name=model_name, provider=ModelProvider.OLLAMA.value)


def print_default_model() -> None:
    default_model_name, default_model_provider = get_default_model_config()
    print(f"default_model_provider={default_model_provider}")
    print(f"default_model_name={default_model_name}")


def print_backtest_summary(metrics: dict, values: list[dict], logger) -> None:
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
        max_drawdown = abs(metrics["max_drawdown"]) if metrics["max_drawdown"] is not None else 0.0
        if metrics.get("max_drawdown_date"):
            logger.info(f"Max DD: {max_drawdown:.2f}% on {metrics['max_drawdown_date']}")
            print(f"Max DD: {max_drawdown:.2f}% on {metrics['max_drawdown_date']}")
        else:
            logger.info(f"Max DD: {max_drawdown:.2f}%")
            print(f"Max DD: {max_drawdown:.2f}%")
