from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_btst_carryover_selected_cohort import (
    _deduplicate_case_rows,
    _iter_case_rows,
    _peer_evidence_status,
)
from scripts.btst_analysis_utils import extract_btst_price_outcome, summarize_distribution


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_low_sample_penalty_audit_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_low_sample_penalty_audit_latest.md"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _attach_penalty_context(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        snapshot = _load_json(Path(str(row.get("snapshot_path") or "")))
        ticker = str(row.get("ticker") or "")
        payload = dict((dict(snapshot.get("selection_targets") or {}).get(ticker) or {}))
        short_trade = dict(payload.get("short_trade") or {})
        metrics_payload = dict(short_trade.get("metrics_payload") or {})
        weighted_negative_contributions = dict(metrics_payload.get("weighted_negative_contributions") or {})
        stale_penalty_contribution = _safe_float(weighted_negative_contributions.get("stale_trend_repair_penalty"))
        extension_penalty_contribution = _safe_float(weighted_negative_contributions.get("extension_without_room_penalty"))
        counterfactual_without_stale_extension = min(
            1.0,
            max(
                0.0,
                _safe_float(row.get("score_target")) + stale_penalty_contribution + extension_penalty_contribution,
            ),
        )
        enriched.append(
            {
                **row,
                "peer_evidence_status": _peer_evidence_status(row),
                "stale_trend_repair_penalty": metrics_payload.get("stale_trend_repair_penalty"),
                "extension_without_room_penalty": metrics_payload.get("extension_without_room_penalty"),
                "total_negative_contribution": metrics_payload.get("total_negative_contribution"),
                "stale_penalty_contribution": round(stale_penalty_contribution, 4),
                "extension_penalty_contribution": round(extension_penalty_contribution, 4),
                "counterfactual_score_without_stale_extension": round(counterfactual_without_stale_extension, 4),
                "counterfactual_gap_to_near_miss": round(
                    _safe_float(short_trade.get("effective_near_miss_threshold")) - counterfactual_without_stale_extension,
                    4,
                ),
                "counterfactual_gap_to_selected": round(
                    _safe_float(short_trade.get("effective_select_threshold")) - counterfactual_without_stale_extension,
                    4,
                ),
                "negative_tags": list(short_trade.get("negative_tags") or []),
                "rejection_reasons": list(short_trade.get("rejection_reasons") or []),
            }
        )
    return enriched


def _attach_outcomes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    price_cache: dict[tuple[str, str], Any] = {}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        outcome = extract_btst_price_outcome(str(row.get("ticker") or ""), str(row.get("trade_date") or ""), price_cache)
        enriched.append({**row, **outcome})
    return enriched


def _summarize_closed_cycle(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed_rows = [row for row in rows if row.get("t_plus_2_close_return") is not None]
    next_close_returns = [float(row["next_close_return"]) for row in closed_rows if row.get("next_close_return") is not None]
    t_plus_2_returns = [float(row["t_plus_2_close_return"]) for row in closed_rows if row.get("t_plus_2_close_return") is not None]
    return {
        "closed_cycle_count": len(closed_rows),
        "next_close_positive_rate": None if not closed_rows else round(sum(1 for value in next_close_returns if value > 0) / len(closed_rows), 4),
        "t_plus_2_close_positive_rate": None if not closed_rows else round(sum(1 for value in t_plus_2_returns if value > 0) / len(closed_rows), 4),
        "next_close_return_distribution": summarize_distribution(next_close_returns),
        "t_plus_2_close_return_distribution": summarize_distribution(t_plus_2_returns),
    }


def _build_recommendation(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    closed_rows = [row for row in rows if row.get("t_plus_2_close_return") is not None]
    if not closed_rows:
        return "当前 low-sample broad-family-only 样本还没有足够 closed-cycle 数据，先继续观察，不做策略放松。"
    promotable_counterfactual_rows = [
        row for row in closed_rows if float(row.get("counterfactual_score_without_stale_extension") or 0.0) >= float(row.get("effective_near_miss_threshold") or 0.0)
    ]
    if promotable_counterfactual_rows and all(float(row.get("next_close_return") or 0.0) <= 0.0 for row in promotable_counterfactual_rows):
        return "即使移除 stale/extension penalty，这批 low-sample broad-family-only 样本也只会更早进入观察/准入，但已闭环收益没有兑现，说明 penalty 更像在保护胜率。"
    if summary.get("t_plus_2_close_positive_rate") is not None and float(summary["t_plus_2_close_positive_rate"]) <= 0.0:
        return "low-sample broad-family-only carryover 样本的 T+2 兑现为负，现阶段不支持放松 penalty。"
    return "low-sample broad-family-only 样本仍需更多 closed-cycle 证据，当前不应因为单一 counterfactual 就调整策略。"


def analyze_btst_low_sample_penalty_audit(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    deduped_rows = _deduplicate_case_rows(_iter_case_rows(resolved_reports_root))
    candidate_rows = [
        row
        for row in deduped_rows
        if str(row.get("historical_execution_quality_label") or "") == "close_continuation"
        and str(row.get("historical_entry_timing_bias") or "") == "confirm_then_hold"
        and int(row.get("historical_evaluable_count") or 0) <= 1
        and str(row.get("decision") or "") != "selected"
    ]
    penalty_rows = _attach_outcomes(_attach_penalty_context(candidate_rows))
    audited_rows = [
        row for row in penalty_rows if str(row.get("peer_evidence_status") or "") in {"broad_family_only", "no_peer_support"}
    ]
    audited_rows.sort(key=lambda row: (float(row.get("gap_to_selected") or 999.0), str(row.get("trade_date") or ""), str(row.get("ticker") or "")))
    closed_cycle_summary = _summarize_closed_cycle(audited_rows)
    return {
        "reports_root": str(resolved_reports_root),
        "audited_case_count": len(audited_rows),
        "peer_status_counts": dict(Counter(str(row.get("peer_evidence_status") or "unknown") for row in audited_rows)),
        "closed_cycle_summary": closed_cycle_summary,
        "rows": audited_rows,
        "recommendation": _build_recommendation(audited_rows, closed_cycle_summary),
    }


def render_btst_low_sample_penalty_audit_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Low-Sample Penalty Audit")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- audited_case_count: {analysis.get('audited_case_count')}")
    lines.append(f"- peer_status_counts: {analysis.get('peer_status_counts')}")
    lines.append(f"- closed_cycle_summary: {analysis.get('closed_cycle_summary')}")
    lines.append("")
    lines.append("## Audited Rows")
    for row in list(analysis.get("rows") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, peer_evidence_status={row.get('peer_evidence_status')}, "
            f"score_target={row.get('score_target')}, stale_penalty={row.get('stale_trend_repair_penalty')}, extension_penalty={row.get('extension_without_room_penalty')}, "
            f"stale_penalty_contribution={row.get('stale_penalty_contribution')}, extension_penalty_contribution={row.get('extension_penalty_contribution')}, "
            f"counterfactual_score_without_stale_extension={row.get('counterfactual_score_without_stale_extension')}, "
            f"counterfactual_gap_to_near_miss={row.get('counterfactual_gap_to_near_miss')}, next_close_return={row.get('next_close_return')}, "
            f"t_plus_2_close_return={row.get('t_plus_2_close_return')}, rejection_reasons={row.get('rejection_reasons')}"
        )
    if not list(analysis.get("rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit low-sample penalty behavior for carryover close-continuation BTST candidates.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_low_sample_penalty_audit(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_low_sample_penalty_audit_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
