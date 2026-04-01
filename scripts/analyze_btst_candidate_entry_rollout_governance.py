from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_FRONTIER_REPORT_PATH = REPORTS_DIR / "btst_candidate_entry_frontier_20260330.json"
DEFAULT_STRUCTURAL_VALIDATION_PATH = REPORTS_DIR / "selection_target_structural_variants_candidate_entry_current_window_20260330.json"
DEFAULT_WINDOW_SCAN_PATH = REPORTS_DIR / "btst_candidate_entry_window_scan_20260330.json"
DEFAULT_SCORE_FRONTIER_PATH = REPORTS_DIR / "btst_score_construction_frontier_20260330.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p9_candidate_entry_rollout_governance_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p9_candidate_entry_rollout_governance_20260330.md"

VARIANT_TO_STRUCTURAL_ALIAS = {
    "weak_structure_triplet": "exclude_watchlist_avoid_weak_structure_entries",
    "semantic_pair_300502": None,
    "volume_only_20260326": None,
}
TARGET_DISTINCT_WINDOW_COUNT = 2


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _score_frontier_all_zero(score_frontier_report: dict[str, Any]) -> bool:
    variant_rows = [dict(row or {}) for row in list(score_frontier_report.get("ranked_variants") or [])]
    if not variant_rows:
        return True
    return all(int(row.get("closed_cycle_tradeable_count") or 0) == 0 for row in variant_rows)


def derive_candidate_entry_shadow_state(
    *,
    rollout_readiness: str,
    preserve_misfire_report_count: int,
    distinct_window_count_with_filtered_entries: int,
    target_window_count: int = TARGET_DISTINCT_WINDOW_COUNT,
) -> dict[str, Any]:
    missing_window_count = max(int(target_window_count or 0) - max(int(distinct_window_count_with_filtered_entries or 0), 0), 0)

    if preserve_misfire_report_count > 0:
        lane_status = "research_only"
        default_upgrade_status = "blocked_by_preserve_misfire"
        upgrade_gap = "preserve_misfire_present"
    elif rollout_readiness == "shadow_only_until_second_window":
        lane_status = "shadow_only_until_second_window"
        default_upgrade_status = "blocked_by_single_window_candidate_entry_signal"
        upgrade_gap = "await_new_independent_window_data"
    elif rollout_readiness == "shadow_rollout_review_ready":
        lane_status = "shadow_rollout_review_ready"
        default_upgrade_status = "blocked_pending_additional_shadow_execution_evidence"
        upgrade_gap = "ready_for_shadow_rollout_review"
    else:
        lane_status = "research_only"
        default_upgrade_status = "blocked_by_missing_window_signal"
        upgrade_gap = "missing_window_signal"

    return {
        "lane_status": lane_status,
        "default_upgrade_status": default_upgrade_status,
        "target_window_count": int(target_window_count or 0),
        "missing_window_count": missing_window_count,
        "upgrade_gap": upgrade_gap,
    }


def analyze_btst_candidate_entry_rollout_governance(
    frontier_report_path: str | Path,
    *,
    structural_validation_path: str | Path,
    window_scan_path: str | Path,
    score_frontier_path: str | Path,
) -> dict[str, Any]:
    frontier_report = _load_json(frontier_report_path)
    structural_validation = _load_json(structural_validation_path)
    window_scan = _load_json(window_scan_path)
    score_frontier_report = _load_json(score_frontier_path)

    best_variant = dict(frontier_report.get("best_variant") or {})
    best_variant_name = str(best_variant.get("variant_name") or "")
    structural_alias = VARIANT_TO_STRUCTURAL_ALIAS.get(best_variant_name)
    structural_rows = [dict(row or {}) for row in list(structural_validation.get("rows") or [])]
    structural_row = next((row for row in structural_rows if str(row.get("structural_variant") or "") == str(structural_alias or "")), {})
    structural_analysis = dict(structural_row.get("analysis") or {})

    current_window_focus_filtered = list(best_variant.get("focus_filtered_tickers") or [])
    current_window_preserve_filtered = list(best_variant.get("preserve_filtered_tickers") or [])
    current_window_filtered_count = int(best_variant.get("filtered_candidate_entry_count") or 0)
    current_window_next_high = best_variant.get("filtered_next_high_hit_rate_at_threshold")
    current_window_next_close = best_variant.get("filtered_next_close_positive_rate")

    score_frontier_all_zero = _score_frontier_all_zero(score_frontier_report)
    scan_readiness = str(window_scan.get("rollout_readiness") or "unknown")
    preserve_misfire_report_count = int(window_scan.get("preserve_misfire_report_count") or 0)
    distinct_window_count_with_filtered_entries = int(window_scan.get("distinct_window_count_with_filtered_entries") or 0)
    shadow_state = derive_candidate_entry_shadow_state(
        rollout_readiness=scan_readiness,
        preserve_misfire_report_count=preserve_misfire_report_count,
        distinct_window_count_with_filtered_entries=distinct_window_count_with_filtered_entries,
    )
    lane_status = shadow_state["lane_status"]
    default_upgrade_status = shadow_state["default_upgrade_status"]

    recommendation = (
        "当前 candidate-entry 主结论应收敛为：保留 weak-structure selective rule 作为 shadow-only 入口治理语义，"
        "不要把 semantic_pair 或 volume-only 规则直接提升为默认，更不要把它误写成 score frontier 的替代品。"
    )
    if lane_status == "shadow_rollout_review_ready":
        recommendation = (
            "当前 candidate-entry 主结论应收敛为：weak-structure selective rule 已具备进入 shadow rollout review 的条件，"
            "但仍不能单独作为默认升级依据，必须继续以 preserve-misfire=0 和新增独立窗口命中作为守门条件。"
        )
    elif lane_status == "research_only":
        recommendation = (
            "当前 candidate-entry 主结论应收敛为：弱结构规则仍停留在 research-only 或单窗证据阶段，"
            "不能进入 rollout，更不能替代当前 default admission 基线。"
        )

    return {
        "frontier_report": str(Path(frontier_report_path).expanduser().resolve()),
        "structural_validation_report": str(Path(structural_validation_path).expanduser().resolve()),
        "window_scan_report": str(Path(window_scan_path).expanduser().resolve()),
        "score_frontier_report": str(Path(score_frontier_path).expanduser().resolve()),
        "candidate_entry_rule": best_variant_name,
        "recommended_structural_variant": structural_alias,
        "lane_status": lane_status,
        "default_upgrade_status": default_upgrade_status,
        "target_window_count": shadow_state["target_window_count"],
        "missing_window_count": shadow_state["missing_window_count"],
        "upgrade_gap": shadow_state["upgrade_gap"],
        "score_frontier_all_zero": score_frontier_all_zero,
        "current_window_evidence": {
            "filtered_candidate_entry_count": current_window_filtered_count,
            "focus_filtered_tickers": current_window_focus_filtered,
            "preserve_filtered_tickers": current_window_preserve_filtered,
            "filtered_next_high_hit_rate_at_threshold": current_window_next_high,
            "filtered_next_close_positive_rate": current_window_next_close,
            "evidence_tier": best_variant.get("evidence_tier"),
            "selection_basis": best_variant.get("selection_basis"),
        },
        "main_chain_validation": {
            "structural_variant": structural_alias,
            "decision_mismatch_count": int(structural_row.get("decision_mismatch_count") or 0),
            "released_from_blocked": list(structural_row.get("released_from_blocked") or []),
            "blocked_to_near_miss": list(structural_row.get("blocked_to_near_miss") or []),
            "blocked_to_selected": list(structural_row.get("blocked_to_selected") or []),
            "filtered_candidate_entry_counts": dict(structural_analysis.get("filtered_candidate_entry_counts") or {}),
            "candidate_entry_filter_observability": dict(structural_analysis.get("candidate_entry_filter_observability") or {}),
        },
        "window_scan_summary": {
            "report_count": int(window_scan.get("report_count") or 0),
            "filtered_report_count": int(window_scan.get("filtered_report_count") or 0),
            "focus_hit_report_count": int(window_scan.get("focus_hit_report_count") or 0),
            "preserve_misfire_report_count": preserve_misfire_report_count,
            "distinct_window_count_with_filtered_entries": distinct_window_count_with_filtered_entries,
            "rollout_readiness": scan_readiness,
            "filtered_ticker_counts": dict(window_scan.get("filtered_ticker_counts") or {}),
        },
        "do_not_promote_variants": ["semantic_pair_300502", "volume_only_20260326"],
        "keep_guardrails": [
            "score frontier 仍为 0 actionable 时，candidate-entry 规则只能当作入口清洗语义，不能误写成默认升级依据",
            "preserve_tickers 必须持续保持 0 误伤，当前锚点是 300394 不得被弱结构规则过滤",
            "弱结构规则进入主链时只能以 exclude_watchlist_avoid_weak_structure_entries structural variant 形式复用，不再另造平行规则",
            "若 main-chain 验证不再是 blocked->none 的单点释放，而开始扩大到非目标样本，就必须回退到 research-only",
        ],
        "promotion_conditions": [
            "新增独立窗口后，弱结构规则至少在第 2 个 window_key 上再次过滤到 candidate-entry 样本",
            "window scan 继续保持 preserve_misfire_report_count == 0",
            "当前窗口型 filtered cohort 仍需维持 next_high_hit_rate@2% 与 next_close_positive_rate 同时低于 baseline false-negative pool",
            "在 shadow rollout review 中，语义仍应优先 weak_structure_triplet / exclude_watchlist_avoid_weak_structure_entries，而不是 semantic_pair 或 volume-only",
        ],
        "next_actions": [
            "把 exclude_watchlist_avoid_weak_structure_entries 固定为后续 replay / shadow 验证的唯一 candidate-entry 弱结构旁路",
            "每出现新的 paper_trading_window 报告，就重跑 candidate-entry window scan，先补第二个独立窗口命中再讨论 lane promotion",
            "维持 semantic_pair_300502 与 volume_only_20260326 为研究参考，不进入 rollout 主链",
        ],
        "recommendation": recommendation,
    }


def render_btst_candidate_entry_rollout_governance_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Entry Rollout Governance")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- candidate_entry_rule: {analysis['candidate_entry_rule']}")
    lines.append(f"- recommended_structural_variant: {analysis['recommended_structural_variant']}")
    lines.append(f"- lane_status: {analysis['lane_status']}")
    lines.append(f"- default_upgrade_status: {analysis['default_upgrade_status']}")
    lines.append(f"- target_window_count: {analysis['target_window_count']}")
    lines.append(f"- missing_window_count: {analysis['missing_window_count']}")
    lines.append(f"- upgrade_gap: {analysis['upgrade_gap']}")
    lines.append(f"- score_frontier_all_zero: {analysis['score_frontier_all_zero']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    lines.append("")
    lines.append("## Current Window Evidence")
    for key, value in dict(analysis.get("current_window_evidence") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Main-Chain Validation")
    for key, value in dict(analysis.get("main_chain_validation") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Window Scan Summary")
    for key, value in dict(analysis.get("window_scan_summary") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Keep Guardrails")
    for item in list(analysis.get("keep_guardrails") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Promotion Conditions")
    for item in list(analysis.get("promotion_conditions") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Next Actions")
    for item in list(analysis.get("next_actions") or []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rollout governance for BTST candidate-entry weak-structure rule.")
    parser.add_argument("--frontier-report", default=str(DEFAULT_FRONTIER_REPORT_PATH))
    parser.add_argument("--structural-validation-report", default=str(DEFAULT_STRUCTURAL_VALIDATION_PATH))
    parser.add_argument("--window-scan-report", default=str(DEFAULT_WINDOW_SCAN_PATH))
    parser.add_argument("--score-frontier-report", default=str(DEFAULT_SCORE_FRONTIER_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_entry_rollout_governance(
        args.frontier_report,
        structural_validation_path=args.structural_validation_report,
        window_scan_path=args.window_scan_report,
        score_frontier_path=args.score_frontier_report,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_candidate_entry_rollout_governance_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()