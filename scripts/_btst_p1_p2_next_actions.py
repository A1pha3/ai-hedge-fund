"""Build high-value P1/P2 follow-up artifacts for BTST 0330."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.btst_top3_runbook_utils import P2_RUNBOOK_JSON_PATH, build_top3_runbook, ensure_inputs


REPORTS_DIR = Path("data/reports")
ARCH_DOC_PATH = Path("docs/zh-cn/product/arch/arch_optimize_implementation.md")
P0_SAMPLE_TABLE_PATH = REPORTS_DIR / "p0_micro_window_sample_table_20260330.csv"
P0_BASELINE_JSON_PATH = REPORTS_DIR / "p0_baseline_freeze_20260330.json"
P1_PRIORITY_CSV_PATH = REPORTS_DIR / "p1_false_negative_priority_board_20260330.csv"
P1_PRIORITY_JSON_PATH = REPORTS_DIR / "p1_false_negative_priority_summary_20260330.json"
P2_CROSSWALK_JSON_PATH = REPORTS_DIR / "p2_strategy_context_crosswalk_20260330.json"

NEAR_MISS_THRESHOLD = 0.46
SELECT_THRESHOLD = 0.58

BOOL_FIELDS = {
    "false_negative_intraday_space",
    "false_negative_positive_close",
    "false_negative_recurring_pattern",
    "false_negative_any",
}
FLOAT_FIELDS = {
    "score_target",
    "confidence",
    "score_b",
    "score_c",
    "score_final",
    "breakout_freshness",
    "trend_acceleration",
    "volume_expansion_quality",
    "close_strength",
    "catalyst_freshness",
    "overhead_supply_penalty",
    "extension_without_room_penalty",
    "layer_c_alignment",
    "layer_c_avoid_penalty",
    "next_open_return",
    "next_high_return",
    "next_close_return",
}
PRIORITY_FIELDS = [
    "priority_rank",
    "priority_bucket",
    "priority_score",
    "primary_archetype",
    "trade_date",
    "ticker",
    "short_trade_decision",
    "candidate_source",
    "report_family",
    "research_decision",
    "delta_classification",
    "score_target",
    "gap_to_near_miss",
    "gap_to_select",
    "next_high_return",
    "next_close_return",
    "false_negative_intraday_space",
    "false_negative_positive_close",
    "false_negative_recurring_pattern",
    "p1_archetypes",
    "blockers",
    "top_reasons",
    "priority_reason",
]
def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def parse_value(field: str, value: str) -> Any:
    if field in BOOL_FIELDS:
        return value == "True"
    if field in FLOAT_FIELDS:
        return float(value) if value else None
    return value


def load_sample_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        return [{field: parse_value(field, value) for field, value in row.items()} for row in reader]


def write_csv(rows: list[dict[str, Any]], path: Path, fieldnames: list[str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def derive_primary_archetype(row: dict[str, Any]) -> str:
    archetypes = [item for item in (row.get("p1_archetypes") or "").split("|") if item]
    if "structural_conflict_but_pattern_recurs" in archetypes and (row.get("score_target") or 0.0) >= 0.35:
        return "structural_conflict_but_pattern_recurs"
    if "score_fail_but_high_works" in archetypes:
        return "score_fail_but_high_works"
    if "watch_only_but_tradable_intraday" in archetypes:
        return "watch_only_but_tradable_intraday"
    if row.get("false_negative_positive_close"):
        return "positive_close_only"
    if row.get("false_negative_recurring_pattern"):
        return "recurring_pattern_only"
    return "residual_false_negative"


def build_priority_reason(row: dict[str, Any], primary_archetype: str, gap_to_near_miss: float | None) -> str:
    reasons: list[str] = []
    if primary_archetype == "structural_conflict_but_pattern_recurs":
        reasons.append("blocked recurring pattern with near-miss adjacency")
    elif primary_archetype == "score_fail_but_high_works":
        reasons.append("score fail but T+1 intraday space is already proven")
    elif primary_archetype == "watch_only_but_tradable_intraday":
        reasons.append("watch-only path now has tradable intraday evidence")
    elif primary_archetype == "positive_close_only":
        reasons.append("close continuation exists even without strong intraday breakout")
    elif primary_archetype == "recurring_pattern_only":
        reasons.append("pattern recurs but lacks realized outcome in current input pack")
    if row.get("false_negative_positive_close"):
        reasons.append("T+1 close stayed positive")
    if row.get("research_decision") == "selected":
        reasons.append("research side already selected it")
    if gap_to_near_miss is not None:
        reasons.append(f"gap_to_near_miss={gap_to_near_miss:.4f}")
    return "; ".join(reasons)


def compute_priority_score(row: dict[str, Any], primary_archetype: str, gap_to_near_miss: float | None) -> int:
    score = _priority_archetype_base_score(row, primary_archetype)
    score += _priority_context_bonus(row)
    score += _priority_outcome_bonus(row)
    if gap_to_near_miss is not None:
        score -= int(gap_to_near_miss * 20)
    return score


def _priority_archetype_base_score(row: dict[str, Any], primary_archetype: str) -> int:
    if primary_archetype == "structural_conflict_but_pattern_recurs":
        score = 35
        if (row.get("score_target") or 0.0) >= 0.35:
            score += 15
        return score
    if primary_archetype == "score_fail_but_high_works":
        return 30
    if primary_archetype == "watch_only_but_tradable_intraday":
        return 25
    if primary_archetype == "positive_close_only":
        return 18
    if primary_archetype == "recurring_pattern_only":
        return 12
    return 0


def _priority_context_bonus(row: dict[str, Any]) -> int:
    score = 0
    if row.get("short_trade_decision") == "blocked":
        score += 5
    if row.get("false_negative_positive_close"):
        score += 10
    if row.get("false_negative_recurring_pattern"):
        score += 6
    if row.get("research_decision") == "selected":
        score += 8
    return score


def _priority_outcome_bonus(row: dict[str, Any]) -> int:
    return int(((row.get("next_high_return") or 0.0) * 100)) + int(((row.get("next_close_return") or 0.0) * 100))


def derive_priority_bucket(primary_archetype: str, priority_score: int) -> str:
    if primary_archetype == "structural_conflict_but_pattern_recurs" and priority_score >= 55:
        return "immediate_core_case"
    if primary_archetype == "score_fail_but_high_works" and priority_score >= 45:
        return "immediate_core_case"
    if priority_score >= 35:
        return "secondary_case"
    return "monitor_only"


def build_p1_priority_outputs(sample_rows: list[dict[str, Any]]) -> dict[str, Any]:
    false_negative_rows = [row for row in sample_rows if row.get("false_negative_any")]
    priority_rows: list[dict[str, Any]] = []

    for row in false_negative_rows:
        score_target = row.get("score_target")
        gap_to_near_miss = round(max(0.0, NEAR_MISS_THRESHOLD - score_target), 4) if score_target is not None else None
        gap_to_select = round(max(0.0, SELECT_THRESHOLD - score_target), 4) if score_target is not None else None
        primary_archetype = derive_primary_archetype(row)
        priority_score = compute_priority_score(row, primary_archetype, gap_to_near_miss)
        priority_rows.append(
            {
                "priority_rank": 0,
                "priority_bucket": derive_priority_bucket(primary_archetype, priority_score),
                "priority_score": priority_score,
                "primary_archetype": primary_archetype,
                "trade_date": row.get("trade_date"),
                "ticker": row.get("ticker"),
                "short_trade_decision": row.get("short_trade_decision"),
                "candidate_source": row.get("candidate_source"),
                "report_family": row.get("report_family"),
                "research_decision": row.get("research_decision"),
                "delta_classification": row.get("delta_classification"),
                "score_target": row.get("score_target"),
                "gap_to_near_miss": gap_to_near_miss,
                "gap_to_select": gap_to_select,
                "next_high_return": row.get("next_high_return"),
                "next_close_return": row.get("next_close_return"),
                "false_negative_intraday_space": row.get("false_negative_intraday_space"),
                "false_negative_positive_close": row.get("false_negative_positive_close"),
                "false_negative_recurring_pattern": row.get("false_negative_recurring_pattern"),
                "p1_archetypes": row.get("p1_archetypes"),
                "blockers": row.get("blockers"),
                "top_reasons": row.get("top_reasons"),
                "priority_reason": build_priority_reason(row, primary_archetype, gap_to_near_miss),
            }
        )

    ordered_rows = sorted(
        priority_rows,
        key=lambda row: (
            {"immediate_core_case": 0, "secondary_case": 1, "monitor_only": 2}[row["priority_bucket"]],
            -row["priority_score"],
            0 if row["short_trade_decision"] == "blocked" else 1,
            row["gap_to_near_miss"] if row["gap_to_near_miss"] is not None else 999,
            row["ticker"],
        ),
    )
    for index, row in enumerate(ordered_rows, start=1):
        row["priority_rank"] = index

    write_csv(ordered_rows, P1_PRIORITY_CSV_PATH, PRIORITY_FIELDS)

    bucket_counts = Counter(row["priority_bucket"] for row in ordered_rows)
    archetype_counts = Counter(row["primary_archetype"] for row in ordered_rows)
    pending_watch_only = [
        {
            "trade_date": row["trade_date"],
            "ticker": row["ticker"],
            "score_target": row["score_target"],
            "preferred_entry_mode": row.get("preferred_entry_mode"),
            "reason": "forward brief only, no realized T+1 outcome yet",
        }
        for row in sample_rows
        if row.get("short_trade_decision") == "near_miss" and row.get("report_family") == "next_day_trade_brief"
    ]

    summary = {
        "generated_on": "2026-03-30",
        "priority_formula": {
            "core_weights": {
                "structural_conflict_but_pattern_recurs": 35,
                "score_fail_but_high_works": 30,
                "watch_only_but_tradable_intraday": 25,
                "positive_close_only": 18,
                "recurring_pattern_only": 12,
            },
            "boosters": {
                "blocked_case": 5,
                "positive_close": 10,
                "recurring_pattern": 6,
                "research_selected": 8,
                "next_high_return_x100": True,
                "next_close_return_x100": True,
            },
            "penalty": "gap_to_near_miss * 20",
        },
        "false_negative_count": len(ordered_rows),
        "bucket_counts": dict(bucket_counts),
        "archetype_counts": dict(archetype_counts),
        "top_10_cases": ordered_rows[:10],
        "pending_watch_only_confirmation": pending_watch_only,
        "outputs": {
            "priority_board_csv": str(P1_PRIORITY_CSV_PATH),
        },
    }
    P1_PRIORITY_JSON_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def build_p2_crosswalk(baseline_payload: dict[str, Any]) -> dict[str, Any]:
    baseline_coverage = baseline_payload["baseline_metrics"]["coverage"]
    baseline_opportunity = baseline_payload["baseline_metrics"]["opportunity"]["layer_b_boundary"]

    crosswalk = {
        "generated_on": "2026-03-30",
        "source_documents": [
            str(P0_BASELINE_JSON_PATH),
            str(ARCH_DOC_PATH),
        ],
        "baseline_anchor": {
            "replay_short_trade_target_count": baseline_coverage["replay_window_target_count"],
            "replay_selected_count": baseline_coverage["replay_window_selected_count"],
            "replay_near_miss_count": baseline_coverage["replay_window_near_miss_count"],
            "replay_blocked_count": baseline_coverage["replay_window_blocked_count"],
            "replay_rejected_count": baseline_coverage["replay_window_rejected_count"],
            "layer_b_high_hit_rate_at_2pct": baseline_opportunity["next_high_hit_rate_at_2pct"],
            "layer_b_close_positive_rate": baseline_opportunity["next_close_positive_rate"],
        },
        "validated_mainline_shifts": [
            {
                "theme": "旧 shared layer_b_boundary 主失败簇已被后续主线消除",
                "baseline_problem": "当前 replay baseline 里有 23 个 rejected_layer_b_boundary_score_fail。",
                "validated_evidence": "后续真实 live candidate builder 4 日窗口已把这 23 个 layer_b_boundary score-fail 压到 0，并替换为 6 个 short_trade_boundary near-miss。",
                "strategy_implication": "不要再把共享 Layer B 边界池当成 0330 的默认 P2 主修复路径；该问题在更靠后的主线里已经被结构性消解。",
                "status": "resolved_by_mainline",
            },
            {
                "theme": "admission 扩覆盖已有通过完整窗口验证的最小默认变体",
                "baseline_problem": "原 replay baseline 上所有 coverage variant 仍是 0 selected。",
                "validated_evidence": "catalyst_freshness_min=0.00 的 full-window live 变体给出 24 个 short_trade_boundary 候选，next_high_hit_rate@2%=0.75，next_close_positive_rate=0.7083。",
                "strategy_implication": "admission 侧暂定保留 catalyst-only floor zero 作为已验证默认入口，不再优先寻找第二条 floor 放松。",
                "status": "validated_default_variant",
            },
            {
                "theme": "当前真正活跃的前线已经从 admission 转移到 short_trade_boundary score frontier",
                "baseline_problem": "README 中仍把 breakout semantics 泛化为下一个单主题主线。",
                "validated_evidence": "后续 full-window frontier 扫描显示 18/18 short_trade_boundary score-fail 样本都存在 near-miss rescue row，但只有 300383 属于 threshold-only 低成本释放。",
                "strategy_implication": "下一轮最值钱的实验不再是重新扫 admission floor，而是 case-based score frontier release。",
                "status": "active_frontier",
            },
            {
                "theme": "near-miss promotion 已经有首个低污染主实验入口",
                "baseline_problem": "当前 P0/P1 里只有 2026-03-27 的 601869 watch-only 前瞻样本，还没有 realized watch-only archetype。",
                "validated_evidence": "001309 在 2026-03-24 与 2026-03-25 两个 near-miss 样本上只需把 select_threshold 从 0.58 下调到 0.56，就能实现 2/2 near_miss -> selected，且 changed_non_target_case_count=0；其 promotion 后 next_close_positive_rate=1.0。",
                "strategy_implication": "下一轮 case-based follow-through 应优先从 001309 开始，而不是先做全局 near-miss 抬升。",
                "status": "primary_controlled_follow_through",
            },
            {
                "theme": "structural conflict 仍应保持 case-based shadow 路径",
                "baseline_problem": "P1 当前会自然把 300724 一类 blocked recurring 样本推到高优先级。",
                "validated_evidence": "300724 只有在移除 hard block 与 conflict surcharge，并把 near_miss_threshold 下调到 0.42 时才会 blocked -> near_miss；窗口级 targeted release 仅改变这一只样本。",
                "strategy_implication": "300724 值得做，但应作为 case-based shadow structural release，不应上升为 blocked cluster-wide 默认放松。",
                "status": "shadow_structural_candidate",
            },
        ],
        "deferred_tracks": [
            {
                "theme": "profitability 软化",
                "reason": "当前仍缺直接对齐到 short_trade_boundary frontier 的小窗可执行样本组，先级低于已具备低污染入口的 case-based frontier。",
            },
            {
                "theme": "watch-only but tradable intraday archetype",
                "reason": "当前 P1 种子里没有 realized watch-only archetype；601869 仍是 forward brief only。",
            },
            {
                "theme": "更长滚动窗口稳定性验证",
                "reason": "001309、300383、300724 都更像当前窗口内成立的局部 baseline，默认升级前仍需滚动窗口复核。",
            },
        ],
    }
    P2_CROSSWALK_JSON_PATH.write_text(json.dumps(crosswalk, ensure_ascii=False, indent=2))
    return crosswalk


def main() -> None:
    ensure_inputs()
    sample_rows = load_sample_rows(P0_SAMPLE_TABLE_PATH)
    baseline_payload = load_json(P0_BASELINE_JSON_PATH)

    p1_priority_summary = build_p1_priority_outputs(sample_rows)
    p2_crosswalk = build_p2_crosswalk(baseline_payload)
    p2_runbook = build_top3_runbook()

    print(f"Wrote {P1_PRIORITY_CSV_PATH}")
    print(f"Wrote {P1_PRIORITY_JSON_PATH}")
    print(f"Wrote {P2_CROSSWALK_JSON_PATH}")
    print(f"Wrote {P2_RUNBOOK_JSON_PATH}")
    print(f"Prioritized false negatives: {p1_priority_summary['false_negative_count']}")
    print(f"Immediate core cases: {p1_priority_summary['bucket_counts'].get('immediate_core_case', 0)}")
    print(f"Validated mainline shifts: {len(p2_crosswalk['validated_mainline_shifts'])}")
    print(f"Top experiments: {len(p2_runbook['top_3_experiments'])}")


if __name__ == "__main__":
    main()
