from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_SELECT_THRESHOLD = 0.58
DEFAULT_NEAR_MISS_THRESHOLD = 0.46


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _parse_reports(values: list[str]) -> list[str]:
    return [str(value).strip() for value in values if str(value).strip()]


def _round(value: float) -> float:
    return round(float(value), 4)


def _extract_entry(report_path: str | Path) -> dict[str, Any]:
    report = _load_json(report_path)
    target_cases = list(report.get("target_cases") or [])
    first_case = dict(target_cases[0] or {}) if target_cases else {}

    if "select_threshold" in report:
        lane_type = "near_miss_promotion"
        ticker = str(report.get("ticker") or first_case.get("ticker") or "")
        adjustment_cost = _round(DEFAULT_SELECT_THRESHOLD - float(report.get("select_threshold") or DEFAULT_SELECT_THRESHOLD))
    elif "ticker" in report:
        lane_type = "recurring_frontier_release"
        ticker = str(report.get("ticker") or "")
        costs = [float(case.get("adjustment_cost") or 0.0) for case in target_cases if case.get("adjustment_cost") is not None]
        adjustment_cost = _round(sum(costs) / len(costs)) if costs else None
    else:
        lane_type = "targeted_boundary_release"
        ticker = str(first_case.get("ticker") or "")
        near_miss_threshold = float(first_case.get("near_miss_threshold") or DEFAULT_NEAR_MISS_THRESHOLD)
        adjustment_cost = _round(DEFAULT_NEAR_MISS_THRESHOLD - near_miss_threshold)

    entry = {
        "report": str(Path(report_path).expanduser().resolve()),
        "ticker": ticker,
        "lane_type": lane_type,
        "target_case_count": int(report.get("target_case_count") or 0),
        "promoted_target_case_count": int(report.get("promoted_target_case_count") or 0),
        "adjustment_cost": adjustment_cost,
        "next_high_return_mean": report.get("next_high_return_mean"),
        "next_close_return_mean": report.get("next_close_return_mean"),
        "next_high_hit_rate_at_threshold": report.get("next_high_hit_rate_at_threshold"),
        "next_close_positive_rate": report.get("next_close_positive_rate"),
        "recommendation": report.get("recommendation"),
    }

    if lane_type == "targeted_boundary_release":
        case = first_case
        entry["next_high_return_mean"] = case.get("next_high_return")
        entry["next_close_return_mean"] = case.get("next_close_return")
        entry["next_high_hit_rate_at_threshold"] = 1.0 if case.get("next_high_return") is not None and float(case.get("next_high_return")) >= 0.02 else 0.0
        entry["next_close_positive_rate"] = 1.0 if case.get("next_close_return") is not None and float(case.get("next_close_return")) > 0 else 0.0
    return entry


def _sort_key(entry: dict[str, Any]) -> tuple[float, float, float, float, int]:
    close_positive = float(entry.get("next_close_positive_rate") if entry.get("next_close_positive_rate") is not None else -999.0)
    close_mean = float(entry.get("next_close_return_mean") if entry.get("next_close_return_mean") is not None else -999.0)
    high_mean = float(entry.get("next_high_return_mean") if entry.get("next_high_return_mean") is not None else -999.0)
    adjustment_cost = float(entry.get("adjustment_cost") if entry.get("adjustment_cost") is not None else 999.0)
    case_count = int(entry.get("target_case_count") or 0)
    return (-close_positive, -close_mean, adjustment_cost, -high_mean, -case_count)


def render_short_trade_release_priority_scoreboard_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Short Trade Release Priority Scoreboard")
    lines.append("")
    lines.append("## Ranking")
    for entry in analysis["entries"]:
        lines.append(
            f"- rank {entry['priority_rank']}: {entry['ticker']} ({entry['lane_type']}), adjustment_cost={entry['adjustment_cost']}, target_case_count={entry['target_case_count']}, next_high_return_mean={entry['next_high_return_mean']}, next_close_return_mean={entry['next_close_return_mean']}, next_close_positive_rate={entry['next_close_positive_rate']}"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_short_trade_release_priority_scoreboard(report_paths: list[str]) -> dict[str, Any]:
    entries = [_extract_entry(path) for path in report_paths]
    entries.sort(key=_sort_key)
    for index, entry in enumerate(entries, start=1):
        entry["priority_rank"] = index

    if entries:
        leader = entries[0]
        recommendation = (
            f"当前统一 scorecard 的第一优先入口是 {leader['ticker']}。"
            f"它在 {leader['lane_type']} 路径上同时给出更低的 adjustment_cost={leader['adjustment_cost']} 和更强的 close continuation。"
        )
    else:
        recommendation = "当前没有可用的 release outcome 报告可供排序。"

    return {
        "report_count": len(entries),
        "entries": entries,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank short-trade release lanes in one scoreboard.")
    parser.add_argument("--report", action="append", dest="reports", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_short_trade_release_priority_scoreboard(_parse_reports(args.reports))
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_release_priority_scoreboard_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()