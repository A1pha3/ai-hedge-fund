from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import extract_btst_price_outcome, summarize_distribution


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_carryover_selected_cohort_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_carryover_selected_cohort_latest.md"
RELIEF_REASON = "catalyst_theme_short_trade_carryover"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _decision_rank(decision: str | None) -> int:
    return {
        "selected": 3,
        "near_miss": 2,
        "blocked": 1,
        "rejected": 0,
    }.get(str(decision or "").strip(), -1)


def _extract_case_row(snapshot_path: Path, ticker: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    short_trade = dict((payload or {}).get("short_trade") or {})
    if not short_trade:
        return None

    explainability = dict(short_trade.get("explainability_payload") or {})
    replay_context = dict(explainability.get("replay_context") or {})
    historical_prior = dict(explainability.get("historical_prior") or replay_context.get("historical_prior") or {})
    upstream_relief = dict(explainability.get("upstream_shadow_catalyst_relief") or {})
    short_trade_catalyst_relief = dict(replay_context.get("short_trade_catalyst_relief") or {})
    candidate_reason_codes = [str(code) for code in list(replay_context.get("candidate_reason_codes") or []) if str(code or "").strip()]
    relief_reason = str(upstream_relief.get("reason") or short_trade_catalyst_relief.get("reason") or "").strip()

    if relief_reason != RELIEF_REASON and "catalyst_theme_short_trade_carryover_candidate" not in candidate_reason_codes:
        return None

    metrics_payload = dict(short_trade.get("metrics_payload") or {})
    thresholds = dict(metrics_payload.get("thresholds") or {})
    trade_date = str(snapshot_path.parent.name)
    score_target = _safe_float(short_trade.get("score_target"))
    effective_select_threshold = _safe_float(
        short_trade.get("effective_select_threshold")
        or upstream_relief.get("effective_select_threshold")
        or thresholds.get("effective_select_threshold")
        or 0.58
    )
    selected_score_tolerance = _safe_float(
        short_trade.get("selected_score_tolerance")
        or thresholds.get("selected_score_tolerance")
        or upstream_relief.get("selected_score_tolerance")
        or 0.0
    )

    return {
        "trade_date": trade_date,
        "ticker": str(ticker),
        "report_dir": str(snapshot_path.parents[2]),
        "snapshot_path": str(snapshot_path),
        "decision": str(short_trade.get("decision") or ""),
        "candidate_source": str(short_trade.get("candidate_source") or ""),
        "preferred_entry_mode": str(short_trade.get("preferred_entry_mode") or ""),
        "score_target": round(score_target, 4),
        "effective_select_threshold": round(effective_select_threshold, 4),
        "selected_score_tolerance": round(selected_score_tolerance, 4),
        "gap_to_selected": round(effective_select_threshold - score_target, 4),
        "selected_within_tolerance": score_target >= (effective_select_threshold - selected_score_tolerance),
        "relief_reason": relief_reason,
        "relief_applied": bool(upstream_relief.get("applied")),
        "candidate_reason_codes": candidate_reason_codes,
        "top_reasons": [str(reason) for reason in list(short_trade.get("top_reasons") or []) if str(reason or "").strip()],
        "blockers": [str(reason) for reason in list(short_trade.get("blockers") or []) if str(reason or "").strip()],
        "historical_execution_quality_label": str(historical_prior.get("execution_quality_label") or ""),
        "historical_entry_timing_bias": str(historical_prior.get("entry_timing_bias") or ""),
        "historical_applied_scope": str(historical_prior.get("applied_scope") or ""),
        "historical_sample_count": int(historical_prior.get("sample_count") or 0),
        "historical_evaluable_count": int(historical_prior.get("evaluable_count") or 0),
        "historical_next_high_hit_rate_at_threshold": historical_prior.get("next_high_hit_rate_at_threshold"),
        "historical_next_close_positive_rate": historical_prior.get("next_close_positive_rate"),
        "historical_next_close_return_mean": historical_prior.get("next_close_return_mean"),
        "historical_next_open_to_close_return_mean": historical_prior.get("next_open_to_close_return_mean"),
        "same_ticker_sample_count": int(historical_prior.get("same_ticker_sample_count") or 0),
        "same_family_sample_count": int(historical_prior.get("same_family_sample_count") or 0),
        "same_family_source_sample_count": int(historical_prior.get("same_family_source_sample_count") or 0),
        "same_family_source_score_catalyst_sample_count": int(historical_prior.get("same_family_source_score_catalyst_sample_count") or 0),
        "same_source_score_sample_count": int(historical_prior.get("same_source_score_sample_count") or 0),
    }


def _iter_case_rows(reports_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for snapshot_path in sorted(reports_root.glob("**/selection_artifacts/*/selection_snapshot.json")):
        snapshot = _load_json(snapshot_path)
        for ticker, payload in dict(snapshot.get("selection_targets") or {}).items():
            row = _extract_case_row(snapshot_path, str(ticker), dict(payload or {}))
            if row is not None:
                rows.append(row)
    return rows


def _deduplicate_case_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("trade_date") or ""), str(row.get("ticker") or ""))
        current = deduped.get(key)
        if current is None:
            deduped[key] = row
            continue
        rank = (
            _decision_rank(row.get("decision")),
            1 if row.get("relief_applied") else 0,
            int(row.get("historical_evaluable_count") or 0),
            -float(row.get("gap_to_selected") or 999.0),
            float(row.get("score_target") or -999.0),
            str(row.get("report_dir") or ""),
        )
        current_rank = (
            _decision_rank(current.get("decision")),
            1 if current.get("relief_applied") else 0,
            int(current.get("historical_evaluable_count") or 0),
            -float(current.get("gap_to_selected") or 999.0),
            float(current.get("score_target") or -999.0),
            str(current.get("report_dir") or ""),
        )
        if rank > current_rank:
            deduped[key] = row
    return sorted(deduped.values(), key=lambda row: (str(row.get("trade_date") or ""), str(row.get("ticker") or "")))


def _is_supportive(row: dict[str, Any]) -> bool:
    return (
        str(row.get("historical_execution_quality_label") or "") == "close_continuation"
        and str(row.get("historical_entry_timing_bias") or "") == "confirm_then_hold"
        and _safe_float(row.get("historical_next_close_positive_rate"), default=-1.0) >= 0.5
    )


def _peer_evidence_status(row: dict[str, Any]) -> str:
    same_ticker_sample_count = int(row.get("same_ticker_sample_count") or 0)
    same_family_source_sample_count = int(row.get("same_family_source_sample_count") or 0)
    same_family_source_score_catalyst_sample_count = int(row.get("same_family_source_score_catalyst_sample_count") or 0)
    same_source_score_sample_count = int(row.get("same_source_score_sample_count") or 0)
    same_family_sample_count = int(row.get("same_family_sample_count") or 0)

    if same_ticker_sample_count >= 2:
        return "same_ticker_ready"
    if same_family_source_score_catalyst_sample_count > 0:
        return "aligned_family_source_score_ready"
    if same_family_source_sample_count > 0 or same_source_score_sample_count > 0:
        return "aligned_peer_ready"
    if same_family_sample_count > 0:
        return "broad_family_only"
    return "no_peer_support"


def _attach_outcomes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    price_cache: dict[tuple[str, str], Any] = {}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        outcome = extract_btst_price_outcome(str(row.get("ticker") or ""), str(row.get("trade_date") or ""), price_cache)
        enriched.append({**row, **outcome, "peer_evidence_status": _peer_evidence_status(row)})
    return enriched


def _summarize_outcomes(rows: list[dict[str, Any]], *, next_high_hit_threshold: float = 0.02) -> dict[str, Any]:
    next_day_rows = [row for row in rows if row.get("next_close_return") is not None]
    closed_rows = [row for row in rows if row.get("t_plus_2_close_return") is not None]
    next_high_returns = [float(row["next_high_return"]) for row in next_day_rows if row.get("next_high_return") is not None]
    next_close_returns = [float(row["next_close_return"]) for row in next_day_rows if row.get("next_close_return") is not None]
    t_plus_2_returns = [float(row["t_plus_2_close_return"]) for row in closed_rows if row.get("t_plus_2_close_return") is not None]
    return {
        "case_count": len(rows),
        "next_day_available_count": len(next_day_rows),
        "t_plus_2_available_count": len(closed_rows),
        "next_high_hit_rate_at_threshold": None if not next_day_rows else round(sum(1 for value in next_high_returns if value >= next_high_hit_threshold) / len(next_day_rows), 4),
        "next_close_positive_rate": None if not next_day_rows else round(sum(1 for value in next_close_returns if value > 0) / len(next_day_rows), 4),
        "t_plus_2_close_positive_rate": None if not closed_rows else round(sum(1 for value in t_plus_2_returns if value > 0) / len(closed_rows), 4),
        "next_high_return_distribution": summarize_distribution(next_high_returns),
        "next_close_return_distribution": summarize_distribution(next_close_returns),
        "t_plus_2_close_return_distribution": summarize_distribution(t_plus_2_returns),
    }


def _build_top_expansion_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if _is_supportive(row)
        and not row.get("relief_applied")
        and str(row.get("decision") or "") != "selected"
    ]
    candidates.sort(
        key=lambda row: (
            float(row.get("gap_to_selected") or 999.0),
            -int(row.get("historical_evaluable_count") or 0),
            -float(row.get("historical_next_close_positive_rate") or 0.0),
            -float(row.get("score_target") or 0.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        )
    )
    return candidates[:10]


def _build_recommendation(*, supportive_rows: list[dict[str, Any]], applied_rows: list[dict[str, Any]], top_expansion_candidates: list[dict[str, Any]]) -> str:
    if not supportive_rows:
        return "当前没有任何 strong carryover supportive cohort，默认结论应是继续收集样本，不要再主动放松 selected frontier。"
    if top_expansion_candidates:
        top_candidate = top_expansion_candidates[0]
        if int(top_candidate.get("historical_evaluable_count") or 0) < 2:
            if str(top_candidate.get("peer_evidence_status") or "") == "broad_family_only":
                return (
                    f"当前最接近 002001 扩样路径的是 {top_candidate.get('ticker')}@{top_candidate.get('trade_date')}，"
                    "但它只有 broad family 级别的外围样本，没有 aligned family/source peer，且 same_ticker evaluable_count 仍不足。"
                    "下一步应优先补 peer evidence 对齐，而不是继续放松 selected frontier。"
                )
            return (
                f"当前最接近 002001 扩样路径的是 {top_candidate.get('ticker')}@{top_candidate.get('trade_date')}，"
                "但它的主阻塞仍是 historical evaluable_count 不足，而不是 score frontier。本阶段应优先扩同票/同类历史样本，而不是继续放松阈值。"
            )
        return (
            f"{top_candidate.get('ticker')}@{top_candidate.get('trade_date')} 已具备继续复核价值，"
            "可作为下一批 carryover selected promotion 的重点候选。"
        )
    if applied_rows:
        return "当前 applied carryover relief 仍主要集中在极少数样本上，应继续扩 supportive cohort，而不是把单票成功经验推广成宽松规则。"
    return "当前 strong carryover supportive 样本存在，但没有形成可直接推广的 false negative 候选，下一步重点仍应是扩充 cohort。"


def analyze_btst_carryover_selected_cohort(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    raw_rows = _iter_case_rows(resolved_reports_root)
    deduped_rows = _deduplicate_case_rows(raw_rows)
    enriched_rows = _attach_outcomes(deduped_rows)
    supportive_rows = [row for row in enriched_rows if _is_supportive(row)]
    applied_rows = [row for row in enriched_rows if row.get("relief_applied")]
    top_expansion_candidates = _build_top_expansion_candidates(enriched_rows)

    return {
        "reports_root": str(resolved_reports_root),
        "raw_case_count": len(raw_rows),
        "unique_case_count": len(deduped_rows),
        "decision_counts": dict(Counter(str(row.get("decision") or "") for row in enriched_rows)),
        "relief_applied_count": len(applied_rows),
        "supportive_case_count": len(supportive_rows),
        "supportive_decision_counts": dict(Counter(str(row.get("decision") or "") for row in supportive_rows)),
        "applied_relief_summary": _summarize_outcomes(applied_rows),
        "supportive_summary": _summarize_outcomes(supportive_rows),
        "applied_relief_rows": applied_rows,
        "top_expansion_candidates": top_expansion_candidates,
        "recommendation": _build_recommendation(
            supportive_rows=supportive_rows,
            applied_rows=applied_rows,
            top_expansion_candidates=top_expansion_candidates,
        ),
    }


def render_btst_carryover_selected_cohort_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover Selected Cohort")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- raw_case_count: {analysis.get('raw_case_count')}")
    lines.append(f"- unique_case_count: {analysis.get('unique_case_count')}")
    lines.append(f"- decision_counts: {analysis.get('decision_counts')}")
    lines.append(f"- relief_applied_count: {analysis.get('relief_applied_count')}")
    lines.append(f"- supportive_case_count: {analysis.get('supportive_case_count')}")
    lines.append(f"- supportive_decision_counts: {analysis.get('supportive_decision_counts')}")
    lines.append("")
    lines.append("## Applied Relief Summary")
    lines.append(f"- {analysis.get('applied_relief_summary')}")
    lines.append("")
    lines.append("## Supportive Summary")
    lines.append(f"- {analysis.get('supportive_summary')}")
    lines.append("")
    lines.append("## Applied Relief Rows")
    for row in list(analysis.get("applied_relief_rows") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, score_target={row.get('score_target')}, gap_to_selected={row.get('gap_to_selected')}, next_close_return={row.get('next_close_return')}, t_plus_2_close_return={row.get('t_plus_2_close_return')}, historical_evaluable_count={row.get('historical_evaluable_count')}"
        )
    if not list(analysis.get("applied_relief_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Top Expansion Candidates")
    for row in list(analysis.get("top_expansion_candidates") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, score_target={row.get('score_target')}, gap_to_selected={row.get('gap_to_selected')}, next_close_return={row.get('next_close_return')}, t_plus_2_close_return={row.get('t_plus_2_close_return')}, historical_sample_count={row.get('historical_sample_count')}, historical_evaluable_count={row.get('historical_evaluable_count')}, peer_evidence_status={row.get('peer_evidence_status')}, same_ticker_sample_count={row.get('same_ticker_sample_count')}, same_family_sample_count={row.get('same_family_sample_count')}, same_family_source_sample_count={row.get('same_family_source_sample_count')}, same_family_source_score_catalyst_sample_count={row.get('same_family_source_score_catalyst_sample_count')}, same_source_score_sample_count={row.get('same_source_score_sample_count')}, top_reasons={row.get('top_reasons')}"
        )
    if not list(analysis.get("top_expansion_candidates") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze historical carryover-selected cohort quality for BTST.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_carryover_selected_cohort(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_carryover_selected_cohort_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
