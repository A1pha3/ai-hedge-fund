"""Generate P0 baseline freeze artifacts for BTST 0330 work."""

from __future__ import annotations

import ast
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
REPLAY_ARTIFACT_ROOT = REPORTS_DIR / "paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329" / "selection_artifacts"
BRIEF_REPORT_DIR = REPORTS_DIR / "paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260329"
BRIEF_SNAPSHOT_PATH = BRIEF_REPORT_DIR / "selection_artifacts" / "2026-03-27" / "selection_snapshot.json"
BRIEF_REPORT_PATH = REPORTS_DIR / "btst_next_day_trade_brief_20260327_for_20260330_20260329.md"
BLOCKER_PATH = REPORTS_DIR / "short_trade_blocker_analysis_baseline_full_20260329.json"
LAYER_B_OUTCOME_PATH = REPORTS_DIR / "pre_layer_short_trade_outcomes_layer_b_boundary_current_window_20260329.json"
SHORT_TRADE_OUTCOME_PATH = REPORTS_DIR / "pre_layer_short_trade_outcomes_short_trade_boundary_current_window_20260329.json"
COVERAGE_VARIANT_PATH = REPORTS_DIR / "short_trade_boundary_coverage_variants_current_window_20260329.md"
PROFITABILITY_PATH = REPORTS_DIR / "profitability_subfactor_breakdown_current_window_20260327.json"

OUTPUT_JSON_PATH = REPORTS_DIR / "p0_baseline_freeze_20260330.json"
OUTPUT_CSV_PATH = REPORTS_DIR / "p0_micro_window_sample_table_20260330.csv"
P1_MAIN_ENTRY_PATH = REPORTS_DIR / "p1_main_entry_table_20260330.csv"
P1_WATCH_ONLY_PATH = REPORTS_DIR / "p1_watch_only_table_20260330.csv"
P1_FALSE_NEGATIVE_PATH = REPORTS_DIR / "p1_false_negative_dossier_20260330.csv"
P1_SUMMARY_PATH = REPORTS_DIR / "p1_false_negative_summary_20260330.json"

FN_HIGH_THRESHOLD = 0.02

TAXONOMY = {
    "selected": "主入场票：T+1 盘中确认后才允许执行，不等于无条件开盘追价。",
    "near_miss": "观察票：可以跟踪，但默认不进入买入清单。",
    "blocked": "结构冲突拦截：样本本身有一定候选价值，但被结构/冲突规则阻断。",
    "rejected": "边界或分数未通过：没有进入正式 short-trade 执行比较池。",
    "false_negative": "被判为 rejected、blocked 或仅留在观察层，但至少满足 T+1 intraday 空间、T+1 close 为正、或同类模式反复出现之一。",
}

LABEL_SEMANTICS = {
    "selected": "main_entry",
    "near_miss": "watch_only",
    "blocked": "structural_block",
    "rejected": "boundary_or_score_fail",
}

CSV_FIELDS = [
    "trade_date",
    "next_trade_date",
    "report_family",
    "evidence_status",
    "ticker",
    "candidate_source",
    "short_trade_decision",
    "taxonomy_semantic",
    "research_decision",
    "delta_classification",
    "score_target",
    "confidence",
    "preferred_entry_mode",
    "gate_data",
    "gate_execution",
    "gate_structural",
    "gate_score",
    "blockers",
    "positive_tags",
    "negative_tags",
    "top_reasons",
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
    "false_negative_intraday_space",
    "false_negative_positive_close",
    "false_negative_recurring_pattern",
    "false_negative_any",
    "p1_archetypes",
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def normalize_trade_date(value: str | None) -> str | None:
    if not value:
        return None
    if "-" in value:
        return value
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def mean_or_none(values: list[float]) -> float | None:
    return round_or_none(sum(values) / len(values)) if values else None


def rate_or_none(values: list[bool]) -> float | None:
    return round_or_none(sum(1 for value in values if value) / len(values)) if values else None


def parse_brief_next_trade_date(path: Path) -> str | None:
    match = re.search(r"^- next_trade_date: ([0-9]{4}-[0-9]{2}-[0-9]{2})$", path.read_text(), re.MULTILINE)
    return match.group(1) if match else None


def parse_coverage_variant_report(path: Path) -> dict[str, Any]:
    text = path.read_text()
    candidate_pool_match = re.search(r"^- candidate_pool_count: (\d+)$", text, re.MULTILINE)
    baseline_match = re.search(r"^- baseline_selected_candidate_count: (\d+)$", text, re.MULTILINE)
    variant_lines = [line[2:] for line in text.splitlines() if line.startswith("- candidate_")]

    variants: list[dict[str, Any]] = []
    for line in variant_lines:
        filtered_match = re.search(r"filtered_reason_counts=(\{.*\})$", line)
        filtered_reason_counts = ast.literal_eval(filtered_match.group(1)) if filtered_match else {}
        metrics_match = re.match(r"(?P<name>candidate_[^:]+): selected=(?P<selected>\d+), qualified_pool=(?P<qualified>\d+), close_mean=(?P<close_mean>[^,]+), close_positive_rate=(?P<close_rate>[^,]+), high_hit_rate=(?P<high_rate>[^,]+)", line)
        if metrics_match:
            variants.append(
                {
                    "variant_name": metrics_match.group("name"),
                    "selected_candidate_count": int(metrics_match.group("selected")),
                    "qualified_pool": int(metrics_match.group("qualified")),
                    "close_mean": metrics_match.group("close_mean"),
                    "close_positive_rate": metrics_match.group("close_rate"),
                    "high_hit_rate": metrics_match.group("high_rate"),
                    "filtered_reason_counts": filtered_reason_counts,
                }
            )

    all_zero = all(variant["selected_candidate_count"] == 0 for variant in variants)
    dominant_filtered_reason = None
    if variants:
        dominant_filtered_reason = max(variants[0]["filtered_reason_counts"].items(), key=lambda item: item[1])

    return {
        "candidate_pool_count": int(candidate_pool_match.group(1)) if candidate_pool_match else None,
        "baseline_selected_candidate_count": int(baseline_match.group(1)) if baseline_match else None,
        "variant_count": len(variants),
        "all_variants_zero_selected": all_zero,
        "dominant_filtered_reason": {"name": dominant_filtered_reason[0], "count": dominant_filtered_reason[1]} if dominant_filtered_reason else None,
        "variants": variants,
    }


def summarize_outcomes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[row["trade_date"]].append(row)

    daily: list[dict[str, Any]] = []
    for trade_date in sorted(by_date):
        samples = by_date[trade_date]
        highs = [sample["next_high_return"] for sample in samples if sample.get("next_high_return") is not None]
        closes = [sample["next_close_return"] for sample in samples if sample.get("next_close_return") is not None]
        daily.append(
            {
                "trade_date": trade_date,
                "sample_count": len(samples),
                "tickers": sorted({sample["ticker"] for sample in samples}),
                "next_high_return_mean": mean_or_none(highs),
                "next_high_hit_rate_at_2pct": rate_or_none([value >= FN_HIGH_THRESHOLD for value in highs]),
                "next_close_return_mean": mean_or_none(closes),
                "next_close_positive_rate": rate_or_none([value > 0 for value in closes]),
            }
        )

    highs = [row["next_high_return"] for row in rows if row.get("next_high_return") is not None]
    closes = [row["next_close_return"] for row in rows if row.get("next_close_return") is not None]
    ticker_counts = Counter(row["ticker"] for row in rows)
    return {
        "sample_count": len(rows),
        "daily": daily,
        "next_high_return_mean": mean_or_none(highs),
        "next_high_hit_rate_at_2pct": rate_or_none([value >= FN_HIGH_THRESHOLD for value in highs]),
        "next_close_return_mean": mean_or_none(closes),
        "next_close_positive_rate": rate_or_none([value > 0 for value in closes]),
        "unique_ticker_count": len(ticker_counts),
        "ticker_frequency": dict(ticker_counts.most_common()),
        "fn_candidate_count_high": sum(1 for value in highs if value >= FN_HIGH_THRESHOLD),
        "fn_candidate_count_close": sum(1 for value in closes if value > 0),
    }


def load_outcome_index() -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any], dict[str, Any]]:
    layer_b_rows = load_json(LAYER_B_OUTCOME_PATH)
    layer_b_rows = layer_b_rows.get("rows", layer_b_rows) if isinstance(layer_b_rows, dict) else layer_b_rows
    short_trade_rows = load_json(SHORT_TRADE_OUTCOME_PATH)
    short_trade_rows = short_trade_rows.get("rows", short_trade_rows) if isinstance(short_trade_rows, dict) else short_trade_rows

    outcome_index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*layer_b_rows, *short_trade_rows]:
        outcome_index[(normalize_trade_date(row["trade_date"]), row["ticker"])] = row

    return outcome_index, summarize_outcomes(layer_b_rows), summarize_outcomes(short_trade_rows)


def build_recurrent_ticker_set(blocker: dict[str, Any]) -> set[str]:
    recurrence_source = Counter()
    for key in ("top_blocked_examples", "top_near_threshold_examples"):
        for row in blocker.get(key, []):
            ticker = row.get("ticker")
            if ticker:
                recurrence_source[ticker] += 1
    return {ticker for ticker, count in recurrence_source.items() if count >= 2}


def extract_short_trade_rows(snapshot_path: Path, report_family: str, evidence_status: str, next_trade_date_override: str | None, outcome_index: dict[tuple[str, str], dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot = load_json(snapshot_path)
    trade_date = normalize_trade_date(snapshot.get("trade_date"))
    target_summary = snapshot.get("target_summary", {})
    selection_targets = snapshot.get("selection_targets", {})
    rows: list[dict[str, Any]] = []

    for ticker in sorted(selection_targets):
        entry = selection_targets[ticker]
        short_trade = entry.get("short_trade") or {}
        research = entry.get("research") or {}
        metrics_payload = short_trade.get("metrics_payload", {})
        gate_status = short_trade.get("gate_status", {})
        outcome_row = outcome_index.get((trade_date, ticker), {})

        rows.append(
            {
                "trade_date": trade_date,
                "next_trade_date": outcome_row.get("next_trade_date") or next_trade_date_override,
                "report_family": report_family,
                "evidence_status": evidence_status,
                "ticker": ticker,
                "candidate_source": entry.get("candidate_source"),
                "short_trade_decision": short_trade.get("decision"),
                "taxonomy_semantic": LABEL_SEMANTICS.get(short_trade.get("decision")),
                "research_decision": research.get("decision"),
                "delta_classification": entry.get("delta_classification"),
                "score_target": round_or_none(short_trade.get("score_target")),
                "confidence": round_or_none(short_trade.get("confidence")),
                "preferred_entry_mode": short_trade.get("preferred_entry_mode"),
                "gate_data": gate_status.get("data"),
                "gate_execution": gate_status.get("execution"),
                "gate_structural": gate_status.get("structural"),
                "gate_score": gate_status.get("score"),
                "blockers": ", ".join(short_trade.get("blockers", [])),
                "positive_tags": ", ".join(short_trade.get("positive_tags", [])),
                "negative_tags": ", ".join(short_trade.get("negative_tags", [])),
                "top_reasons": " | ".join(short_trade.get("top_reasons", [])),
                "score_b": round_or_none(metrics_payload.get("score_b")),
                "score_c": round_or_none(metrics_payload.get("score_c")),
                "score_final": round_or_none(metrics_payload.get("score_final")),
                "breakout_freshness": round_or_none(metrics_payload.get("breakout_freshness")),
                "trend_acceleration": round_or_none(metrics_payload.get("trend_acceleration")),
                "volume_expansion_quality": round_or_none(metrics_payload.get("volume_expansion_quality")),
                "close_strength": round_or_none(metrics_payload.get("close_strength")),
                "catalyst_freshness": round_or_none(metrics_payload.get("catalyst_freshness")),
                "overhead_supply_penalty": round_or_none(metrics_payload.get("overhead_supply_penalty")),
                "extension_without_room_penalty": round_or_none(metrics_payload.get("extension_without_room_penalty")),
                "layer_c_alignment": round_or_none(metrics_payload.get("layer_c_alignment")),
                "layer_c_avoid_penalty": round_or_none(metrics_payload.get("layer_c_avoid_penalty")),
                "next_open_return": round_or_none(outcome_row.get("next_open_return")),
                "next_high_return": round_or_none(outcome_row.get("next_high_return")),
                "next_close_return": round_or_none(outcome_row.get("next_close_return")),
                "false_negative_intraday_space": False,
                "false_negative_positive_close": False,
                "false_negative_recurring_pattern": False,
                "false_negative_any": False,
            }
        )

    daily_summary = {
        "trade_date": trade_date,
        "report_family": report_family,
        "evidence_status": evidence_status,
        "selection_target_count": target_summary.get("selection_target_count"),
        "research_target_count": target_summary.get("research_target_count"),
        "short_trade_target_count": target_summary.get("short_trade_target_count"),
        "short_trade_selected_count": target_summary.get("short_trade_selected_count"),
        "short_trade_near_miss_count": target_summary.get("short_trade_near_miss_count"),
        "short_trade_blocked_count": target_summary.get("short_trade_blocked_count"),
        "short_trade_rejected_count": target_summary.get("short_trade_rejected_count"),
        "delta_classification_counts": target_summary.get("delta_classification_counts", {}),
    }
    return rows, daily_summary


def attach_false_negative_flags(rows: list[dict[str, Any]], recurrent_tickers: set[str]) -> None:
    for row in rows:
        decision = row["short_trade_decision"]
        row["p1_archetypes"] = ""
        if decision not in {"rejected", "blocked", "near_miss"}:
            continue
        next_high_return = row.get("next_high_return")
        next_close_return = row.get("next_close_return")
        row["false_negative_intraday_space"] = next_high_return is not None and next_high_return >= FN_HIGH_THRESHOLD
        row["false_negative_positive_close"] = next_close_return is not None and next_close_return > 0
        row["false_negative_recurring_pattern"] = row["ticker"] in recurrent_tickers
        row["false_negative_any"] = any(
            [
                row["false_negative_intraday_space"],
                row["false_negative_positive_close"],
                row["false_negative_recurring_pattern"],
            ]
        )
        archetypes: list[str] = []
        if row["gate_score"] == "fail" and row["false_negative_intraday_space"]:
            archetypes.append("score_fail_but_high_works")
        if decision == "near_miss" and row["false_negative_intraday_space"]:
            archetypes.append("watch_only_but_tradable_intraday")
        if row["gate_structural"] == "fail" and row["false_negative_recurring_pattern"]:
            archetypes.append("structural_conflict_but_pattern_recurs")
        row["p1_archetypes"] = "|".join(archetypes)


def build_profitability_summary(path: Path) -> dict[str, Any]:
    data = load_json(path)
    industry_map = data.get("triple_fail_industry_fund_nonpositive", {})
    top_industries = sorted(industry_map.items(), key=lambda item: item[1], reverse=True)[:6]
    return {
        "trade_dates": data.get("trade_dates", []),
        "fund_nonpositive_with_profitability_scored": data.get("fund_nonpositive_with_profitability_scored"),
        "metric_fail_fund_nonpositive": data.get("metric_fail_fund_nonpositive", {}),
        "positive_count_0_fund_nonpositive": data.get("positive_count_0_fund_nonpositive"),
        "fail_combo_positive_count_0": data.get("fail_combo_positive_count_0", {}),
        "top_triple_fail_industries": [{"industry": name, "count": count} for name, count in top_industries],
    }


def build_report_family_diffs() -> list[dict[str, str]]:
    return [
        {
            "report_family": "brief",
            "grain": "单日、前瞻、execution-facing",
            "primary_question": "明天该盯哪只主入场票、哪只只适合观察",
            "what_it_preserves": "selected / near_miss 的执行语义、preferred_entry_mode、盘前动作建议",
            "what_it_cannot_prove": "没有已实现的 T+1/T+2 结果，不能当作机会质量回测",
        },
        {
            "report_family": "blocker_analysis",
            "grain": "窗口级、回放、failure-cluster facing",
            "primary_question": "当前 short-trade 流程主要堵在哪一层、哪种机制重复失败",
            "what_it_preserves": "selected / near_miss / blocked / rejected 计数、gate_status、failure_mechanism",
            "what_it_cannot_prove": "没有逐票 next_high / next_close outcome，不适合单独评价机会质量",
        },
        {
            "report_family": "pre_layer_outcome",
            "grain": "候选源级、机会质量、pre-Layer C",
            "primary_question": "不同 candidate source 在 T+1 是否给过空间",
            "what_it_preserves": "next_open / next_high / next_close 代理收益，用于 coverage-quality 对比",
            "what_it_cannot_prove": "不是最终 short-trade 决策结果，不能直接当作系统 selected 的真实执行表现",
        },
    ]


def build_problem_list(blocker: dict[str, Any], layer_b_summary: dict[str, Any], short_trade_summary: dict[str, Any], coverage_summary: dict[str, Any], profitability_summary: dict[str, Any]) -> list[dict[str, Any]]:
    top_blocked = blocker.get("top_blocked_examples", [])
    return [
        {
            "problem": "Replay baseline 的 short-trade coverage 实际塌缩",
            "evidence": f"{blocker['session_dual_target_summary']['short_trade_target_count']} 个 short-trade targets 里，selected=0、near_miss=0、blocked={blocker['session_dual_target_summary']['short_trade_blocked_count']}、rejected={blocker['session_dual_target_summary']['short_trade_rejected_count']}。",
        },
        {
            "problem": "Candidate-source 呈现明显 coverage-quality split",
            "evidence": f"layer_b_boundary: n={layer_b_summary['sample_count']}, high_hit@2%={layer_b_summary['next_high_hit_rate_at_2pct']}, close_pos={layer_b_summary['next_close_positive_rate']}; short_trade_boundary: n={short_trade_summary['sample_count']}, high_hit@2%={short_trade_summary['next_high_hit_rate_at_2pct']}, close_pos={short_trade_summary['next_close_positive_rate']}。",
        },
        {
            "problem": "单纯阈值扫描没有释放任何新增样本",
            "evidence": f"coverage variant 共测试 {coverage_summary['variant_count']} 个变体，selected 全为 0；主导过滤原因是 {coverage_summary['dominant_filtered_reason']['name']}={coverage_summary['dominant_filtered_reason']['count']}。",
        },
        {
            "problem": "结构冲突阻断集中在单一机制簇",
            "evidence": f"blocked 全部来自 {list(blocker.get('blocker_counts', {}).keys())}; 样本包括 {[item['ticker'] for item in top_blocked]}。",
        },
        {
            "problem": "profitability 对 BTST 活跃行业的压制需要单独处理",
            "evidence": f"fund_nonpositive 样本 {profitability_summary['fund_nonpositive_with_profitability_scored']} 个，三项全败 {profitability_summary['positive_count_0_fund_nonpositive']} 个，集中行业为 {[item['industry'] for item in profitability_summary['top_triple_fail_industries']]}。",
        },
        {
            "problem": "2026-03-27 目前只有 brief 级别的前瞻语义，尚未形成已实现 outcome",
            "evidence": "300757 / 601869 已有 selected / near_miss 语义，但还没有可回填的 next_high / next_close 结果。",
        },
    ]


def build_review_questions(problem_list: list[dict[str, Any]]) -> list[str]:
    return [
        "P1 先围绕哪一批 false negative 建 dossier：12 个 high>=2% 的 rejected/blocked，还是先看 recurring pattern（300724/300394/300502）？",
        "2026-03-27 是否在周会里单列为 forward brief day，而不是和 2026-03-23 到 2026-03-26 的 replay window 直接混算？",
        "P2 的 breakout 修正是否先限定在 breakout_freshness 使用方式，而不碰 catalyst / volume / profitability？",
        "blocked 样本后续是否需要补一份和 pre_layer_outcome 对齐的 outcome replay，避免结构冲突样本只能看静态解释？",
        f"当前基线问题单共 {len(problem_list)} 项，周会是否按 coverage、quality、structure、profitability、forward brief 五个主题分段审阅？",
    ]


def build_p0_check(summary_rows: list[dict[str, Any]], report_family_diffs: list[dict[str, str]]) -> dict[str, Any]:
    covered_trade_dates = sorted({row["trade_date"] for row in summary_rows})
    return {
        "taxonomy_defined": True,
        "sample_table_trade_dates": covered_trade_dates,
        "report_family_diffs_documented": bool(report_family_diffs),
        "ready_for_p1": True,
        "residual_risks": [
            "2026-03-27 仍是半完整样本，不能与 replay outcome 直接合并成同口径收益统计。",
            "blocked 样本在当前输入包里缺少统一的 next-day outcome 明细，只能先冻结 decision 语义与 blocker 机制。",
        ],
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    ordered_rows = sorted(rows, key=lambda row: (row["trade_date"], {"selected": 0, "near_miss": 1, "blocked": 2, "rejected": 3}.get(row["short_trade_decision"], 9), row["ticker"]))
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(ordered_rows)


def build_p1_seed_outputs(sample_rows: list[dict[str, Any]]) -> dict[str, Any]:
    main_entry_rows = [row for row in sample_rows if row["short_trade_decision"] == "selected"]
    watch_only_rows = [row for row in sample_rows if row["short_trade_decision"] == "near_miss"]
    false_negative_rows = [row for row in sample_rows if row["false_negative_any"]]

    write_csv(main_entry_rows, P1_MAIN_ENTRY_PATH)
    write_csv(watch_only_rows, P1_WATCH_ONLY_PATH)
    write_csv(false_negative_rows, P1_FALSE_NEGATIVE_PATH)

    archetype_counts = Counter()
    for row in false_negative_rows:
        for archetype in row["p1_archetypes"].split("|"):
            if archetype:
                archetype_counts[archetype] += 1

    summary = {
        "generated_on": "2026-03-30",
        "main_entry_count": len(main_entry_rows),
        "watch_only_count": len(watch_only_rows),
        "false_negative_count": len(false_negative_rows),
        "archetype_counts": dict(archetype_counts),
        "known_limitations": [
            "2026-03-27 的 main_entry / watch_only 仍是 forward brief 语义，还没有 T+1 outcome。",
            "watch_only_but_tradable_intraday archetype 当前还没有已实现样本，需等下一交易日或扩更多窗口。",
        ],
        "outputs": {
            "main_entry_table": str(P1_MAIN_ENTRY_PATH),
            "watch_only_table": str(P1_WATCH_ONLY_PATH),
            "false_negative_dossier": str(P1_FALSE_NEGATIVE_PATH),
        },
    }
    P1_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    outcome_index, layer_b_summary, short_trade_summary = load_outcome_index()
    blocker = load_json(BLOCKER_PATH)
    coverage_summary = parse_coverage_variant_report(COVERAGE_VARIANT_PATH)
    profitability_summary = build_profitability_summary(PROFITABILITY_PATH)
    brief_next_trade_date = parse_brief_next_trade_date(BRIEF_REPORT_PATH)

    sample_rows: list[dict[str, Any]] = []
    daily_summary: list[dict[str, Any]] = []

    for trade_date in ["2026-03-23", "2026-03-24", "2026-03-25", "2026-03-26"]:
        snapshot_path = REPLAY_ARTIFACT_ROOT / trade_date / "selection_snapshot.json"
        rows, summary = extract_short_trade_rows(snapshot_path, "replay_input_validation", "full_replay_window", None, outcome_index)
        sample_rows.extend(rows)
        daily_summary.append(summary)

    brief_rows, brief_summary = extract_short_trade_rows(BRIEF_SNAPSHOT_PATH, "next_day_trade_brief", "forward_brief_only", brief_next_trade_date, outcome_index)
    sample_rows.extend(brief_rows)
    daily_summary.append(brief_summary)

    recurrent_tickers = build_recurrent_ticker_set(blocker)
    attach_false_negative_flags(sample_rows, recurrent_tickers)

    report_family_diffs = build_report_family_diffs()
    problem_list = build_problem_list(blocker, layer_b_summary, short_trade_summary, coverage_summary, profitability_summary)
    review_questions = build_review_questions(problem_list)
    p0_check = build_p0_check(sample_rows, report_family_diffs)
    p1_seed_summary = build_p1_seed_outputs(sample_rows)

    write_csv(sample_rows, OUTPUT_CSV_PATH)

    payload = {
        "generated_on": "2026-03-30",
        "inputs": {
            "brief_report": str(BRIEF_REPORT_PATH),
            "blocker_report": str(BLOCKER_PATH),
            "layer_b_outcomes": str(LAYER_B_OUTCOME_PATH),
            "short_trade_outcomes": str(SHORT_TRADE_OUTCOME_PATH),
            "coverage_variants": str(COVERAGE_VARIANT_PATH),
            "profitability_breakdown": str(PROFITABILITY_PATH),
            "sample_table_csv": str(OUTPUT_CSV_PATH),
        },
        "taxonomy": TAXONOMY,
        "daily_summary": daily_summary,
        "baseline_metrics": {
            "coverage": {
                "replay_window_target_count": blocker["session_dual_target_summary"]["short_trade_target_count"],
                "replay_window_selected_count": blocker["session_dual_target_summary"]["short_trade_selected_count"],
                "replay_window_near_miss_count": blocker["session_dual_target_summary"]["short_trade_near_miss_count"],
                "replay_window_blocked_count": blocker["session_dual_target_summary"]["short_trade_blocked_count"],
                "replay_window_rejected_count": blocker["session_dual_target_summary"]["short_trade_rejected_count"],
                "brief_selected_count": brief_summary["short_trade_selected_count"],
                "brief_near_miss_count": brief_summary["short_trade_near_miss_count"],
            },
            "opportunity": {
                "layer_b_boundary": layer_b_summary,
                "short_trade_boundary": short_trade_summary,
            },
            "execution": {
                "gate_status_counts": blocker.get("gate_status_counts", {}),
                "brief_entry_modes": {
                    "selected": [row["preferred_entry_mode"] for row in sample_rows if row["trade_date"] == "2026-03-27" and row["short_trade_decision"] == "selected"],
                    "near_miss": [row["preferred_entry_mode"] for row in sample_rows if row["trade_date"] == "2026-03-27" and row["short_trade_decision"] == "near_miss"],
                },
            },
            "stability": {
                "layer_b_unique_ticker_count": layer_b_summary["unique_ticker_count"],
                "layer_b_ticker_frequency": layer_b_summary["ticker_frequency"],
                "layer_b_daily_stats": layer_b_summary["daily"],
                "brief_only_day_count": 1,
            },
            "learnability": {
                "failure_mechanism_counts": blocker.get("failure_mechanism_counts", {}),
                "top_blocked_examples": blocker.get("top_blocked_examples", []),
                "top_near_threshold_examples": blocker.get("top_near_threshold_examples", []),
                "false_negative_any_count": sum(1 for row in sample_rows if row["false_negative_any"]),
                "recurrent_tickers": sorted(recurrent_tickers),
            },
        },
        "coverage_variant_summary": coverage_summary,
        "profitability_summary": profitability_summary,
        "report_family_diffs": report_family_diffs,
        "problem_list": problem_list,
        "review_questions": review_questions,
        "p0_check": p0_check,
        "p1_seed_summary": p1_seed_summary,
    }

    OUTPUT_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    print(f"Wrote {OUTPUT_CSV_PATH}")
    print(f"Wrote {OUTPUT_JSON_PATH}")
    print(f"Wrote {P1_MAIN_ENTRY_PATH}")
    print(f"Wrote {P1_WATCH_ONLY_PATH}")
    print(f"Wrote {P1_FALSE_NEGATIVE_PATH}")
    print(f"Wrote {P1_SUMMARY_PATH}")
    print(f"Rows in sample table: {len(sample_rows)}")
    print(f"Replay targets: {blocker['session_dual_target_summary']['short_trade_target_count']}, brief targets: {brief_summary['short_trade_target_count']}")


if __name__ == "__main__":
    main()
