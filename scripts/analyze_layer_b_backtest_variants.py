from __future__ import annotations

import argparse
from pathlib import Path

from src.backtesting.rule_variant_compare import build_rule_variants, run_rule_variant_backtests, save_rule_variant_backtests
from src.utils.analysts import ANALYST_ORDER


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pipeline backtests for Layer B rule variants")
    parser.add_argument("--start-date", required=True, help="Backtest start date in YYYY-MM-DD format")
    parser.add_argument("--end-date", required=True, help="Backtest end date in YYYY-MM-DD format")
    parser.add_argument("--model-name", required=True, help="Model name for fast/precise pipeline execution")
    parser.add_argument("--model-provider", required=True, help="Model provider for fast/precise pipeline execution")
    parser.add_argument("--initial-capital", type=float, default=100000.0, help="Initial portfolio capital")
    parser.add_argument(
        "--variants",
        type=str,
        default="baseline,profitability_inactive,neutral_mean_reversion_guarded_033_no_hard_cliff",
        help="Comma-separated variant names",
    )
    parser.add_argument("--analysts", type=str, default=None, help="Comma-separated analysts list")
    parser.add_argument("--analysts-all", action="store_true", help="Use all analysts")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory for timing logs and checkpoints")
    args = parser.parse_args()

    if args.analysts_all:
        selected_analysts = [value for _, value in ANALYST_ORDER]
    elif args.analysts:
        selected_analysts = [item.strip() for item in args.analysts.split(",") if item.strip()]
    else:
        selected_analysts = [value for _, value in ANALYST_ORDER]

    variants = build_rule_variants([item.strip() for item in args.variants.split(",") if item.strip()])
    report = run_rule_variant_backtests(
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        model_name=args.model_name,
        model_provider=args.model_provider,
        selected_analysts=selected_analysts,
        variants=variants,
        output_dir=args.output_dir,
    )

    output_path = args.output or str(
        (Path(args.output_dir) if args.output_dir else Path(__file__).resolve().parents[1] / "data" / "reports").resolve()
        / f"layer_b_backtest_variants_{args.start_date.replace('-', '')}_{args.end_date.replace('-', '')}.json"
    )
    saved_path = save_rule_variant_backtests(report, output_path)

    print(f"Saved backtest variant report to: {saved_path}")
    for variant_name, payload in report["comparisons"].items():
        portfolio_summary = payload["portfolio_summary"]
        timing_summary = payload["timing_summary"]
        total_return = portfolio_summary.get("total_return_pct")
        layer_b_days = timing_summary.get("nonzero_layer_b_days")
        buy_days = timing_summary.get("nonzero_buy_order_days")
        print(
            f"{variant_name}: return={total_return if total_return is not None else 'n/a'} "
            f"nonzero_layer_b_days={layer_b_days} nonzero_buy_order_days={buy_days}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())