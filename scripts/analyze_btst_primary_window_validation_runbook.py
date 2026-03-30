from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_short_trade_ticker_role_history import analyze_short_trade_ticker_role_history


REPORTS_DIR = Path("data/reports")
DEFAULT_CANDIDATE_REPORT_PATH = REPORTS_DIR / "multi_window_short_trade_role_candidates_20260329.json"
DEFAULT_PRIMARY_ROLL_FORWARD_PATH = REPORTS_DIR / "p4_primary_roll_forward_validation_001309_20260330.json"
DEFAULT_PRIMARY_WINDOW_GAP_PATH = REPORTS_DIR / "p6_primary_window_gap_001309_20260330.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p7_primary_window_validation_runbook_001309_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p7_primary_window_validation_runbook_001309_20260330.md"

WINDOW_KEY_PATTERN = re.compile(r"paper_trading_window_(\d{8})_(\d{8})")


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _extract_window_key(report_label: str) -> str:
    matched = WINDOW_KEY_PATTERN.search(str(report_label or ""))
    if not matched:
        return str(report_label or "")
    return f"{matched.group(1)}_{matched.group(2)}"


def _find_candidate_row(candidate_report: dict[str, Any], ticker: str) -> dict[str, Any]:
    for row in list(candidate_report.get("candidates") or []):
        if str(row.get("ticker") or "") == ticker:
            return dict(row)
    raise ValueError(f"Ticker not found in candidate report: {ticker}")


def analyze_btst_primary_window_validation_runbook(
    candidate_report_path: str | Path,
    *,
    primary_roll_forward_path: str | Path,
    primary_window_gap_path: str | Path,
    ticker: str = "001309",
) -> dict[str, Any]:
    normalized_ticker = str(ticker).strip()
    candidate_report = _load_json(candidate_report_path)
    primary_roll_forward = _load_json(primary_roll_forward_path)
    primary_window_gap = _load_json(primary_window_gap_path)
    candidate_row = _find_candidate_row(candidate_report, normalized_ticker)

    report_dirs = list(candidate_report.get("report_dirs") or [])
    role_history = analyze_short_trade_ticker_role_history(report_dirs, tickers=[normalized_ticker])
    ticker_summary = list(role_history.get("ticker_summaries") or [])[0]
    observations = list(ticker_summary.get("observations") or [])

    window_rows: list[dict[str, Any]] = []
    by_window_key: dict[str, list[dict[str, Any]]] = {}
    for row in observations:
        window_key = _extract_window_key(str(row.get("report_label") or ""))
        by_window_key.setdefault(window_key, []).append(row)

    current_short_trade_window_keys = list(candidate_row.get("window_keys") or [])
    for window_key, rows in sorted(by_window_key.items()):
        role_counts = Counter(str(row.get("role") or "unknown") for row in rows)
        short_trade_rows = [
            row for row in rows if str(row.get("role") or "").startswith("short_trade_") or str(row.get("role") or "").startswith("short_trade_boundary")
        ]
        non_short_trade_rows = [row for row in rows if row not in short_trade_rows]
        if short_trade_rows and window_key in current_short_trade_window_keys:
            status = "current_qualified_window"
        elif short_trade_rows:
            status = "new_independent_short_trade_window"
        else:
            status = "pre_short_trade_context_only"
        window_rows.append(
            {
                "window_key": window_key,
                "report_labels": sorted({str(row.get("report_label") or "") for row in rows}),
                "observation_count": len(rows),
                "short_trade_observation_count": len(short_trade_rows),
                "non_short_trade_observation_count": len(non_short_trade_rows),
                "dominant_role": role_counts.most_common(1)[0][0] if role_counts else None,
                "role_counts": dict(role_counts),
                "status": status,
            }
        )

    independent_window_rows = [row for row in window_rows if row["status"] == "new_independent_short_trade_window"]
    missing_window_count = int(primary_window_gap.get("missing_window_count") or 0)
    validation_verdict = "independent_window_requirement_satisfied" if not missing_window_count and independent_window_rows else "await_new_independent_window_data"
    rerun_commands = [
        "python scripts/analyze_multi_window_short_trade_role_candidates.py --report-root-dirs data/reports --report-name-contains paper_trading_window --min-short-trade-trade-dates 2 --output-json data/reports/multi_window_short_trade_role_candidates_YYYYMMDD.json --output-md data/reports/multi_window_short_trade_role_candidates_YYYYMMDD.md",
        f"python scripts/analyze_btst_primary_window_validation_runbook.py --ticker {normalized_ticker} --candidate-report data/reports/multi_window_short_trade_role_candidates_YYYYMMDD.json --output-json data/reports/p7_primary_window_validation_runbook_{normalized_ticker}_YYYYMMDD.json --output-md data/reports/p7_primary_window_validation_runbook_{normalized_ticker}_YYYYMMDD.md",
        f"python scripts/analyze_btst_primary_roll_forward.py --ticker {normalized_ticker} --candidate-report data/reports/multi_window_short_trade_role_candidates_YYYYMMDD.json --output-json data/reports/p4_primary_roll_forward_validation_{normalized_ticker}_YYYYMMDD.json --output-md data/reports/p4_primary_roll_forward_validation_{normalized_ticker}_YYYYMMDD.md",
    ]
    recommendation = (
        f"{normalized_ticker} 的 primary roll-forward 方法链已经完整，当前缺的不是额外规则，而是新增独立窗口数据。"
        " 只要新的 paper_trading_window 落地，就按 rerun_commands 重新扫描并判定是否达到 distinct_window_count>=2。"
    )

    return {
        "generated_on": primary_roll_forward.get("generated_on"),
        "candidate_report": str(Path(candidate_report_path).expanduser().resolve()),
        "primary_roll_forward": str(Path(primary_roll_forward_path).expanduser().resolve()),
        "primary_window_gap": str(Path(primary_window_gap_path).expanduser().resolve()),
        "ticker": normalized_ticker,
        "distinct_window_count": candidate_row.get("distinct_window_count"),
        "target_window_count": primary_window_gap.get("target_window_count"),
        "missing_window_count": missing_window_count,
        "current_short_trade_window_keys": current_short_trade_window_keys,
        "window_scan_rows": window_rows,
        "independent_window_rows": independent_window_rows,
        "validation_verdict": validation_verdict,
        "rerun_commands": rerun_commands,
        "recommendation": recommendation,
    }


def render_btst_primary_window_validation_runbook_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Primary Window Validation Runbook")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- ticker: {analysis['ticker']}")
    lines.append(f"- distinct_window_count: {analysis['distinct_window_count']}")
    lines.append(f"- target_window_count: {analysis['target_window_count']}")
    lines.append(f"- missing_window_count: {analysis['missing_window_count']}")
    lines.append(f"- validation_verdict: {analysis['validation_verdict']}")
    lines.append("")
    lines.append("## Window Scan")
    for row in analysis["window_scan_rows"]:
        lines.append(
            f"- window_key={row['window_key']} status={row['status']} short_trade_observation_count={row['short_trade_observation_count']} dominant_role={row['dominant_role']} report_labels={row['report_labels']}"
        )
    if not analysis["window_scan_rows"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Rerun Commands")
    for command in analysis["rerun_commands"]:
        lines.append(f"- {command}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an execution-ready independent-window validation runbook for the BTST primary lane.")
    parser.add_argument("--candidate-report", default=str(DEFAULT_CANDIDATE_REPORT_PATH))
    parser.add_argument("--primary-roll-forward", default=str(DEFAULT_PRIMARY_ROLL_FORWARD_PATH))
    parser.add_argument("--primary-window-gap", default=str(DEFAULT_PRIMARY_WINDOW_GAP_PATH))
    parser.add_argument("--ticker", default="001309")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_primary_window_validation_runbook(
        args.candidate_report,
        primary_roll_forward_path=args.primary_roll_forward,
        primary_window_gap_path=args.primary_window_gap,
        ticker=args.ticker,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_primary_window_validation_runbook_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()