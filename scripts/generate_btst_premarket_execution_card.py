from __future__ import annotations

import argparse
from pathlib import Path

from src.paper_trading.btst_reporting import (
    generate_btst_premarket_execution_card_artifacts,
    infer_next_trade_date,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a BTST premarket execution card from a paper trading report directory or brief JSON.")
    parser.add_argument("input_path", help="Paper trading report directory, selection_snapshot.json, or brief JSON path")
    parser.add_argument("--trade-date", help="Trade date to load from selection_artifacts (defaults to latest available)")
    parser.add_argument("--next-trade-date", help="Next trading day label to include in the execution card")
    parser.add_argument("--output-dir", default="data/reports", help="Directory where the execution card artifacts will be written")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    next_trade_date = args.next_trade_date or infer_next_trade_date(args.trade_date)
    result = generate_btst_premarket_execution_card_artifacts(
        input_path=Path(args.input_path),
        output_dir=Path(args.output_dir),
        trade_date=args.trade_date,
        next_trade_date=next_trade_date,
    )
    print(f"Wrote BTST premarket execution card JSON: {result['json_path']}")
    print(f"Wrote BTST premarket execution card Markdown: {result['markdown_path']}")


if __name__ == "__main__":
    main()