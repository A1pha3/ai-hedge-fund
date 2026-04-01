from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from scripts.generate_reports_manifest import generate_reports_manifest_artifacts
from scripts.model_selection import resolve_model_selection
from scripts.run_btst_nightly_control_tower import generate_btst_nightly_control_tower_artifacts
from src.paper_trading.btst_reporting import (
    generate_and_register_btst_followup_artifacts,
)
from src.paper_trading.runtime import run_paper_trading_session


def _default_output_dir(start_date: str, end_date: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("data/reports") / f"paper_trading_{start_date}_{end_date}_{timestamp}"


def generate_btst_followup_artifacts(report_dir: Path, trade_date: str, next_trade_date: str | None = None) -> dict[str, str] | None:
    refresh_reports_manifest(report_dir)
    result = generate_and_register_btst_followup_artifacts(report_dir=report_dir, trade_date=trade_date, next_trade_date=next_trade_date)
    return {
        "brief_json": result["brief_json"],
        "brief_markdown": result["brief_markdown"],
        "card_json": result["execution_card_json"],
        "card_markdown": result["execution_card_markdown"],
        "opening_card_json": result["opening_watch_card_json"],
        "opening_card_markdown": result["opening_watch_card_markdown"],
        "priority_board_json": result["priority_board_json"],
        "priority_board_markdown": result["priority_board_markdown"],
    }


def refresh_reports_manifest(report_dir: Path) -> dict[str, str] | None:
    resolved_report_dir = report_dir.expanduser().resolve()
    reports_root = resolved_report_dir.parent
    if reports_root.name != "reports":
        return None
    result = generate_reports_manifest_artifacts(reports_root=reports_root)
    return {
        "manifest_json": result["json_path"],
        "manifest_markdown": result["markdown_path"],
    }


def refresh_btst_nightly_control_tower(report_dir: Path) -> dict[str, str] | None:
    resolved_report_dir = report_dir.expanduser().resolve()
    reports_root = resolved_report_dir.parent
    if reports_root.name != "reports":
        return None
    result = generate_btst_nightly_control_tower_artifacts(reports_root=reports_root)
    return {
        "open_ready_delta_json": result["delta_json_path"],
        "open_ready_delta_markdown": result["delta_markdown_path"],
        "nightly_control_tower_json": result["json_path"],
        "nightly_control_tower_markdown": result["markdown_path"],
        "catalyst_theme_frontier_json": result.get("catalyst_theme_frontier_json"),
        "catalyst_theme_frontier_markdown": result.get("catalyst_theme_frontier_markdown"),
        "manifest_json": result["manifest_json"],
        "manifest_markdown": result["manifest_markdown"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a paper-trading session using the existing pipeline mode engine.")
    parser.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD format")
    parser.add_argument("--end-date", required=True, help="End date in YYYY-MM-DD format")
    parser.add_argument("--tickers", default="", help="Optional comma-separated tracking tickers")
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument("--model-name", default=None, help="Model name override; omitted means use the primary route detected from .env")
    parser.add_argument("--model-provider", default=None, help="Model provider override; omitted means use the primary route detected from .env")
    parser.add_argument(
        "--selection-target",
        default="research_only",
        choices=["research_only", "short_trade_only", "dual_target"],
        help="Selection target mode for the underlying daily pipeline",
    )
    parser.add_argument("--output-dir", default=None, help="Directory for daily events, timing logs, and session summary")
    parser.add_argument("--frozen-plan-source", default=None, help="Path to a historical daily_events.jsonl file whose current_plan records will be replayed")
    parser.add_argument("--cache-benchmark", action="store_true", help="Run a post-session cache benchmark and write benchmark artifacts into the output directory")
    parser.add_argument("--cache-benchmark-ticker", default=None, help="Ticker used for the post-session cache benchmark; defaults to the first tracked ticker")
    parser.add_argument("--cache-benchmark-clear-first", action="store_true", help="Clear the local cache before running the post-session benchmark; use with caution")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tickers = [ticker.strip() for ticker in args.tickers.split(",") if ticker.strip()]
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(args.start_date, args.end_date)
    resolved_model_name, resolved_model_provider = resolve_model_selection(args.model_name, args.model_provider)
    artifacts = run_paper_trading_session(
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=output_dir,
        tickers=tickers,
        initial_capital=args.initial_capital,
        model_name=resolved_model_name,
        model_provider=resolved_model_provider,
        frozen_plan_source=args.frozen_plan_source,
        selection_target=args.selection_target,
        cache_benchmark=args.cache_benchmark,
        cache_benchmark_ticker=args.cache_benchmark_ticker,
        cache_benchmark_clear_first=args.cache_benchmark_clear_first,
    )
    print(f"paper_trading_model_route={resolved_model_provider}:{resolved_model_name}")
    print(f"paper_trading_output_dir={artifacts.output_dir}")
    print(f"paper_trading_daily_events={artifacts.daily_events_path}")
    print(f"paper_trading_timing_log={artifacts.timing_log_path}")
    print(f"paper_trading_summary={artifacts.summary_path}")
    print(f"paper_trading_selection_target={args.selection_target}")
    if args.selection_target != "research_only":
        followup_artifacts = generate_btst_followup_artifacts(output_dir, args.end_date)
        print(f"paper_trading_btst_brief_json={followup_artifacts['brief_json']}")
        print(f"paper_trading_btst_brief_markdown={followup_artifacts['brief_markdown']}")
        print(f"paper_trading_btst_execution_card_json={followup_artifacts['card_json']}")
        print(f"paper_trading_btst_execution_card_markdown={followup_artifacts['card_markdown']}")
        print(f"paper_trading_btst_opening_watch_card_json={followup_artifacts['opening_card_json']}")
        print(f"paper_trading_btst_opening_watch_card_markdown={followup_artifacts['opening_card_markdown']}")
        print(f"paper_trading_btst_priority_board_json={followup_artifacts['priority_board_json']}")
        print(f"paper_trading_btst_priority_board_markdown={followup_artifacts['priority_board_markdown']}")
        nightly_control_tower_artifacts = refresh_btst_nightly_control_tower(output_dir)
        if nightly_control_tower_artifacts:
            print(f"paper_trading_btst_open_ready_delta_json={nightly_control_tower_artifacts['open_ready_delta_json']}")
            print(f"paper_trading_btst_open_ready_delta_markdown={nightly_control_tower_artifacts['open_ready_delta_markdown']}")
            print(f"paper_trading_btst_nightly_control_tower_json={nightly_control_tower_artifacts['nightly_control_tower_json']}")
            print(f"paper_trading_btst_nightly_control_tower_markdown={nightly_control_tower_artifacts['nightly_control_tower_markdown']}")
            if nightly_control_tower_artifacts.get("catalyst_theme_frontier_json"):
                print(f"paper_trading_catalyst_theme_frontier_json={nightly_control_tower_artifacts['catalyst_theme_frontier_json']}")
            if nightly_control_tower_artifacts.get("catalyst_theme_frontier_markdown"):
                print(f"paper_trading_catalyst_theme_frontier_markdown={nightly_control_tower_artifacts['catalyst_theme_frontier_markdown']}")
            print(f"paper_trading_report_manifest_json={nightly_control_tower_artifacts['manifest_json']}")
            print(f"paper_trading_report_manifest_markdown={nightly_control_tower_artifacts['manifest_markdown']}")
    if args.cache_benchmark:
        print(f"paper_trading_cache_benchmark=enabled")
    if args.frozen_plan_source:
        print(f"paper_trading_frozen_plan_source={Path(args.frozen_plan_source).resolve()}")


if __name__ == "__main__":
    main()