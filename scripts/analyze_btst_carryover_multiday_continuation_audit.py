from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_btst_carryover_selected_cohort import _deduplicate_case_rows, _is_supportive, _iter_case_rows, _peer_evidence_status
from scripts.analyze_btst_selected_outcome_proof import _extract_holding_outcome, _summarize_evidence_rows, analyze_btst_selected_outcome_proof


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_carryover_multiday_continuation_audit_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_carryover_multiday_continuation_audit_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def _resolve_latest_selected_snapshot(reports_root: Path) -> Path:
    refresh_board_path = reports_root / "btst_selected_outcome_refresh_board_latest.json"
    if refresh_board_path.exists():
        refresh_board = _load_json(refresh_board_path)
        snapshot_path = Path(str(refresh_board.get("snapshot_path") or "")).expanduser()
        if snapshot_path.exists():
            return snapshot_path.resolve()

    selected_candidates: list[tuple[str, Path]] = []
    for snapshot_path in sorted(reports_root.glob("**/selection_artifacts/*/selection_snapshot.json")):
        snapshot = _load_json(snapshot_path)
        selection_targets = dict(snapshot.get("selection_targets") or {})
        if any(str(dict(payload.get("short_trade") or {}).get("decision") or "") == "selected" for payload in selection_targets.values()):
            selected_candidates.append((str(snapshot.get("trade_date") or snapshot_path.parent.name), snapshot_path))
    if not selected_candidates:
        raise FileNotFoundError(f"No selected selection_snapshot.json found under {reports_root}")
    selected_candidates.sort(key=lambda item: (item[0], str(item[1])))
    return selected_candidates[-1][1]


def _build_supportive_cohort_rows(reports_root: Path) -> list[dict[str, Any]]:
    deduped_rows = _deduplicate_case_rows(_iter_case_rows(reports_root))
    supportive_rows = [row for row in deduped_rows if _is_supportive(row)]
    price_cache: dict[tuple[str, str], Any] = {}
    enriched_rows: list[dict[str, Any]] = []
    for row in supportive_rows:
        outcome = _extract_holding_outcome(str(row.get("ticker") or ""), str(row.get("trade_date") or ""), price_cache)
        enriched_rows.append({**row, **outcome, "peer_evidence_status": _peer_evidence_status(row)})
    return enriched_rows


def _build_policy_checks(
    *,
    selected_proof: dict[str, Any],
    cohort_rows: list[dict[str, Any]],
    broad_family_only_summary: dict[str, Any],
    aligned_peer_summary: dict[str, Any],
) -> dict[str, Any]:
    selected_summary = dict(selected_proof.get("summary") or {})
    selected_t2 = selected_summary.get("t_plus_2_close_positive_rate")
    selected_t3 = selected_summary.get("t_plus_3_close_positive_rate")
    broad_next_close = broad_family_only_summary.get("next_close_positive_rate")
    broad_t2 = broad_family_only_summary.get("t_plus_2_close_positive_rate")
    aligned_t3 = aligned_peer_summary.get("t_plus_3_close_positive_rate")
    aligned_t4 = aligned_peer_summary.get("t_plus_4_close_positive_rate")

    return {
        "selected_path_t2_bias_only": bool(
            selected_summary.get("evidence_case_count")
            and selected_t2 is not None
            and float(selected_t2) >= 0.5
            and (selected_t3 is None or float(selected_t3) < 0.5)
        ),
        "broad_family_only_multiday_unsupported": bool(
            broad_family_only_summary.get("evidence_case_count")
            and (broad_next_close is None or float(broad_next_close) <= 0.0)
            and (broad_t2 is None or float(broad_t2) <= 0.0)
        ),
        "aligned_peer_multiday_ready": bool(
            aligned_peer_summary.get("evidence_case_count", 0) >= 2
            and aligned_t3 is not None
            and aligned_t4 is not None
            and float(aligned_t3) >= 0.5
            and float(aligned_t4) >= 0.5
        ),
        "open_selected_case_count": sum(1 for row in cohort_rows if str(row.get("decision") or "") == "selected" and str(row.get("cycle_status") or "").startswith("missing_")),
    }


def _build_policy_recommendations(policy_checks: dict[str, Any], *, selected_ticker: str, broad_family_only_count: int, aligned_peer_count: int) -> list[str]:
    recommendations: list[str] = []
    if policy_checks.get("selected_path_t2_bias_only"):
        recommendations.append(
            f"{selected_ticker} 的 formal selected 历史 proof 仍只支持 T+2 bias，不应把这条 lane 包装成稳定 T+3/T+4 continuation。"
        )
    if broad_family_only_count > 0 and policy_checks.get("broad_family_only_multiday_unsupported"):
        recommendations.append("broad_family_only supportive case 不应获得多日 continuation 合约语义，更不应成为放宽 selected frontier 的依据。")
    if aligned_peer_count <= 0:
        recommendations.append("当前还没有 closed-cycle aligned peer 可以证明这条 carryover lane 具备可扩展的多日 continuation 赔率。")
    elif not policy_checks.get("aligned_peer_multiday_ready"):
        recommendations.append("已有 aligned peer 线索，但 closed-cycle 仍不足以证明 T+3/T+4 continuation ready。")
    if int(policy_checks.get("open_selected_case_count") or 0) > 0:
        recommendations.append("当前 live formal selected 仍有 open case，等 next-day/T+2 闭环后再判断是否需要改动 selected 规则。")
    return recommendations


def _build_recommendation(
    *,
    selected_proof: dict[str, Any],
    policy_checks: dict[str, Any],
    policy_recommendations: list[str],
) -> str:
    if policy_recommendations:
        return "；".join(policy_recommendations)
    selected_summary = dict(selected_proof.get("summary") or {})
    if int(selected_summary.get("evidence_case_count") or 0) <= 0:
        return "当前 formal selected 缺少可复核的 historical proof，先不要讨论多日 continuation。"
    return "当前没有额外的多日 continuation 风险信号，但样本仍少，应继续积累 closed-cycle 证据。"


def analyze_btst_carryover_multiday_continuation_audit(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    latest_snapshot_path = _resolve_latest_selected_snapshot(resolved_reports_root)
    selected_proof = analyze_btst_selected_outcome_proof(latest_snapshot_path)
    cohort_rows = _build_supportive_cohort_rows(resolved_reports_root)

    broad_family_only_rows = [row for row in cohort_rows if str(row.get("peer_evidence_status") or "") == "broad_family_only"]
    aligned_peer_rows = [
        row
        for row in cohort_rows
        if str(row.get("peer_evidence_status") or "") in {"aligned_peer_ready", "aligned_family_source_score_ready", "same_ticker_ready"}
    ]
    selected_or_relief_rows = [row for row in cohort_rows if str(row.get("decision") or "") == "selected" or bool(row.get("relief_applied"))]

    broad_family_only_summary = _summarize_evidence_rows(broad_family_only_rows, next_high_hit_threshold=0.02)
    aligned_peer_summary = _summarize_evidence_rows(aligned_peer_rows, next_high_hit_threshold=0.02)
    selected_or_relief_summary = _summarize_evidence_rows(selected_or_relief_rows, next_high_hit_threshold=0.02)

    policy_checks = _build_policy_checks(
        selected_proof=selected_proof,
        cohort_rows=cohort_rows,
        broad_family_only_summary=broad_family_only_summary,
        aligned_peer_summary=aligned_peer_summary,
    )
    policy_recommendations = _build_policy_recommendations(
        policy_checks,
        selected_ticker=str(selected_proof.get("ticker") or ""),
        broad_family_only_count=len(broad_family_only_rows),
        aligned_peer_count=len(aligned_peer_rows),
    )

    return {
        "reports_root": str(resolved_reports_root),
        "selected_snapshot_path": str(latest_snapshot_path),
        "selected_ticker": selected_proof.get("ticker"),
        "selected_trade_date": selected_proof.get("trade_date"),
        "supportive_case_count": len(cohort_rows),
        "peer_status_counts": dict(Counter(str(row.get("peer_evidence_status") or "") for row in cohort_rows)),
        "selected_historical_proof_summary": dict(selected_proof.get("summary") or {}),
        "selected_or_relief_cohort_summary": selected_or_relief_summary,
        "broad_family_only_summary": broad_family_only_summary,
        "aligned_peer_summary": aligned_peer_summary,
        "policy_checks": policy_checks,
        "policy_recommendations": policy_recommendations,
        "selected_historical_proof_rows": list(selected_proof.get("evidence_rows") or []),
        "supportive_cohort_rows": cohort_rows,
        "recommendation": _build_recommendation(
            selected_proof=selected_proof,
            policy_checks=policy_checks,
            policy_recommendations=policy_recommendations,
        ),
    }


def render_btst_carryover_multiday_continuation_audit_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover Multiday Continuation Audit")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- selected_ticker: {analysis.get('selected_ticker')}")
    lines.append(f"- selected_trade_date: {analysis.get('selected_trade_date')}")
    lines.append(f"- supportive_case_count: {analysis.get('supportive_case_count')}")
    lines.append(f"- peer_status_counts: {analysis.get('peer_status_counts')}")
    lines.append("")
    lines.append("## Selected Historical Proof Summary")
    lines.append(f"- {analysis.get('selected_historical_proof_summary')}")
    lines.append("")
    lines.append("## Selected or Relief Cohort Summary")
    lines.append(f"- {analysis.get('selected_or_relief_cohort_summary')}")
    lines.append("")
    lines.append("## Broad Family Only Summary")
    lines.append(f"- {analysis.get('broad_family_only_summary')}")
    lines.append("")
    lines.append("## Aligned Peer Summary")
    lines.append(f"- {analysis.get('aligned_peer_summary')}")
    lines.append("")
    lines.append("## Policy Checks")
    lines.append(f"- {analysis.get('policy_checks')}")
    lines.append("")
    lines.append("## Policy Recommendations")
    for recommendation in list(analysis.get("policy_recommendations") or []):
        lines.append(f"- {recommendation}")
    if not list(analysis.get("policy_recommendations") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Selected Historical Proof Rows")
    for row in list(analysis.get("selected_historical_proof_rows") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: next_close_return={row.get('next_close_return')}, "
            f"t_plus_2_close_return={row.get('t_plus_2_close_return')}, t_plus_3_close_return={row.get('t_plus_3_close_return')}, "
            f"t_plus_4_close_return={row.get('t_plus_4_close_return')}, cycle_status={row.get('cycle_status')}"
        )
    if not list(analysis.get("selected_historical_proof_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Supportive Cohort Rows")
    for row in list(analysis.get("supportive_cohort_rows") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, relief_applied={row.get('relief_applied')}, "
            f"peer_evidence_status={row.get('peer_evidence_status')}, next_close_return={row.get('next_close_return')}, "
            f"t_plus_2_close_return={row.get('t_plus_2_close_return')}, t_plus_3_close_return={row.get('t_plus_3_close_return')}, "
            f"t_plus_4_close_return={row.get('t_plus_4_close_return')}, cycle_status={row.get('cycle_status')}"
        )
    if not list(analysis.get("supportive_cohort_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit whether carryover BTST evidence really supports T+3/T+4 continuation or only a T+2-biased holding contract.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_carryover_multiday_continuation_audit(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_carryover_multiday_continuation_audit_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
