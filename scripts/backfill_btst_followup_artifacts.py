from __future__ import annotations

import argparse
from pathlib import Path

from scripts.btst_report_utils import discover_report_dirs as _discover_btst_report_dirs
from src.paper_trading.btst_reporting import generate_and_register_btst_followup_artifacts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill BTST brief and premarket execution card artifacts into existing report directories.")
    parser.add_argument("input_paths", nargs="+", help="One or more report directories or report root directories")
    parser.add_argument("--trade-date", help="Optional trade date override for single-report backfill")
    parser.add_argument("--next-trade-date", help="Optional next trade date override")
    parser.add_argument("--report-name-contains", default="paper_trading", help="When scanning a root directory, only include report directories whose names contain this fragment")
    return parser.parse_args()


def _discover_report_dirs(input_path: Path, report_name_contains: str) -> list[Path]:
    return _discover_btst_report_dirs(input_path, report_name_contains=report_name_contains)


def main() -> None:
    args = parse_args()
    report_dirs: list[Path] = []
    for raw_input in args.input_paths:
        report_dirs.extend(_discover_report_dirs(Path(raw_input), args.report_name_contains))

    seen: set[Path] = set()
    unique_report_dirs = [path for path in report_dirs if not (path in seen or seen.add(path))]
    if not unique_report_dirs:
        raise SystemExit("No report directories found for BTST follow-up artifact backfill.")

    for report_dir in unique_report_dirs:
        result = generate_and_register_btst_followup_artifacts(
            report_dir=report_dir,
            trade_date=args.trade_date,
            next_trade_date=args.next_trade_date,
        )
        print(f"report_dir={report_dir}")
        print(f"btst_brief_json={result['brief_json']}")
        print(f"btst_brief_markdown={result['brief_markdown']}")
        print(f"btst_execution_card_json={result['execution_card_json']}")
        print(f"btst_execution_card_markdown={result['execution_card_markdown']}")


if __name__ == "__main__":
    main()