from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_short_trade_ticker_role_history import analyze_short_trade_ticker_role_history, discover_report_dirs


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def render_recurring_frontier_transition_candidates_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Recurring Frontier Transition Candidates")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- recurring_frontier_report: {analysis['recurring_frontier_report']}")
    lines.append(f"- role_history_report_dirs: {analysis['role_history_report_dirs']}")
    lines.append("")
    lines.append("## Candidates")
    for row in analysis["candidates"]:
        lines.append(
            f"- {row['ticker']}: locality={row['transition_locality']}, occurrence_count={row['occurrence_count']}, minimal_adjustment_cost={row['minimal_adjustment_cost']}, previous_window_role={row['previous_window_role']}, current_window_role_count={row['current_window_role_count']}, recommendation={row['recommendation']}"
        )
    if not analysis["candidates"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_recurring_frontier_transition_candidates(
    recurring_frontier_report: str | Path,
    *,
    role_history_report_dirs: list[str | Path],
) -> dict[str, Any]:
    recurring = _load_json(recurring_frontier_report)
    priority_queue = list(recurring.get("priority_queue") or [])
    tickers = [str(row.get("ticker") or "") for row in priority_queue if str(row.get("ticker") or "").strip()]
    role_history = analyze_short_trade_ticker_role_history(role_history_report_dirs, tickers=tickers)
    summaries_by_ticker = {str(row.get("ticker") or ""): row for row in list(role_history.get("ticker_summaries") or [])}

    candidates: list[dict[str, Any]] = []
    for row in priority_queue:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        summary = dict(summaries_by_ticker.get(ticker) or {})
        observations = list(summary.get("observations") or [])
        previous_window_role = None
        if observations and summary.get("first_short_trade_report_dir"):
            first_short_trade_report_dir = str(summary.get("first_short_trade_report_dir") or "")
            previous_rows = [row for row in observations if str(row.get("report_label") or "") != first_short_trade_report_dir]
            if previous_rows:
                previous_window_role = str(previous_rows[-1].get("role") or "unknown")
        current_window_role_count = int(summary.get("recurring_short_trade_trade_date_count") or 0)

        if current_window_role_count >= 2 and previous_window_role and previous_window_role.startswith("layer_b_pool_"):
            transition_locality = "emergent_local_baseline"
            recommendation = f"{ticker} 当前更适合作为新出现的局部 recurring baseline 观察，不应直接外推成历史稳定规则。"
        elif current_window_role_count >= 2:
            transition_locality = "multi_window_stable"
            recommendation = f"{ticker} 已出现跨窗口 short-trade 复现，可继续推进更正式的 profile validation。"
        else:
            transition_locality = "non_recurring"
            recommendation = f"{ticker} 当前还不足以定义 recurring frontier transition。"

        candidates.append(
            {
                "ticker": ticker,
                "occurrence_count": int(row.get("occurrence_count") or 0),
                "minimal_adjustment_cost": row.get("minimal_adjustment_cost"),
                "previous_window_role": previous_window_role,
                "current_window_role_count": current_window_role_count,
                "transition_locality": transition_locality,
                "recommendation": recommendation,
            }
        )

    if candidates and all(row["transition_locality"] == "emergent_local_baseline" for row in candidates):
        recommendation = "当前 recurring frontier 候选都应视为 current-window emergent baselines。下一步应先扩大窗口验证，再决定是否进入可复用 profile。"
    elif candidates:
        recommendation = "当前 recurring frontier 候选已出现 local 与 stable 混合态，应优先把 stable 候选和 emergent 候选分开验证。"
    else:
        recommendation = "当前 recurring frontier 报告中没有可分析的候选。"

    return {
        "recurring_frontier_report": str(Path(recurring_frontier_report).expanduser().resolve()),
        "role_history_report_dirs": [str(Path(path).expanduser().resolve()) for path in role_history_report_dirs],
        "candidates": candidates,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify recurring frontier candidates as emergent-local or cross-window stable.")
    parser.add_argument("--recurring-frontier-report", required=True)
    parser.add_argument("--role-history-report-dirs", default="", help="Comma-separated report directories")
    parser.add_argument("--role-history-report-root-dirs", default="", help="Comma-separated root directories to recursively discover role-history report directories")
    parser.add_argument("--report-name-contains", default="", help="Optional substring filter applied when discovering role-history report directories")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    role_history_report_dirs = [token.strip() for token in str(args.role_history_report_dirs).split(",") if token.strip()]
    if args.role_history_report_root_dirs:
        role_history_report_dirs.extend(
            str(path)
            for path in discover_report_dirs(
                [token.strip() for token in str(args.role_history_report_root_dirs).split(",") if token.strip()],
                report_name_contains=str(args.report_name_contains or ""),
            )
        )
    if not role_history_report_dirs:
        raise SystemExit("No role-history report directories were provided or discovered.")

    analysis = analyze_recurring_frontier_transition_candidates(
        args.recurring_frontier_report,
        role_history_report_dirs=role_history_report_dirs,
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_recurring_frontier_transition_candidates_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()