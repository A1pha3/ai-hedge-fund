from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_btst_carryover_selected_cohort import _deduplicate_case_rows, _is_supportive, _iter_case_rows
from scripts.analyze_btst_selected_outcome_proof import _extract_holding_outcome, _summarize_evidence_rows


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_carryover_horizon_validation_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_carryover_horizon_validation_latest.md"


def _build_recommendation(
    *,
    supportive_summary: dict[str, Any],
    selected_summary: dict[str, Any],
    rejected_summary: dict[str, Any],
) -> str:
    supportive_t3 = supportive_summary.get("t_plus_3_close_positive_rate")
    supportive_t4 = supportive_summary.get("t_plus_4_close_positive_rate")
    selected_t2 = selected_summary.get("t_plus_2_close_positive_rate")
    rejected_t2 = rejected_summary.get("t_plus_2_close_positive_rate")

    if supportive_summary.get("evidence_case_count", 0) <= 0:
        return "当前没有可评估的 supportive carryover horizon 样本，先继续积累 closed-cycle 数据。"
    if supportive_t3 is not None and float(supportive_t3) >= 0.5 and supportive_t4 is not None and float(supportive_t4) >= 0.5:
        return "当前 supportive carryover 样本已表现出可研究的 T+3/T+4 延续质量，可以继续验证多日 continuation 赔率。"
    if selected_t2 is not None and float(selected_t2) >= 0.5 and (rejected_t2 is None or float(rejected_t2) <= 0.0):
        return "当前 carryover lane 更像是 selected/apply-relief 才能支撑到 T+2，rejected supportive 样本并不支持把这条路径外推到 T+3/T+4。"
    return "当前 carryover lane 的 closed-cycle 样本尚不足以支持稳定的 T+3/T+4 预期，主线仍应以次日确认后持有到 T+2 为上限。"


def analyze_btst_carryover_horizon_validation(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    deduped_rows = _deduplicate_case_rows(_iter_case_rows(resolved_reports_root))
    supportive_rows = [row for row in deduped_rows if _is_supportive(row)]

    price_cache: dict[tuple[str, str], Any] = {}
    evidence_rows: list[dict[str, Any]] = []
    for row in supportive_rows:
        outcome = _extract_holding_outcome(str(row.get("ticker") or ""), str(row.get("trade_date") or ""), price_cache)
        evidence_rows.append({**row, **outcome})

    selected_rows = [row for row in evidence_rows if str(row.get("decision") or "") == "selected" or bool(row.get("relief_applied"))]
    rejected_rows = [row for row in evidence_rows if str(row.get("decision") or "") != "selected" and not bool(row.get("relief_applied"))]

    supportive_summary = _summarize_evidence_rows(evidence_rows, next_high_hit_threshold=0.02)
    selected_summary = _summarize_evidence_rows(selected_rows, next_high_hit_threshold=0.02)
    rejected_summary = _summarize_evidence_rows(rejected_rows, next_high_hit_threshold=0.02)

    return {
        "reports_root": str(resolved_reports_root),
        "supportive_case_count": len(supportive_rows),
        "decision_counts": dict(Counter(str(row.get("decision") or "") for row in supportive_rows)),
        "supportive_summary": supportive_summary,
        "selected_or_relief_summary": selected_summary,
        "rejected_supportive_summary": rejected_summary,
        "evidence_rows": evidence_rows,
        "recommendation": _build_recommendation(
            supportive_summary=supportive_summary,
            selected_summary=selected_summary,
            rejected_summary=rejected_summary,
        ),
    }


def render_btst_carryover_horizon_validation_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover Horizon Validation")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- supportive_case_count: {analysis.get('supportive_case_count')}")
    lines.append(f"- decision_counts: {analysis.get('decision_counts')}")
    lines.append("")
    lines.append("## Supportive Summary")
    lines.append(f"- {analysis.get('supportive_summary')}")
    lines.append("")
    lines.append("## Selected or Relief Summary")
    lines.append(f"- {analysis.get('selected_or_relief_summary')}")
    lines.append("")
    lines.append("## Rejected Supportive Summary")
    lines.append(f"- {analysis.get('rejected_supportive_summary')}")
    lines.append("")
    lines.append("## Evidence Rows")
    for row in list(analysis.get("evidence_rows") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, relief_applied={row.get('relief_applied')}, "
            f"next_close_return={row.get('next_close_return')}, t_plus_2_close_return={row.get('t_plus_2_close_return')}, "
            f"t_plus_3_close_return={row.get('t_plus_3_close_return')}, t_plus_4_close_return={row.get('t_plus_4_close_return')}, "
            f"cycle_status={row.get('cycle_status')}"
        )
    if not list(analysis.get("evidence_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate T+2/T+3/T+4 horizon quality for supportive carryover BTST candidates.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_carryover_horizon_validation(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_carryover_horizon_validation_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
