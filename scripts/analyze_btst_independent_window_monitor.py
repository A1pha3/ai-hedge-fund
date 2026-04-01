from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from scripts.analyze_short_trade_ticker_role_history import analyze_short_trade_ticker_role_history
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_TICKERS: tuple[str, ...] = ("001309", "300113", "600821")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_independent_window_monitor_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_independent_window_monitor_latest.md"
TARGET_WINDOW_COUNT = 2
WINDOW_KEY_PATTERN = re.compile(r"paper_trading_window_(\d{8})_(\d{8})")
LANE_CONFIG: dict[str, dict[str, str]] = {
    "001309": {
        "lane_id": "primary_roll_forward",
        "lane_label": "Primary Roll Forward",
        "target_state": "collect_second_window",
    },
    "300113": {
        "lane_id": "recurring_shadow_close_candidate",
        "lane_label": "Recurring Close Candidate",
        "target_state": "collect_second_independent_close_window",
    },
    "600821": {
        "lane_id": "recurring_intraday_control",
        "lane_label": "Recurring Intraday Control",
        "target_state": "collect_second_independent_intraday_window",
    },
}


def _extract_window_key(report_label: str) -> str:
    matched = WINDOW_KEY_PATTERN.search(str(report_label))
    if not matched:
        return str(report_label)
    return f"{matched.group(1)}_{matched.group(2)}"


def _is_short_trade_role(role: Any) -> bool:
    normalized = str(role or "")
    return normalized.startswith("short_trade_") or normalized.startswith("short_trade_boundary")


def _build_lane_row(summary: dict[str, Any], *, ticker: str) -> dict[str, Any]:
    config = LANE_CONFIG.get(ticker, {})
    observations = [dict(row or {}) for row in list(summary.get("observations") or [])]
    short_trade_rows = [row for row in observations if _is_short_trade_role(row.get("role"))]
    distinct_window_keys = sorted({_extract_window_key(str(row.get("report_label") or "")) for row in short_trade_rows})
    short_trade_trade_date_count = len(short_trade_rows)
    distinct_window_count = len(distinct_window_keys)
    missing_window_count = max(TARGET_WINDOW_COUNT - distinct_window_count, 0)

    if distinct_window_count >= TARGET_WINDOW_COUNT:
        readiness = "ready_for_reassessment"
        locality = "multi_window_stable"
        next_step = "re-run governance review with the newly accumulated independent-window evidence"
    elif short_trade_trade_date_count > 0:
        readiness = "await_new_independent_window_data"
        locality = "single_window_only"
        next_step = config.get("target_state") or "collect another independent window"
    else:
        readiness = "no_short_trade_window_evidence"
        locality = "no_evidence"
        next_step = "wait for the ticker to reappear in a short-trade lane before promoting the lane"

    return {
        "ticker": ticker,
        "lane_id": config.get("lane_id") or ticker,
        "lane_label": config.get("lane_label") or ticker,
        "readiness": readiness,
        "transition_locality": locality,
        "short_trade_trade_date_count": short_trade_trade_date_count,
        "distinct_window_count": distinct_window_count,
        "target_window_count": TARGET_WINDOW_COUNT,
        "missing_window_count": missing_window_count,
        "window_keys": distinct_window_keys,
        "first_short_trade_report_dir": summary.get("first_short_trade_report_dir"),
        "role_counts": dict(summary.get("role_counts") or {}),
        "next_step": next_step,
        "recommendation": summary.get("recommendation"),
    }


def render_btst_independent_window_monitor_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Independent Window Monitor")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- reports_root: {analysis['reports_root']}")
    lines.append(f"- report_dir_count: {analysis['report_dir_count']}")
    lines.append(f"- tickers: {analysis['tickers']}")
    lines.append("")
    lines.append("## Lane Readiness")
    for row in analysis["rows"]:
        lines.append(f"- {row['ticker']} {row['lane_label']}: readiness={row['readiness']}, distinct_window_count={row['distinct_window_count']}, missing_window_count={row['missing_window_count']}, transition_locality={row['transition_locality']}, next_step={row['next_step']}")
    if not analysis["rows"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- ready_lane_count: {analysis['ready_lane_count']}")
    lines.append(f"- waiting_lane_count: {analysis['waiting_lane_count']}")
    lines.append(f"- no_evidence_lane_count: {analysis['no_evidence_lane_count']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_btst_independent_window_monitor(
    reports_root: str | Path,
    *,
    tickers: list[str] | None = None,
    report_name_contains: str = "paper_trading_window",
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    monitored_tickers = [str(ticker).strip() for ticker in (tickers or list(DEFAULT_TICKERS)) if str(ticker).strip()]
    report_dirs = discover_report_dirs([resolved_reports_root], report_name_contains=report_name_contains)
    role_history = analyze_short_trade_ticker_role_history(report_dirs, tickers=monitored_tickers)
    summaries_by_ticker = {
        str(row.get("ticker") or ""): dict(row or {})
        for row in list(role_history.get("ticker_summaries") or [])
        if row.get("ticker")
    }
    rows = [_build_lane_row(summaries_by_ticker.get(ticker, {"ticker": ticker}), ticker=ticker) for ticker in monitored_tickers]
    ready_lane_count = sum(1 for row in rows if row["readiness"] == "ready_for_reassessment")
    waiting_lane_count = sum(1 for row in rows if row["readiness"] == "await_new_independent_window_data")
    no_evidence_lane_count = sum(1 for row in rows if row["readiness"] == "no_short_trade_window_evidence")

    if ready_lane_count > 0:
        recommendation = "At least one monitored lane has enough independent-window evidence to re-enter governance review."
    elif waiting_lane_count > 0:
        recommendation = "No monitored lane has closed the second-window gap yet; keep the current governance split and wait for new independent-window evidence."
    else:
        recommendation = "The monitored lanes do not currently appear in any short-trade window evidence; do not promote them until they re-enter the observed frontier."

    return {
        "reports_root": str(resolved_reports_root),
        "report_dir_count": len(report_dirs),
        "report_dirs": [str(path) for path in report_dirs],
        "tickers": monitored_tickers,
        "target_window_count": TARGET_WINDOW_COUNT,
        "ready_lane_count": ready_lane_count,
        "waiting_lane_count": waiting_lane_count,
        "no_evidence_lane_count": no_evidence_lane_count,
        "rows": rows,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor whether BTST focus lanes have accumulated a second independent short-trade window.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--report-name-contains", default="paper_trading_window")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_independent_window_monitor(
        args.reports_root,
        tickers=[token.strip() for token in str(args.tickers).split(",") if token.strip()],
        report_name_contains=str(args.report_name_contains or "paper_trading_window"),
    )

    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_independent_window_monitor_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()