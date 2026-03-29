from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _resolve_release_report(entry: dict[str, Any]) -> dict[str, Any]:
    release_report = entry.get("release_report")
    if not release_report:
        return {}
    resolved = Path(str(release_report)).expanduser().resolve()
    if not resolved.exists():
        return {}
    return _load_json(resolved)


def _parameter_summary(entry: dict[str, Any], release_analysis: dict[str, Any]) -> dict[str, Any]:
    if entry.get("lane_type") == "near_miss_promotion":
        return {
            "parameter_name": "select_threshold",
            "parameter_value": release_analysis.get("select_threshold"),
            "stale_weight": release_analysis.get("stale_weight"),
            "extension_weight": release_analysis.get("extension_weight"),
        }
    return {
        "parameter_name": "near_miss_threshold",
        "parameter_value": release_analysis.get("near_miss_threshold") or (list(release_analysis.get("changed_cases") or [{}])[0].get("near_miss_threshold")),
        "stale_weight": release_analysis.get("stale_weight") or (list(release_analysis.get("changed_cases") or [{}])[0].get("stale_weight")),
        "extension_weight": release_analysis.get("extension_weight") or (list(release_analysis.get("changed_cases") or [{}])[0].get("extension_weight")),
    }


def _tier_label(readiness_tier: str) -> str:
    mapping = {
        "primary_controlled_follow_through": "primary",
        "secondary_shadow_entry": "shadow",
        "control_only": "control",
    }
    return mapping.get(readiness_tier, "other")


def _entry_runbook(entry: dict[str, Any]) -> dict[str, Any]:
    release_analysis = _resolve_release_report(entry)
    parameter_summary = _parameter_summary(entry, release_analysis)
    targets = list(release_analysis.get("targets") or [])
    target_cases = list(release_analysis.get("changed_cases") or [])

    tier = _tier_label(str(entry.get("readiness_tier") or ""))
    if tier == "primary":
        objective = "把当前低成本、低污染的 near-miss promotion 作为下一轮主实验入口继续观测。"
        keep_conditions = [
            "changed_non_target_case_count 必须保持为 0",
            "next_close_return_mean 必须保持为正",
            "next_close_positive_rate 不应低于 0.75",
        ]
        demotion_conditions = [
            "出现任何非目标样本联动变化",
            "next_close_return_mean 回落到小于等于 0",
            "next_close_positive_rate 低于 0.75",
        ]
    elif tier == "shadow":
        objective = "保留为低污染 shadow entry，给主实验提供旁路参考，但不抢占主实验位置。"
        keep_conditions = [
            "changed_non_target_case_count 必须保持为 0",
            "release 后 next_close_return_mean 继续为正",
            "样本扩展前不升级为 primary",
        ]
        demotion_conditions = [
            "非目标样本被带动",
            "shadow 样本 next_close_return_mean 回落到小于等于 0",
        ]
    else:
        objective = "仅作为 intraday 对照样本保留，用来识别主实验是否只是短线热度而不是稳定 close follow-through。"
        keep_conditions = [
            "不参与主实验结论，只保留对照语义",
            "继续观察 intraday upside 是否独立于 close continuation",
        ]
        demotion_conditions = [
            "若后续连 intraday upside 也消失，可从对照队列移出",
        ]

    return {
        "tier": tier,
        "ticker": entry.get("ticker"),
        "lane_type": entry.get("lane_type"),
        "objective": objective,
        "targets": targets,
        "target_case_count": entry.get("target_case_count"),
        "adjustment_cost": entry.get("adjustment_cost"),
        "changed_non_target_case_count": entry.get("changed_non_target_case_count"),
        "next_high_return_mean": entry.get("next_high_return_mean"),
        "next_close_return_mean": entry.get("next_close_return_mean"),
        "next_close_positive_rate": entry.get("next_close_positive_rate"),
        "parameter_summary": parameter_summary,
        "changed_cases": target_cases,
        "keep_conditions": keep_conditions,
        "demotion_conditions": demotion_conditions,
        "entry_recommendation": entry.get("recommendation"),
    }


def analyze_case_based_short_trade_follow_through_runbook(readiness_report: str | Path) -> dict[str, Any]:
    readiness = _load_json(readiness_report)
    entries = list(readiness.get("entries") or [])

    primary_entry = next((entry for entry in entries if entry.get("readiness_tier") == "primary_controlled_follow_through"), None)
    shadow_entry = next((entry for entry in entries if entry.get("readiness_tier") == "secondary_shadow_entry"), None)
    control_entry = next((entry for entry in entries if entry.get("readiness_tier") == "control_only"), None)

    runbook = {
        "readiness_report": str(Path(readiness_report).expanduser().resolve()),
        "primary_entry": _entry_runbook(primary_entry) if primary_entry else None,
        "shadow_entry": _entry_runbook(shadow_entry) if shadow_entry else None,
        "control_entry": _entry_runbook(control_entry) if control_entry else None,
        "global_guardrails": [
            "下一轮只推进一个 primary case-based entry，不把 shadow 和 control 混成默认放松建议。",
            "所有 case-based 入口都必须保持 changed_non_target_case_count=0。",
            "若 primary 的 close follow-through 失效，不得因为 intraday upside 仍在就升级为默认口径。",
        ],
        "execution_sequence": [
            "先按 primary entry 跑 001309 的 follow-through 观察。",
            "并行保留 300383 作为 shadow entry，只做旁路参考，不改变主实验结论。",
            "300620 只保留为 intraday control，用来检查主实验是否只是热度放大。",
        ],
        "promotion_rules": [
            "只有 primary entry 保持低污染且 close follow-through 为正，才允许继续推进下一轮 case-based 扩展。",
            "shadow entry 只有在新增样本后仍保持低污染和正向 close follow-through，才可讨论是否提升优先级。",
            "control entry 只有在 adjustment_cost 和 close follow-through 同时改善后，才有资格脱离 control-only 角色。",
        ],
        "recommendation": readiness.get("recommendation"),
    }
    return runbook


def render_case_based_short_trade_follow_through_runbook_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Case-Based Short Trade Follow-Through Runbook")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- readiness_report: {analysis['readiness_report']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    lines.append("")

    for section_name, key in (("Primary Entry", "primary_entry"), ("Shadow Entry", "shadow_entry"), ("Control Entry", "control_entry")):
        entry = analysis.get(key)
        lines.append(f"## {section_name}")
        if not entry:
            lines.append("- none")
            lines.append("")
            continue
        lines.append(f"- ticker: {entry['ticker']}")
        lines.append(f"- lane_type: {entry['lane_type']}")
        lines.append(f"- tier: {entry['tier']}")
        lines.append(f"- objective: {entry['objective']}")
        lines.append(f"- target_case_count: {entry['target_case_count']}")
        lines.append(f"- adjustment_cost: {entry['adjustment_cost']}")
        lines.append(f"- next_close_return_mean: {entry['next_close_return_mean']}")
        lines.append(f"- next_close_positive_rate: {entry['next_close_positive_rate']}")
        lines.append(f"- parameter_name: {entry['parameter_summary']['parameter_name']}")
        lines.append(f"- parameter_value: {entry['parameter_summary']['parameter_value']}")
        lines.append(f"- targets: {', '.join(entry['targets']) if entry['targets'] else 'none'}")
        lines.append("- keep_conditions:")
        for item in entry["keep_conditions"]:
            lines.append(f"  - {item}")
        lines.append("- demotion_conditions:")
        for item in entry["demotion_conditions"]:
            lines.append(f"  - {item}")
        lines.append("")

    lines.append("## Global Guardrails")
    for item in analysis["global_guardrails"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Execution Sequence")
    for item in analysis["execution_sequence"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Promotion Rules")
    for item in analysis["promotion_rules"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a follow-through runbook from case-based readiness results.")
    parser.add_argument("--readiness-report", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_case_based_short_trade_follow_through_runbook(args.readiness_report)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_case_based_short_trade_follow_through_runbook_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()