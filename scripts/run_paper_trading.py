from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from src.paper_trading.runtime import run_paper_trading_session


def _default_output_dir(start_date: str, end_date: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("data/reports") / f"paper_trading_{start_date}_{end_date}_{timestamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a paper-trading session using the existing pipeline mode engine.")
    parser.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD format")
    parser.add_argument("--end-date", required=True, help="End date in YYYY-MM-DD format")
    parser.add_argument("--tickers", default="", help="Optional comma-separated tracking tickers")
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument("--model-name", default="gpt-4.1")
    parser.add_argument("--model-provider", default="OpenAI")
    parser.add_argument("--output-dir", default=None, help="Directory for daily events, timing logs, and session summary")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tickers = [ticker.strip() for ticker in args.tickers.split(",") if ticker.strip()]
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(args.start_date, args.end_date)
    artifacts = run_paper_trading_session(
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=output_dir,
        tickers=tickers,
        initial_capital=args.initial_capital,
        model_name=args.model_name,
        model_provider=args.model_provider,
    )
    print(f"paper_trading_output_dir={artifacts.output_dir}")
    print(f"paper_trading_daily_events={artifacts.daily_events_path}")
    print(f"paper_trading_timing_log={artifacts.timing_log_path}")
    print(f"paper_trading_summary={artifacts.summary_path}")


if __name__ == "__main__":
    main()