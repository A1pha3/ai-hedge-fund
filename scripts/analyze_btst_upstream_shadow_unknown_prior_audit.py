from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.analyze_short_trade_blockers import collect_short_trade_rows
from scripts.btst_latest_followup_utils import (
    load_latest_btst_historical_prior_by_ticker,
    load_upstream_shadow_followup_rows_for_report,
)

REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_upstream_shadow_unknown_prior_audit_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_upstream_shadow_unknown_prior_audit_latest.md"
UPSTREAM_SHADOW_SOURCE = "upstream_liquidity_corridor_shadow"
LOW_SAMPLE_EVALUABLE_COUNT = 2
PRIOR_SCOPE_RANK = {
    "same_ticker": 6,
    "same_family_source_score_catalyst": 5,
    "family_source_score_catalyst": 5,
    "same_family_source": 4,
    "family_source": 4,
    "same_family": 3,
    "same_source_score": 2,
    "source_score": 2,
    "candidate_source": 1,
    "none": 0,
}
PRIOR_LABEL_RANK = {
    "zero_follow_through": 5,
    "intraday_only": 4,
    "gap_chase_risk": 3,
    "balanced_confirmation": 2,
    "close_continuation": 1,
}


def _normalize_prior(prior: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(prior or {})
    return {str(key): value for key, value in normalized.items() if value not in (None, "", [], {})}


def _prior_rank(prior: dict[str, Any]) -> tuple[int, int, int, int]:
    normalized = _normalize_prior(prior)
    return (
        int(normalized.get("evaluable_count") or 0),
        int(normalized.get("sample_count") or 0),
        PRIOR_SCOPE_RANK.get(str(normalized.get("applied_scope") or ""), 0),
        PRIOR_LABEL_RANK.get(str(normalized.get("execution_quality_label") or ""), 0),
    )


def _extract_final_row_prior(row: dict[str, Any]) -> dict[str, Any]:
    short_trade = dict(row.get("short_trade") or {})
    return _normalize_prior(short_trade.get("historical_prior") or row.get("historical_prior"))


def _classify_trace_status(
    *,
    embedded_prior: dict[str, Any],
    latest_loader_prior: dict[str, Any],
    resolved_final_prior: dict[str, Any],
) -> str:
    if not embedded_prior and not latest_loader_prior and not resolved_final_prior:
        return "missing_upstream_prior"
    if embedded_prior and not latest_loader_prior and not resolved_final_prior:
        return "latest_prior_missing"
    # Only count as resolve_dropped_stronger_prior if latest_loader_prior is meaningfully stronger than final row,
    # not just due to scope-only rank delta. If the final row already carries the same meaningful prior core as
    # the latest loader prior (execution_quality_label, sample_count, evaluable_count), and that final prior is still low-sample,
    # classify as resolved_but_low_sample. Only use resolve_dropped_stronger_prior when the latest loader prior is
    # meaningfully stronger than the final row, not just stronger because of extra ranked metadata like applied_scope.
    if latest_loader_prior:
        # Compare core prior fields
        core_keys = ["execution_quality_label", "sample_count", "evaluable_count"]
        final_core = tuple(resolved_final_prior.get(k) for k in core_keys)
        loader_core = tuple(latest_loader_prior.get(k) for k in core_keys)
        if final_core == loader_core:
            # If the final prior is still low-sample, classify as resolved_but_low_sample
            if int(resolved_final_prior.get("evaluable_count") or 0) < LOW_SAMPLE_EVALUABLE_COUNT:
                return "resolved_but_low_sample"
        elif _prior_rank(latest_loader_prior) > _prior_rank(resolved_final_prior):
            return "resolve_dropped_stronger_prior"
    if resolved_final_prior and int(resolved_final_prior.get("evaluable_count") or 0) < LOW_SAMPLE_EVALUABLE_COUNT and not latest_loader_prior:
        return "resolved_but_low_sample"
    return "resolve_kept_unknown"


def _build_prior_trace(
    *,
    followup_row: dict[str, Any],
    final_row: dict[str, Any] | None,
    latest_loader_prior: dict[str, Any],
) -> dict[str, Any]:
    embedded_prior = _normalize_prior(followup_row.get("historical_prior"))
    normalized_latest_loader_prior = _normalize_prior(latest_loader_prior)
    resolved_final_prior = _extract_final_row_prior(final_row or {})
    trace_status = _classify_trace_status(
        embedded_prior=embedded_prior,
        latest_loader_prior=normalized_latest_loader_prior,
        resolved_final_prior=resolved_final_prior,
    )
    return {
        "embedded_prior": embedded_prior,
        "latest_loader_prior": normalized_latest_loader_prior,
        "resolved_final_prior": resolved_final_prior,
        "trace_status": trace_status,
    }


def _build_ticker_timeline_board(ticker_timeline: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    board: list[dict[str, Any]] = []
    for ticker in sorted(ticker_timeline):
        rows = list(ticker_timeline[ticker])
        board.append(
            {
                "ticker": ticker,
                "occurrences": len(rows),
                "trace_statuses": [str(row.get("prior_trace", {}).get("trace_status") or "") for row in rows],
                "trade_dates": [str(row.get("trade_date") or "") for row in rows],
            }
        )
    return board


def _build_recommendation(trace_status_split: Counter[str]) -> str:
    if int(trace_status_split.get("resolve_dropped_stronger_prior") or 0) > 0:
        return "Prioritize attachment repair before any label-generation audit."
    if int(trace_status_split.get("resolved_but_low_sample") or 0) > 0:
        return "Prioritize sample-quality follow-up before any label-generation audit."
    return "No immediate attachment gap found; inspect label-generation only after validating trace coverage."


def analyze_btst_upstream_shadow_unknown_prior_audit(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    latest_priors = load_latest_btst_historical_prior_by_ticker(resolved_reports_root)
    attachment_gap_rows: list[dict[str, Any]] = []
    low_sample_or_weak_prior_rows: list[dict[str, Any]] = []
    ticker_timeline: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trace_status_split: Counter[str] = Counter()
    rows_audited = 0
    rows_with_partial_trace = 0
    rows_skipped_for_missing_report_inputs = 0

    if not resolved_reports_root.exists():
        return {
            "reports_root": str(resolved_reports_root),
            "coverage_summary": {
                "rows_audited": 0,
                "rows_skipped_for_missing_report_inputs": 0,
                "rows_with_partial_trace": 0,
            },
            "trace_status_split": {},
            "attachment_gap_rows": [],
            "low_sample_or_weak_prior_rows": [],
            "ticker_timeline_board": [],
            "recommendation": _build_recommendation(Counter()),
        }

    for report_dir in sorted(path for path in resolved_reports_root.iterdir() if path.is_dir()):
        followup_rows = load_upstream_shadow_followup_rows_for_report(report_dir)
        if not followup_rows:
            rows_skipped_for_missing_report_inputs += 1
            continue
        final_rows_by_key = {
            (str(row.get("trade_date") or ""), str(row.get("ticker") or "")): dict(row)
            for row in collect_short_trade_rows(report_dir)
            if str(row.get("candidate_source") or "") == UPSTREAM_SHADOW_SOURCE
        }
        for followup_row in followup_rows:
            key = (str(followup_row.get("trade_date") or ""), str(followup_row.get("ticker") or ""))
            final_row = final_rows_by_key.get(key)
            prior_trace = _build_prior_trace(
                followup_row=followup_row,
                final_row=final_row,
                latest_loader_prior=dict(latest_priors.get(key[1]) or {}),
            )
            rows_audited += 1
            if not prior_trace["resolved_final_prior"]:
                rows_with_partial_trace += 1

            output_row = {
                "trade_date": key[0],
                "ticker": key[1],
                "decision": str(followup_row.get("decision") or ""),
                "candidate_source": str(followup_row.get("candidate_source") or ""),
                "prior_trace": prior_trace,
            }
            trace_status = str(prior_trace["trace_status"])
            trace_status_split[trace_status] += 1
            ticker_timeline[key[1]].append(output_row)
            if trace_status == "resolve_dropped_stronger_prior":
                attachment_gap_rows.append(output_row)
            elif trace_status in {"resolved_but_low_sample", "resolve_kept_unknown"}:
                low_sample_or_weak_prior_rows.append(output_row)

    return {
        "reports_root": str(resolved_reports_root),
        "coverage_summary": {
            "rows_audited": rows_audited,
            "rows_skipped_for_missing_report_inputs": rows_skipped_for_missing_report_inputs,
            "rows_with_partial_trace": rows_with_partial_trace,
        },
        "trace_status_split": dict(trace_status_split),
        "attachment_gap_rows": attachment_gap_rows,
        "low_sample_or_weak_prior_rows": low_sample_or_weak_prior_rows,
        "ticker_timeline_board": _build_ticker_timeline_board(ticker_timeline),
        "recommendation": _build_recommendation(trace_status_split),
    }
