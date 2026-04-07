from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.analyze_btst_prepared_breakout_relief_validation import RELIEF_FIELDS, _build_outcome_support_summary
from scripts.btst_report_utils import discover_nested_report_dirs
from scripts.replay_selection_target_calibration import analyze_selection_target_replay_sources, load_selection_target_replay_sources

REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_prepared_breakout_cohort_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_prepared_breakout_cohort_latest.md"
WINDOW_KEY_PATTERN = re.compile(r"paper_trading_window_(\d{8})_(\d{8})")
REFERENCE_TICKER = "300505"

VERDICT_PRIORITY = {
    "stable_selected_relief_peer": 0,
    "prepared_breakout_selected_frontier": 1,
    "prepared_breakout_watchlist_peer": 2,
    "prepared_breakout_rejected_surface": 3,
}
OUTCOME_SUPPORT_PRIORITY = {
    "strong_t1_t2_support": 3,
    "close_support_only": 2,
    "intraday_support_only": 1,
    "weak_outcome_support": 0,
    "missing_outcome_surface": -1,
    "missing_candidate_dossier": -2,
}


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


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


def _extract_window_key(report_name: str) -> str:
    matched = WINDOW_KEY_PATTERN.search(str(report_name))
    if not matched:
        return str(report_name)
    return f"{matched.group(1)}_{matched.group(2)}"


def _resolve_report_dir_from_replay_input(replay_input_path: str | Path) -> Path:
    resolved = Path(replay_input_path).expanduser().resolve()
    if resolved.name == "selection_target_replay_input.json" and len(resolved.parents) >= 3:
        return resolved.parents[2]
    return resolved.parent


def _load_candidate_dossier(reports_root: Path, ticker: str) -> dict[str, Any]:
    dossier_path = reports_root / f"btst_tplus2_candidate_dossier_{ticker}_latest.json"
    if not dossier_path.exists():
        return {}
    return _load_json(dossier_path)


def _resolve_relief_flags(metrics_payload: dict[str, Any]) -> dict[str, bool]:
    return {
        field: bool(dict(metrics_payload.get(field) or {}).get("applied"))
        for field in RELIEF_FIELDS
    }


def _collect_prepared_breakout_rows(
    report_dirs: list[Path],
    *,
    profile_name: str,
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    replay_input_count = 0
    for report_dir in report_dirs:
        replay_sources = load_selection_target_replay_sources(report_dir)
        replay_input_count += len(replay_sources)
        tickers = sorted(
            {
                str(ticker or "").strip()
                for _, payload in replay_sources
                for ticker in list((payload.get("selection_targets") or {}).keys())
                if str(ticker or "").strip()
            }
        )
        if not tickers:
            continue
        analysis = analyze_selection_target_replay_sources(
            replay_sources,
            profile_name=profile_name,
            focus_tickers=tickers,
        )
        for row in list(analysis.get("focused_score_diagnostics") or []):
            metrics_payload = dict(row.get("replayed_metrics_payload") or {})
            candidate_source = str(row.get("candidate_source") or "")
            reliefs = _resolve_relief_flags(metrics_payload)
            breakout_stage = str(metrics_payload.get("breakout_stage") or "")
            if candidate_source != "layer_c_watchlist":
                continue
            if breakout_stage != "prepared_breakout" and not any(reliefs.values()):
                continue

            resolved_report_dir = _resolve_report_dir_from_replay_input(row.get("replay_input_path") or "")
            rows.append(
                {
                    "ticker": str(row.get("ticker") or ""),
                    "trade_date": row.get("trade_date"),
                    "report_dir": str(resolved_report_dir),
                    "report_label": resolved_report_dir.name,
                    "window_key": _extract_window_key(resolved_report_dir.name),
                    "candidate_source": candidate_source,
                    "candidate_reason_codes": list(row.get("candidate_reason_codes") or []),
                    "breakout_stage": breakout_stage,
                    "replayed_decision": row.get("replayed_decision"),
                    "stored_decision": row.get("stored_decision"),
                    "replayed_score_target": row.get("replayed_score_target"),
                    "replayed_gap_to_near_miss": row.get("replayed_gap_to_near_miss"),
                    "replayed_gap_to_selected": row.get("replayed_gap_to_selected"),
                    "delta_classification": row.get("delta_classification"),
                    "replayed_top_reasons": list(row.get("replayed_top_reasons") or []),
                    "replayed_blockers": list(row.get("replayed_blockers") or []),
                    "replayed_gate_status": dict(row.get("replayed_gate_status") or {}),
                    "reliefs": reliefs,
                }
            )
    return rows, replay_input_count


def _build_candidate_summary(ticker: str, rows: list[dict[str, Any]], *, reports_root: Path) -> dict[str, Any]:
    decision_counts = Counter(str(row.get("replayed_decision") or "unknown") for row in rows)
    relief_window_counts = {
        field: sum(1 for row in rows if row["reliefs"].get(field))
        for field in RELIEF_FIELDS
    }
    selected_relief_window_count = relief_window_counts["prepared_breakout_selected_catalyst_relief"]
    selected_relief_alignment_count = sum(
        1
        for row in rows
        if row["reliefs"].get("prepared_breakout_selected_catalyst_relief") and row.get("replayed_decision") == "selected"
    )
    selected_relief_alignment_rate = round(selected_relief_alignment_count / selected_relief_window_count, 4) if selected_relief_window_count else None
    distinct_report_count = len({str(row.get("report_label") or "") for row in rows})
    distinct_window_count = len({str(row.get("window_key") or "") for row in rows})
    distinct_trade_date_count = len({str(row.get("trade_date") or "") for row in rows})
    score_stats = _score_stats([row.get("replayed_score_target") for row in rows])
    gap_to_selected_stats = _score_stats([row.get("replayed_gap_to_selected") for row in rows])
    dossier = _load_candidate_dossier(reports_root, ticker)
    outcome_support = _build_outcome_support_summary(dossier)
    row_count = len(rows)
    selected_count = decision_counts.get("selected", 0)
    near_miss_count = decision_counts.get("near_miss", 0)
    all_rows_selected = row_count > 0 and selected_count == row_count
    min_gap_to_selected = gap_to_selected_stats.get("min")

    if ticker == REFERENCE_TICKER and all_rows_selected and selected_relief_window_count == row_count:
        verdict = "reference_selected_relief_anchor"
        recommendation = "Use this ticker as the prepared-breakout anchor sample; it already demonstrates the full five-stage relief path."
    elif all_rows_selected and selected_relief_window_count == row_count:
        verdict = "stable_selected_relief_peer"
        recommendation = f"{ticker} already behaves like a stable prepared-breakout selected-relief peer under the current profile."
    elif near_miss_count > 0 and min_gap_to_selected is not None and float(min_gap_to_selected) <= 0.12:
        verdict = "prepared_breakout_selected_frontier"
        recommendation = f"{ticker} is the closest non-anchor prepared-breakout frontier; validate whether its remaining selected gap is safe to close."
    elif near_miss_count > 0 or selected_count > 0:
        verdict = "prepared_breakout_watchlist_peer"
        recommendation = f"{ticker} shows repeat prepared-breakout watchlist behavior, but still needs better selected conversion quality."
    else:
        verdict = "prepared_breakout_rejected_surface"
        recommendation = f"{ticker} remains a prepared-breakout replay surface without enough near-miss/selected quality to justify widening the uplift."

    non_selected_gaps = [
        float(row["replayed_gap_to_selected"])
        for row in rows
        if row.get("replayed_decision") != "selected" and isinstance(row.get("replayed_gap_to_selected"), (int, float))
    ]

    return {
        "ticker": ticker,
        "row_count": row_count,
        "distinct_report_count": distinct_report_count,
        "distinct_window_count": distinct_window_count,
        "distinct_trade_date_count": distinct_trade_date_count,
        "decision_counts": dict(decision_counts),
        "relief_applied_window_counts": relief_window_counts,
        "selected_relief_window_count": selected_relief_window_count,
        "selected_relief_alignment_count": selected_relief_alignment_count,
        "selected_relief_alignment_rate": selected_relief_alignment_rate,
        "score_target_stats": score_stats,
        "required_score_uplift_to_selected_stats": gap_to_selected_stats,
        "minimum_required_score_uplift_to_selected_non_selected": round(min(non_selected_gaps), 4) if non_selected_gaps else None,
        "outcome_support": outcome_support,
        "latest_trade_date": max((str(row.get("trade_date") or "") for row in rows), default=None),
        "sample_report_labels": sorted({str(row.get("report_label") or "") for row in rows})[:8],
        "verdict": verdict,
        "recommendation": recommendation,
        "rows": sorted(rows, key=lambda row: (str(row.get("trade_date") or ""), str(row.get("ticker") or ""))),
    }


def _candidate_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    verdict = str(row.get("verdict") or "")
    outcome_support = dict(row.get("outcome_support") or {})
    decision_counts = dict(row.get("decision_counts") or {})
    gap_stats = dict(row.get("required_score_uplift_to_selected_stats") or {})
    return (
        VERDICT_PRIORITY.get(verdict, 99),
        -(int(row.get("selected_relief_window_count") or 0)),
        -(float(row.get("selected_relief_alignment_rate") or 0.0)),
        -int(decision_counts.get("selected", 0)),
        -int(decision_counts.get("near_miss", 0)),
        float(gap_stats.get("min")) if isinstance(gap_stats.get("min"), (int, float)) else 999.0,
        -OUTCOME_SUPPORT_PRIORITY.get(str(outcome_support.get("evidence_status") or ""), -99),
        -int(row.get("distinct_window_count") or 0),
        str(row.get("ticker") or ""),
    )


def analyze_btst_prepared_breakout_cohort(
    reports_root: str | Path,
    *,
    report_name_contains: str = "paper_trading_window",
    profile_name: str = "default",
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    report_dirs = discover_nested_report_dirs([resolved_reports_root], report_name_contains=report_name_contains)
    rows, replay_input_count = _collect_prepared_breakout_rows(report_dirs, profile_name=profile_name)

    rows_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            rows_by_ticker[ticker].append(row)

    candidate_rows = [
        _build_candidate_summary(ticker, ticker_rows, reports_root=resolved_reports_root)
        for ticker, ticker_rows in rows_by_ticker.items()
    ]
    candidate_rows.sort(key=_candidate_sort_key)

    reference_anchor = next((row for row in candidate_rows if row.get("ticker") == REFERENCE_TICKER), None)
    non_anchor_candidates = [row for row in candidate_rows if row.get("ticker") != REFERENCE_TICKER]
    next_candidate = non_anchor_candidates[0] if non_anchor_candidates else None

    stable_selected_relief_candidate_count = sum(1 for row in non_anchor_candidates if row.get("verdict") == "stable_selected_relief_peer")
    selected_frontier_candidate_count = sum(1 for row in non_anchor_candidates if row.get("verdict") == "prepared_breakout_selected_frontier")
    watchlist_peer_candidate_count = sum(1 for row in non_anchor_candidates if row.get("verdict") == "prepared_breakout_watchlist_peer")
    rejected_surface_candidate_count = sum(1 for row in non_anchor_candidates if row.get("verdict") == "prepared_breakout_rejected_surface")

    if next_candidate is None:
        verdict = "anchor_only_no_second_peer"
        recommendation = "Current replay evidence still supports keeping the prepared-breakout uplift anchored on 300505; no second peer is strong enough yet."
    elif next_candidate.get("verdict") == "stable_selected_relief_peer":
        verdict = "stable_selected_relief_peer_found"
        recommendation = f"{next_candidate['ticker']} is the strongest non-anchor peer; validate false-positive risk before broadening the selected-relief lane."
    elif next_candidate.get("verdict") == "prepared_breakout_selected_frontier":
        verdict = "selected_frontier_peer_found"
        recommendation = f"{next_candidate['ticker']} is the next prepared-breakout frontier to validate after 300505; its remaining selected gap is the tightest in the cohort."
    elif next_candidate.get("verdict") == "prepared_breakout_watchlist_peer":
        verdict = "watchlist_peer_only"
        recommendation = f"{next_candidate['ticker']} is the best remaining watchlist peer, but the cohort still lacks another strong selected-relief copy."
    else:
        verdict = "anchor_only_no_actionable_peer"
        recommendation = f"{next_candidate['ticker']} is the least-bad residual prepared-breakout surface, but it still sits too far below selected to justify broadening the uplift beyond 300505."

    return {
        "reports_root": str(resolved_reports_root),
        "report_name_contains": report_name_contains,
        "profile_name": profile_name,
        "report_dir_count": len(report_dirs),
        "replay_input_count": replay_input_count,
        "prepared_breakout_row_count": len(rows),
        "candidate_count": len(candidate_rows),
        "stable_selected_relief_candidate_count": stable_selected_relief_candidate_count,
        "selected_frontier_candidate_count": selected_frontier_candidate_count,
        "watchlist_peer_candidate_count": watchlist_peer_candidate_count,
        "rejected_surface_candidate_count": rejected_surface_candidate_count,
        "reference_anchor": reference_anchor,
        "next_candidate": next_candidate,
        "verdict": verdict,
        "recommendation": recommendation,
        "candidates": candidate_rows,
    }


def render_btst_prepared_breakout_cohort_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Prepared-Breakout Cohort Scan")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- reports_root: {analysis['reports_root']}")
    lines.append(f"- report_name_contains: {analysis['report_name_contains']}")
    lines.append(f"- profile_name: {analysis['profile_name']}")
    lines.append(f"- report_dir_count: {analysis['report_dir_count']}")
    lines.append(f"- replay_input_count: {analysis['replay_input_count']}")
    lines.append(f"- prepared_breakout_row_count: {analysis['prepared_breakout_row_count']}")
    lines.append("")
    lines.append("## Cohort Summary")
    lines.append(f"- candidate_count: {analysis['candidate_count']}")
    lines.append(f"- stable_selected_relief_candidate_count: {analysis['stable_selected_relief_candidate_count']}")
    lines.append(f"- selected_frontier_candidate_count: {analysis['selected_frontier_candidate_count']}")
    lines.append(f"- watchlist_peer_candidate_count: {analysis['watchlist_peer_candidate_count']}")
    lines.append(f"- rejected_surface_candidate_count: {analysis['rejected_surface_candidate_count']}")
    lines.append("")
    if analysis.get("reference_anchor"):
        anchor = dict(analysis.get("reference_anchor") or {})
        lines.append("## Reference Anchor")
        lines.append(
            f"- {anchor.get('ticker')}: verdict={anchor.get('verdict')} decision_counts={anchor.get('decision_counts')} "
            f"selected_relief_window_count={anchor.get('selected_relief_window_count')} "
            f"selected_relief_alignment_rate={anchor.get('selected_relief_alignment_rate')} "
            f"outcome_support={dict(anchor.get('outcome_support') or {}).get('evidence_status')}"
        )
        lines.append("")
    lines.append("## Next Candidate")
    next_candidate = dict(analysis.get("next_candidate") or {})
    if next_candidate:
        lines.append(
            f"- {next_candidate.get('ticker')}: verdict={next_candidate.get('verdict')} "
            f"decision_counts={next_candidate.get('decision_counts')} "
            f"required_score_uplift_to_selected_stats={next_candidate.get('required_score_uplift_to_selected_stats')} "
            f"outcome_support={dict(next_candidate.get('outcome_support') or {}).get('evidence_status')}"
        )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Candidate Ranking")
    for row in list(analysis.get("candidates") or [])[:12]:
        lines.append(
            f"- {row.get('ticker')}: verdict={row.get('verdict')} decision_counts={row.get('decision_counts')} "
            f"selected_relief_window_count={row.get('selected_relief_window_count')} "
            f"required_score_uplift_to_selected_stats={row.get('required_score_uplift_to_selected_stats')} "
            f"outcome_support={dict(row.get('outcome_support') or {}).get('evidence_status')} "
            f"sample_report_labels={row.get('sample_report_labels')}"
        )
    if not list(analysis.get("candidates") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Verdict")
    lines.append(f"- verdict: {analysis['verdict']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan replay windows for prepared-breakout BTST cohort members under the current target profile.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--report-name-contains", default="paper_trading_window")
    parser.add_argument("--profile-name", default="default")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_prepared_breakout_cohort(
        args.reports_root,
        report_name_contains=str(args.report_name_contains or "paper_trading_window"),
        profile_name=str(args.profile_name or "default"),
    )

    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_prepared_breakout_cohort_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
