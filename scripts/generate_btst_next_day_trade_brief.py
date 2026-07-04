from __future__ import annotations

import argparse
from pathlib import Path

from src.paper_trading.btst_reporting import (  # noqa: F401 — re-export for tests
    analyze_btst_next_day_trade_brief,
    generate_and_register_btst_followup_artifacts,
    generate_btst_next_day_trade_brief_artifacts,
    infer_next_trade_date,
    render_btst_next_day_trade_brief_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a BTST next-day trade brief from a paper trading report directory.")
    parser.add_argument("input_path", help="Paper trading report directory or selection_snapshot.json path")
    parser.add_argument("--trade-date", help="Trade date to load from selection_artifacts (defaults to latest available)")
    parser.add_argument("--next-trade-date", help="Next trading day label to include in the brief")
    parser.add_argument(
        "--register-followup",
        action="store_true",
        help=("Generate and register the full BTST follow-up bundle (brief + execution card + boards). " "This updates session_summary.json and *_latest aliases under the report directory. " "Only supported when input_path is a report directory; ignores --output-dir."),
    )
    parser.add_argument("--output-dir", default="data/reports", help="Directory where the brief artifacts will be written")
    return parser.parse_args()


def _infer_next_trade_date_from_input(input_path: Path, trade_date: str | None) -> str | None:
    if trade_date:
        return infer_next_trade_date(trade_date)
    analysis = analyze_btst_next_day_trade_brief(input_path=input_path)
    inferred_trade_date = analysis.get("trade_date")
    if inferred_trade_date:
        return infer_next_trade_date(inferred_trade_date)
    return None


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path)

    if args.register_followup:
        resolved_input = input_path.expanduser().resolve()
        if not resolved_input.is_dir():
            raise SystemExit("--register-followup requires input_path to be a report directory")
        result = generate_and_register_btst_followup_artifacts(
            report_dir=resolved_input,
            trade_date=args.trade_date,
            next_trade_date=args.next_trade_date,
        )
        print(f"report_dir={resolved_input}")
        print(f"btst_brief_json={result['brief_json']}")
        print(f"btst_brief_markdown={result['brief_markdown']}")
        print(f"btst_execution_card_json={result['execution_card_json']}")
        print(f"btst_execution_card_markdown={result['execution_card_markdown']}")
        return

    next_trade_date = args.next_trade_date or _infer_next_trade_date_from_input(input_path, args.trade_date)
    result = generate_btst_next_day_trade_brief_artifacts(
        input_path=input_path,
        output_dir=Path(args.output_dir),
        trade_date=args.trade_date,
        next_trade_date=next_trade_date,
    )
    print(f"Wrote BTST brief JSON: {result['json_path']}")
    print(f"Wrote BTST brief Markdown: {result['markdown_path']}")


if __name__ == "__main__":
    main()
