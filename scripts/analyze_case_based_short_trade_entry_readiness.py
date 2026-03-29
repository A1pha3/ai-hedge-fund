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


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _infer_ticker(report: dict[str, Any]) -> str:
    ticker = str(report.get("ticker") or "")
    if ticker:
        return ticker
    target_cases = list(report.get("target_cases") or [])
    if target_cases:
        return str(target_cases[0].get("ticker") or "")
    return ""


def _infer_lane_type(report: dict[str, Any]) -> str:
    if report.get("select_threshold") is not None:
        return "near_miss_promotion"
    target_cases = list(report.get("target_cases") or [])
    if target_cases and str(target_cases[0].get("before_decision") or "") == "rejected":
        return "targeted_boundary_release"
    return "case_based_entry"


def _infer_adjustment_cost(report: dict[str, Any]) -> float | None:
    explicit_cost = report.get("adjustment_cost")
    if explicit_cost is not None:
        return round(float(explicit_cost), 4)

    select_threshold = report.get("select_threshold")
    if select_threshold is not None:
        return round(max(0.0, DEFAULT_SELECT_THRESHOLD - float(select_threshold)), 4)

    target_cases = list(report.get("target_cases") or [])
    if not target_cases:
        return None
    near_miss_threshold = target_cases[0].get("near_miss_threshold") or report.get("near_miss_threshold")
    if near_miss_threshold is not None:
        return round(max(0.0, DEFAULT_NEAR_MISS_THRESHOLD - float(near_miss_threshold)), 4)
    return None


def _infer_next_high_return_mean(report: dict[str, Any]) -> float | None:
    value = report.get("next_high_return_mean")
    if value is not None:
        return round(float(value), 4)
    target_cases = list(report.get("target_cases") or [])
    values = [float(row["next_high_return"]) for row in target_cases if row.get("next_high_return") is not None]
    return _mean(values)


def _infer_next_close_return_mean(report: dict[str, Any]) -> float | None:
    value = report.get("next_close_return_mean")
    if value is not None:
        return round(float(value), 4)
    target_cases = list(report.get("target_cases") or [])
    values = [float(row["next_close_return"]) for row in target_cases if row.get("next_close_return") is not None]
    return _mean(values)


def _infer_next_close_positive_rate(report: dict[str, Any]) -> float | None:
    value = report.get("next_close_positive_rate")
    if value is not None:
        return round(float(value), 4)
    target_cases = list(report.get("target_cases") or [])
    if not target_cases:
        return None
    positive_count = sum(1 for row in target_cases if row.get("next_close_return") is not None and float(row["next_close_return"]) > 0)
    return round(positive_count / len(target_cases), 4)


def _infer_non_target_change_count(report: dict[str, Any]) -> int | None:
    release_report = report.get("release_report")
    if not release_report:
        return None
    resolved = Path(str(release_report)).expanduser().resolve()
    if not resolved.exists():
        return None
    release_analysis = _load_json(resolved)
    value = release_analysis.get("changed_non_target_case_count")
    if value is None:
        return None
    return int(value)


def _build_entry(report_path: str | Path) -> dict[str, Any]:
    report = _load_json(report_path)
    ticker = _infer_ticker(report)
    lane_type = _infer_lane_type(report)
    target_case_count = int(report.get("target_case_count") or 0)
    promoted_target_case_count = int(report.get("promoted_target_case_count") or 0)
    adjustment_cost = _infer_adjustment_cost(report)
    next_high_return_mean = _infer_next_high_return_mean(report)
    next_close_return_mean = _infer_next_close_return_mean(report)
    next_close_positive_rate = _infer_next_close_positive_rate(report)
    changed_non_target_case_count = _infer_non_target_change_count(report)
    promoted_all_targets = target_case_count > 0 and promoted_target_case_count == target_case_count
    low_pollution = changed_non_target_case_count == 0 if changed_non_target_case_count is not None else None
    strong_close_follow_through = bool(
        next_close_return_mean is not None
        and next_close_return_mean > 0
        and next_close_positive_rate is not None
        and next_close_positive_rate >= 0.75
    )
    low_adjustment_cost = bool(adjustment_cost is not None and adjustment_cost <= 0.04)

    if promoted_all_targets and low_adjustment_cost and strong_close_follow_through and target_case_count >= 2 and low_pollution is not False:
        readiness_tier = "primary_controlled_follow_through"
        recommendation = f"{ticker} 已具备下一轮主实验资格：低成本、低污染，且 close follow-through 足够一致。"
    elif promoted_all_targets and low_adjustment_cost and strong_close_follow_through and target_case_count >= 1 and low_pollution is not False:
        readiness_tier = "secondary_shadow_entry"
        recommendation = f"{ticker} 适合作为 shadow entry 保留：样本仍偏少，但 release 方向与次日表现一致。"
    elif promoted_all_targets and next_high_return_mean is not None and next_high_return_mean > 0:
        readiness_tier = "control_only"
        recommendation = f"{ticker} 更适合作为对照样本保留：存在 intraday upside，但 close follow-through 不够稳。"
    else:
        readiness_tier = "not_ready"
        recommendation = f"{ticker} 当前还不适合进入下一轮 case-based 受控实验。"

    return {
        "report": str(Path(report_path).expanduser().resolve()),
        "release_report": report.get("release_report"),
        "ticker": ticker,
        "lane_type": lane_type,
        "target_case_count": target_case_count,
        "promoted_target_case_count": promoted_target_case_count,
        "adjustment_cost": adjustment_cost,
        "changed_non_target_case_count": changed_non_target_case_count,
        "next_high_return_mean": next_high_return_mean,
        "next_close_return_mean": next_close_return_mean,
        "next_close_positive_rate": next_close_positive_rate,
        "promoted_all_targets": promoted_all_targets,
        "strong_close_follow_through": strong_close_follow_through,
        "low_adjustment_cost": low_adjustment_cost,
        "low_pollution": low_pollution,
        "readiness_tier": readiness_tier,
        "recommendation": recommendation,
    }


def analyze_case_based_short_trade_entry_readiness(report_paths: list[str | Path]) -> dict[str, Any]:
    entries = [_build_entry(path) for path in report_paths]
    tier_rank = {
        "primary_controlled_follow_through": 0,
        "secondary_shadow_entry": 1,
        "control_only": 2,
        "not_ready": 3,
    }
    entries.sort(
        key=lambda entry: (
            tier_rank.get(str(entry.get("readiness_tier") or "not_ready"), 99),
            -(float(entry.get("next_close_positive_rate") or -1.0)),
            -(float(entry.get("next_close_return_mean") or -999.0)),
            float(entry.get("adjustment_cost") or 999.0),
            -(int(entry.get("target_case_count") or 0)),
        )
    )

    for index, entry in enumerate(entries, start=1):
        entry["priority_rank"] = index

    ready_entries = [entry for entry in entries if entry["readiness_tier"] == "primary_controlled_follow_through"]
    if ready_entries:
        recommendation = f"当前最应推进的 case-based 受控实验入口是 {ready_entries[0]['ticker']}。"
    elif entries:
        recommendation = f"当前没有主实验级入口，优先保留 {entries[0]['ticker']} 作为下一轮观察样本。"
    else:
        recommendation = "当前没有可分析的 case-based entry 报告。"

    return {
        "report_count": len(entries),
        "entries": entries,
        "recommendation": recommendation,
    }


def render_case_based_short_trade_entry_readiness_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Case-Based Short Trade Entry Readiness Queue")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_count: {analysis['report_count']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    lines.append("")
    lines.append("## Entries")
    for entry in analysis["entries"]:
        lines.append(
            f"- rank={entry['priority_rank']} ticker={entry['ticker']} tier={entry['readiness_tier']} lane_type={entry['lane_type']} target_case_count={entry['target_case_count']} adjustment_cost={entry['adjustment_cost']} next_close_return_mean={entry['next_close_return_mean']} next_close_positive_rate={entry['next_close_positive_rate']} low_pollution={entry['low_pollution']}"
        )
        lines.append(f"  recommendation: {entry['recommendation']}")
    if not analysis["entries"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Tier Definitions")
    lines.append("- primary_controlled_follow_through: low-cost, low-pollution, positive close follow-through, and at least 2 target cases")
    lines.append("- secondary_shadow_entry: low-cost and positive close follow-through, but evidence depth is still thinner")
    lines.append("- control_only: useful as contrast or intraday reference, but not strong enough for the primary controlled path")
    lines.append("- not_ready: keep out of the next case-based experiment queue")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank case-based short-trade entries by experiment readiness.")
    parser.add_argument("--report", action="append", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_case_based_short_trade_entry_readiness(args.report)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_case_based_short_trade_entry_readiness_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()