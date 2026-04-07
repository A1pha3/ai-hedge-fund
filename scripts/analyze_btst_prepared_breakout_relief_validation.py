from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_MERGE_REPLAY_VALIDATION_PATH = REPORTS_DIR / "btst_merge_replay_validation_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_prepared_breakout_relief_validation_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_prepared_breakout_relief_validation_latest.md"
RELIEF_FIELDS: tuple[str, ...] = (
    "prepared_breakout_penalty_relief",
    "prepared_breakout_catalyst_relief",
    "prepared_breakout_volume_relief",
    "prepared_breakout_continuation_relief",
    "prepared_breakout_selected_catalyst_relief",
)


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _count_values(values: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        token = str(value or "").strip() or "unknown"
        counts[token] = counts.get(token, 0) + 1
    return counts


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _score_stats(values: list[Any]) -> dict[str, float | None]:
    numeric_values = [float(value) for value in values if isinstance(value, (int, float))]
    return {
        "min": round(min(numeric_values), 4) if numeric_values else None,
        "max": round(max(numeric_values), 4) if numeric_values else None,
        "mean": _mean(numeric_values),
    }


def _resolve_focus_candidate(candidate_summaries: list[dict[str, Any]], focus_ticker: str | None) -> dict[str, Any]:
    if focus_ticker:
        matched = next((row for row in candidate_summaries if str(row.get("focus_ticker") or "") == str(focus_ticker)), None)
        if matched is None:
            raise ValueError(f"Ticker not found in merge replay validation: {focus_ticker}")
        return matched

    ranked = sorted(
        candidate_summaries,
        key=lambda row: (
            int(row.get("prepared_breakout_selected_catalyst_relief_applied_count") or 0),
            int(row.get("prepared_breakout_continuation_relief_applied_count") or 0),
            int(row.get("prepared_breakout_volume_relief_applied_count") or 0),
            int(row.get("prepared_breakout_catalyst_relief_applied_count") or 0),
            int(row.get("prepared_breakout_penalty_relief_applied_count") or 0),
            int(row.get("promoted_to_selected_count") or 0),
            str(row.get("focus_ticker") or ""),
        ),
        reverse=True,
    )
    if not ranked:
        raise ValueError("No candidate_summaries were found in merge replay validation report.")
    return ranked[0]


def _build_outcome_support_summary(dossier: dict[str, Any]) -> dict[str, Any]:
    if not dossier:
        return {
            "evidence_status": "missing_candidate_dossier",
            "candidate_row_count": 0,
            "recent_window_count": 0,
            "recent_validation_verdict": None,
            "next_high_hit_rate_at_threshold": None,
            "next_close_positive_rate": None,
            "next_close_return_mean": None,
            "t_plus_2_close_positive_rate": None,
            "t_plus_2_close_return_mean": None,
        }

    surface = dict(dossier.get("tier_focus_surface_summary") or {})
    t_plus_2_distribution = dict(surface.get("t_plus_2_close_return_distribution") or {})
    next_close_distribution = dict(surface.get("next_close_return_distribution") or {})
    next_high_hit_rate = surface.get("next_high_hit_rate_at_threshold")
    next_close_positive_rate = surface.get("next_close_positive_rate")

    if next_high_hit_rate is not None and next_close_positive_rate is not None and float(next_high_hit_rate) >= 0.6 and float(next_close_positive_rate) >= 0.6:
        evidence_status = "strong_t1_t2_support"
    elif next_close_positive_rate is not None and float(next_close_positive_rate) >= 0.6:
        evidence_status = "close_support_only"
    elif next_high_hit_rate is not None and float(next_high_hit_rate) >= 0.6:
        evidence_status = "intraday_support_only"
    elif next_high_hit_rate is None and next_close_positive_rate is None:
        evidence_status = "missing_outcome_surface"
    else:
        evidence_status = "weak_outcome_support"

    return {
        "evidence_status": evidence_status,
        "candidate_row_count": int(dossier.get("candidate_row_count") or 0),
        "recent_window_count": int(dossier.get("recent_window_count") or 0),
        "recent_validation_verdict": dossier.get("recent_validation_verdict"),
        "promotion_readiness_verdict": dossier.get("promotion_readiness_verdict"),
        "next_high_hit_rate_at_threshold": next_high_hit_rate,
        "next_close_positive_rate": next_close_positive_rate,
        "next_close_return_mean": next_close_distribution.get("mean"),
        "t_plus_2_close_positive_rate": surface.get("t_plus_2_close_positive_rate"),
        "t_plus_2_close_return_mean": t_plus_2_distribution.get("mean"),
    }


def analyze_btst_prepared_breakout_relief_validation(
    reports_root: str | Path,
    *,
    focus_ticker: str | None = None,
    merge_replay_validation_path: str | Path | None = None,
    candidate_dossier_path: str | Path | None = None,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    merge_report_path = Path(merge_replay_validation_path or (resolved_reports_root / DEFAULT_MERGE_REPLAY_VALIDATION_PATH.name)).expanduser().resolve()
    merge_validation = _load_json(merge_report_path)
    candidate_summaries = [dict(row or {}) for row in list(merge_validation.get("candidate_summaries") or [])]
    focus_summary = _resolve_focus_candidate(candidate_summaries, focus_ticker)
    resolved_focus_ticker = str(focus_summary.get("focus_ticker") or "")

    dossier_path = Path(candidate_dossier_path or (resolved_reports_root / f"btst_tplus2_candidate_dossier_{resolved_focus_ticker}_latest.json")).expanduser().resolve()
    dossier = _load_json(dossier_path) if dossier_path.exists() else {}

    raw_rows = [dict(row or {}) for row in list(focus_summary.get("rows") or [])]
    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        reliefs = {field: bool(row.get(f"{field}_applied")) for field in RELIEF_FIELDS}
        rows.append(
            {
                "report_label": row.get("report_label"),
                "report_dir": row.get("report_dir"),
                "trade_date": row.get("trade_date"),
                "baseline_replayed_decision": row.get("baseline_replayed_decision"),
                "merge_replayed_decision": row.get("merge_replayed_decision"),
                "baseline_replayed_score_target": row.get("baseline_replayed_score_target"),
                "merge_replayed_score_target": row.get("merge_replayed_score_target"),
                "required_score_uplift_to_selected": row.get("required_score_uplift_to_selected"),
                "remaining_leverage_classification": row.get("remaining_leverage_classification"),
                "recommended_primary_lever": row.get("recommended_primary_lever"),
                "reliefs": reliefs,
            }
        )

    baseline_decisions = _count_values([row.get("baseline_replayed_decision") for row in rows])
    merge_decisions = _count_values([row.get("merge_replayed_decision") for row in rows])
    remaining_leverage_counts = _count_values([row.get("remaining_leverage_classification") for row in rows])
    recommended_primary_lever_counts = _count_values([row.get("recommended_primary_lever") for row in rows])
    relief_applied_window_counts = {
        field: sum(1 for row in rows if row["reliefs"].get(field)) for field in RELIEF_FIELDS
    }
    selected_window_count = merge_decisions.get("selected", 0)
    selected_relief_window_count = relief_applied_window_counts["prepared_breakout_selected_catalyst_relief"]
    selected_relief_selected_alignment_count = sum(
        1
        for row in rows
        if row["reliefs"].get("prepared_breakout_selected_catalyst_relief") and row.get("merge_replayed_decision") == "selected"
    )
    row_count = len(rows)
    all_rows_selected = row_count > 0 and selected_window_count == row_count

    outcome_support = _build_outcome_support_summary(dossier)
    if row_count == 0:
        verdict = "missing_prepared_breakout_windows"
        recommendation = "No prepared-breakout windows were found for the focus ticker."
    elif selected_relief_window_count == 0:
        verdict = "selected_relief_not_observed"
        recommendation = "Keep collecting prepared-breakout windows; the selected catalyst relief has not appeared yet."
    elif selected_relief_selected_alignment_count != selected_relief_window_count:
        verdict = "selected_relief_alignment_broken"
        recommendation = "Do not broaden the uplift yet; some selected-relief windows still fail to land in selected."
    elif all_rows_selected and outcome_support["evidence_status"] in {"strong_t1_t2_support", "close_support_only", "intraday_support_only"}:
        verdict = "prepared_breakout_selected_relief_supported"
        recommendation = (
            f"{resolved_focus_ticker} currently shows stable prepared-breakout selected relief across observed windows "
            f"with {outcome_support['evidence_status']}."
        )
    elif all_rows_selected:
        verdict = "prepared_breakout_selected_relief_needs_more_outcome_evidence"
        recommendation = "The replay side is stable, but more realized outcome evidence is still needed before generalizing the uplift."
    else:
        verdict = "prepared_breakout_selected_relief_window_mixed"
        recommendation = "Keep the uplift isolated; multi-window replay still shows mixed decision quality."

    return {
        "reports_root": str(resolved_reports_root),
        "merge_replay_validation_path": str(merge_report_path),
        "candidate_dossier_path": str(dossier_path) if dossier_path.exists() else None,
        "focus_ticker": resolved_focus_ticker,
        "row_count": row_count,
        "candidate_recommendation": focus_summary.get("candidate_recommendation"),
        "recommended_signal_levers": list(focus_summary.get("recommended_signal_levers") or []),
        "baseline_decision_counts": baseline_decisions,
        "merge_decision_counts": merge_decisions,
        "remaining_leverage_counts": remaining_leverage_counts,
        "recommended_primary_lever_counts": recommended_primary_lever_counts,
        "relief_applied_window_counts": relief_applied_window_counts,
        "selected_window_count": selected_window_count,
        "selected_relief_window_count": selected_relief_window_count,
        "selected_relief_selected_alignment_count": selected_relief_selected_alignment_count,
        "selected_relief_alignment_rate": round(selected_relief_selected_alignment_count / selected_relief_window_count, 4) if selected_relief_window_count else None,
        "merge_score_target_stats": _score_stats([row.get("merge_replayed_score_target") for row in rows]),
        "baseline_score_target_stats": _score_stats([row.get("baseline_replayed_score_target") for row in rows]),
        "required_score_uplift_to_selected_stats": _score_stats([row.get("required_score_uplift_to_selected") for row in rows]),
        "outcome_support": outcome_support,
        "verdict": verdict,
        "recommendation": recommendation,
        "rows": rows,
    }


def render_btst_prepared_breakout_relief_validation_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Prepared-Breakout Relief Validation")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- focus_ticker: {analysis['focus_ticker']}")
    lines.append(f"- merge_replay_validation_path: {analysis['merge_replay_validation_path']}")
    lines.append(f"- candidate_dossier_path: {analysis.get('candidate_dossier_path')}")
    lines.append(f"- row_count: {analysis['row_count']}")
    lines.append("")
    lines.append("## Replay Stability")
    lines.append(f"- baseline_decision_counts: {analysis['baseline_decision_counts']}")
    lines.append(f"- merge_decision_counts: {analysis['merge_decision_counts']}")
    lines.append(f"- remaining_leverage_counts: {analysis['remaining_leverage_counts']}")
    lines.append(f"- recommended_primary_lever_counts: {analysis['recommended_primary_lever_counts']}")
    lines.append(f"- relief_applied_window_counts: {analysis['relief_applied_window_counts']}")
    lines.append(f"- selected_relief_alignment_rate: {analysis['selected_relief_alignment_rate']}")
    lines.append(f"- merge_score_target_stats: {analysis['merge_score_target_stats']}")
    lines.append(f"- required_score_uplift_to_selected_stats: {analysis['required_score_uplift_to_selected_stats']}")
    lines.append("")
    lines.append("## Outcome Support")
    lines.append(f"- outcome_support: {analysis['outcome_support']}")
    lines.append("")
    lines.append("## Window Details")
    for row in list(analysis.get("rows") or []):
        lines.append(
            f"- {row.get('report_label') or row.get('trade_date')}: "
            f"baseline={row.get('baseline_replayed_decision')} merge={row.get('merge_replayed_decision')} "
            f"merge_score={row.get('merge_replayed_score_target')} "
            f"uplift_to_selected={row.get('required_score_uplift_to_selected')} "
            f"remaining_leverage={row.get('remaining_leverage_classification')} "
            f"recommended_primary_lever={row.get('recommended_primary_lever')} "
            f"reliefs={row.get('reliefs')}"
        )
    if not list(analysis.get("rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Verdict")
    lines.append(f"- verdict: {analysis['verdict']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate prepared-breakout BTST relief stability for a focus ticker across replay windows.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--focus-ticker", default="")
    parser.add_argument("--merge-replay-validation-path", default=str(DEFAULT_MERGE_REPLAY_VALIDATION_PATH))
    parser.add_argument("--candidate-dossier-path", default="")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_prepared_breakout_relief_validation(
        args.reports_root,
        focus_ticker=str(args.focus_ticker or "").strip() or None,
        merge_replay_validation_path=args.merge_replay_validation_path,
        candidate_dossier_path=str(args.candidate_dossier_path or "").strip() or None,
    )

    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_prepared_breakout_relief_validation_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
