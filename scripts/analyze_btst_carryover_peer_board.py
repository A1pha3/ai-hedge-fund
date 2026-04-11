from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_btst_carryover_selected_cohort import (
    _attach_outcomes,
    _deduplicate_case_rows,
    _is_supportive,
    _iter_case_rows,
)


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_carryover_peer_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_carryover_peer_board_latest.md"

ALIGNED_PEER_STATUSES = {
    "aligned_family_source_score_ready",
    "aligned_peer_ready",
}


def _candidate_rank(row: dict[str, Any]) -> tuple[float, int, float, str, str]:
    return (
        float(row.get("gap_to_selected") or 999.0),
        -int(row.get("historical_evaluable_count") or 0),
        -float(row.get("score_target") or 0.0),
        str(row.get("trade_date") or ""),
        str(row.get("ticker") or ""),
    )


def _build_recommendation(
    *,
    aligned_candidates: list[dict[str, Any]],
    broad_family_only_candidates: list[dict[str, Any]],
    same_ticker_ready_rows: list[dict[str, Any]],
) -> str:
    if aligned_candidates:
        top = aligned_candidates[0]
        return (
            f"已出现 aligned carryover peer 候选 {top.get('ticker')}@{top.get('trade_date')}，"
            "下一步应优先验证其 closed-cycle 质量和 recent-window 稳定性，再决定是否进入极窄 promotion review。"
        )
    if broad_family_only_candidates:
        top = broad_family_only_candidates[0]
        return (
            f"当前最接近扩样的是 {top.get('ticker')}@{top.get('trade_date')}，但它只有 broad family 样本，"
            "没有 aligned family/source peer。下一步应先补 peer evidence 对齐，不能靠继续放松 carryover selected frontier 来扩容。"
        )
    if same_ticker_ready_rows:
        return "当前 carryover peer board 只剩 same-ticker 已验证样本，说明这条路径仍停留在单票模板阶段，应继续积累同类窗口。"
    return "当前没有可用 carryover peer 扩样对象，先继续积累 supportive close-continuation 样本。"


def analyze_btst_carryover_peer_board(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    raw_rows = _iter_case_rows(resolved_reports_root)
    deduped_rows = _deduplicate_case_rows(raw_rows)
    enriched_rows = _attach_outcomes(deduped_rows)
    supportive_rows = [row for row in enriched_rows if _is_supportive(row)]
    aligned_candidates, broad_family_only_candidates, same_ticker_ready_rows = _partition_peer_candidates(supportive_rows)
    return _build_peer_board_analysis(
        resolved_reports_root=resolved_reports_root,
        raw_rows=raw_rows,
        deduped_rows=deduped_rows,
        supportive_rows=supportive_rows,
        aligned_candidates=aligned_candidates,
        broad_family_only_candidates=broad_family_only_candidates,
        same_ticker_ready_rows=same_ticker_ready_rows,
    )


def _partition_peer_candidates(
    supportive_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        sorted(
            [
                row
                for row in supportive_rows
                if str(row.get("peer_evidence_status") or "") in ALIGNED_PEER_STATUSES and str(row.get("decision") or "") != "selected"
            ],
            key=_candidate_rank,
        ),
        sorted(
            [
                row
                for row in supportive_rows
                if str(row.get("peer_evidence_status") or "") == "broad_family_only" and str(row.get("decision") or "") != "selected"
            ],
            key=_candidate_rank,
        ),
        sorted(
            [row for row in supportive_rows if str(row.get("peer_evidence_status") or "") == "same_ticker_ready"],
            key=lambda row: (str(row.get("trade_date") or ""), str(row.get("ticker") or "")),
        ),
    )


def _build_peer_board_analysis(
    *,
    resolved_reports_root: Path,
    raw_rows: list[dict[str, Any]],
    deduped_rows: list[dict[str, Any]],
    supportive_rows: list[dict[str, Any]],
    aligned_candidates: list[dict[str, Any]],
    broad_family_only_candidates: list[dict[str, Any]],
    same_ticker_ready_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "reports_root": str(resolved_reports_root),
        "raw_case_count": len(raw_rows),
        "unique_case_count": len(deduped_rows),
        "supportive_case_count": len(supportive_rows),
        "peer_status_counts": dict(Counter(str(row.get("peer_evidence_status") or "unknown") for row in supportive_rows)),
        "aligned_candidate_count": len(aligned_candidates),
        "broad_family_only_count": len(broad_family_only_candidates),
        "same_ticker_ready_count": len(same_ticker_ready_rows),
        "aligned_candidates": aligned_candidates[:10],
        "broad_family_only_candidates": broad_family_only_candidates[:10],
        "same_ticker_ready_rows": same_ticker_ready_rows[:10],
        "recommendation": _build_recommendation(
            aligned_candidates=aligned_candidates,
            broad_family_only_candidates=broad_family_only_candidates,
            same_ticker_ready_rows=same_ticker_ready_rows,
        ),
    }


def render_btst_carryover_peer_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover Peer Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- raw_case_count: {analysis.get('raw_case_count')}")
    lines.append(f"- unique_case_count: {analysis.get('unique_case_count')}")
    lines.append(f"- supportive_case_count: {analysis.get('supportive_case_count')}")
    lines.append(f"- peer_status_counts: {analysis.get('peer_status_counts')}")
    lines.append(f"- aligned_candidate_count: {analysis.get('aligned_candidate_count')}")
    lines.append(f"- broad_family_only_count: {analysis.get('broad_family_only_count')}")
    lines.append(f"- same_ticker_ready_count: {analysis.get('same_ticker_ready_count')}")
    lines.append("")
    lines.append("## Aligned Candidates")
    for row in list(analysis.get("aligned_candidates") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, "
            f"peer_evidence_status={row.get('peer_evidence_status')}, gap_to_selected={row.get('gap_to_selected')}, "
            f"same_family_source_sample_count={row.get('same_family_source_sample_count')}, "
            f"same_family_source_score_catalyst_sample_count={row.get('same_family_source_score_catalyst_sample_count')}, "
            f"same_source_score_sample_count={row.get('same_source_score_sample_count')}"
        )
    if not list(analysis.get("aligned_candidates") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Broad Family Only Candidates")
    for row in list(analysis.get("broad_family_only_candidates") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, "
            f"gap_to_selected={row.get('gap_to_selected')}, same_ticker_sample_count={row.get('same_ticker_sample_count')}, "
            f"same_family_sample_count={row.get('same_family_sample_count')}, "
            f"same_family_source_sample_count={row.get('same_family_source_sample_count')}, "
            f"same_source_score_sample_count={row.get('same_source_score_sample_count')}, "
            f"next_close_return={row.get('next_close_return')}, t_plus_2_close_return={row.get('t_plus_2_close_return')}"
        )
    if not list(analysis.get("broad_family_only_candidates") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Same-Ticker Ready Rows")
    for row in list(analysis.get("same_ticker_ready_rows") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, "
            f"peer_evidence_status={row.get('peer_evidence_status')}, same_ticker_sample_count={row.get('same_ticker_sample_count')}, "
            f"same_family_source_sample_count={row.get('same_family_source_sample_count')}, "
            f"same_family_source_score_catalyst_sample_count={row.get('same_family_source_score_catalyst_sample_count')}"
        )
    if not list(analysis.get("same_ticker_ready_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze carryover peer-evidence readiness for BTST close-continuation candidates.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_carryover_peer_board(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_carryover_peer_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
