from __future__ import annotations

import argparse
from pathlib import Path

from scripts.btst_report_utils import discover_report_dirs
from scripts.refresh_selection_artifacts_from_daily_events import rebuild_catalyst_theme_diagnostics_for_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild catalyst-theme diagnostics from frozen report artifacts.")
    parser.add_argument("input_paths", nargs="+", help="One or more paper trading report directories or report roots")
    parser.add_argument("--trade-date", default=None, help="Optional trade date in YYYY-MM-DD or YYYYMMDD format")
    parser.add_argument("--report-name-contains", default="paper_trading", help="When scanning a root directory, only include report directories whose names contain this fragment")
    parser.add_argument(
        "--use-selection-snapshot-baseline",
        action="store_true",
        help="Opt in to using selection_snapshot.json as the audit baseline instead of the frozen plan funnel diagnostics",
    )
    return parser.parse_args()


def _discover_unique_report_dirs(input_paths: list[str], *, report_name_contains: str) -> list[Path]:
    report_dirs: list[Path] = []
    for raw_input in input_paths:
        report_dirs.extend(discover_report_dirs(raw_input, report_name_contains=report_name_contains))
    seen: set[Path] = set()
    return [path for path in report_dirs if not (path in seen or seen.add(path))]


def main() -> None:
    args = parse_args()
    for report_dir in _discover_unique_report_dirs(args.input_paths, report_name_contains=args.report_name_contains):
        result = rebuild_catalyst_theme_diagnostics_for_report(
            report_dir,
            trade_date=args.trade_date,
            use_selection_snapshot_baseline=args.use_selection_snapshot_baseline,
        )
        print(f"report_dir={result['report_dir']}")
        for row in result["results"]:
            print(f"trade_date={row['trade_date']}")
            print(f"artifact_path={row['artifact_path']}")
            print(f"replay_universe_count={row['replay_universe_count']}")
            print(f"baseline_selected_tickers={','.join(row['baseline_selected_tickers'])}")
            print(f"rebuilt_selected_tickers={','.join(row['rebuilt_selected_tickers'])}")


if __name__ == "__main__":
    main()
