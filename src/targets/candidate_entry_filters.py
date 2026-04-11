from __future__ import annotations

from collections import Counter
from typing import Any


def build_watchlist_avoid_weak_structure_filter(
    *,
    breakout_freshness_max: float | None = None,
    trend_acceleration_max: float | None = None,
    volume_expansion_quality_max: float | None = None,
    close_strength_max: float | None = None,
    catalyst_freshness_max: float | None = None,
) -> dict[str, Any]:
    metric_max_thresholds: dict[str, float] = {}
    if breakout_freshness_max is not None:
        metric_max_thresholds["breakout_freshness"] = float(breakout_freshness_max)
    if trend_acceleration_max is not None:
        metric_max_thresholds["trend_acceleration"] = float(trend_acceleration_max)
    if volume_expansion_quality_max is not None:
        metric_max_thresholds["volume_expansion_quality"] = float(volume_expansion_quality_max)
    if close_strength_max is not None:
        metric_max_thresholds["close_strength"] = float(close_strength_max)
    if catalyst_freshness_max is not None:
        metric_max_thresholds["catalyst_freshness"] = float(catalyst_freshness_max)
    return {
        "name": "watchlist_avoid_boundary_weak_structure_entry",
        "candidate_sources": ["watchlist_filter_diagnostics"],
        "all_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "metric_max_thresholds": metric_max_thresholds,
    }


def build_default_btst_candidate_entry_filter_rules() -> list[dict[str, Any]]:
    return [
        build_watchlist_avoid_weak_structure_filter(
            breakout_freshness_max=0.05,
            volume_expansion_quality_max=0.05,
            catalyst_freshness_max=0.05,
        )
    ]


def collect_candidate_entry_reason_codes(entry: dict[str, Any]) -> list[str]:
    normalized_entry = dict(entry or {})
    reason_codes = [str(reason) for reason in list(normalized_entry.get("candidate_reason_codes", normalized_entry.get("reasons", [])) or []) if str(reason or "").strip()]
    primary_reason = str(normalized_entry.get("reason") or "").strip()
    if primary_reason and primary_reason not in reason_codes:
        reason_codes.insert(0, primary_reason)
    return reason_codes


def _build_candidate_entry_metric_snapshot(*, trade_date: str, entry: dict[str, Any], candidate_source: str) -> dict[str, Any]:
    from src.targets.short_trade_target import evaluate_short_trade_rejected_target

    normalized_entry = dict(entry or {})
    if not normalized_entry:
        return {}
    normalized_entry.setdefault("candidate_source", candidate_source)
    evaluation = evaluate_short_trade_rejected_target(
        trade_date=str(trade_date or "").replace("-", ""),
        entry=normalized_entry,
    )
    metric_snapshot = dict(getattr(evaluation, "metrics_payload", {}) or {})
    metric_snapshot["__gate_status__"] = dict(getattr(evaluation, "gate_status", {}) or {})
    metric_snapshot["__blockers__"] = list(getattr(evaluation, "blockers", []) or [])
    return metric_snapshot


def evaluate_candidate_entry_filter_rule(entry: dict[str, Any], rule: dict[str, Any], *, trade_date: str, default_candidate_source: str) -> dict[str, Any]:
    normalized_entry = dict(entry or {})
    candidate_source = str(normalized_entry.get("candidate_source") or normalized_entry.get("source") or default_candidate_source or "unknown")
    reason_codes = set(collect_candidate_entry_reason_codes(normalized_entry))
    candidate_sources = {str(value) for value in list(rule.get("candidate_sources") or []) if str(value or "").strip()}
    all_reason_codes = {str(value) for value in list(rule.get("all_reason_codes") or []) if str(value or "").strip()}
    any_reason_codes = {str(value) for value in list(rule.get("any_reason_codes") or []) if str(value or "").strip()}
    metric_max_thresholds = {str(name): float(value) for name, value in dict(rule.get("metric_max_thresholds") or {}).items() if str(name or "").strip()}
    metric_min_thresholds = {str(name): float(value) for name, value in dict(rule.get("metric_min_thresholds") or {}).items() if str(name or "").strip()}
    candidate_source_match = not candidate_sources or candidate_source in candidate_sources
    all_reason_codes_match = not all_reason_codes or all_reason_codes.issubset(reason_codes)
    any_reason_codes_match = not any_reason_codes or not reason_codes.isdisjoint(any_reason_codes)
    preconditions_match = candidate_source_match and all_reason_codes_match and any_reason_codes_match
    metric_snapshot: dict[str, Any] = {}
    metric_gate_status: dict[str, Any] = {}
    metric_data_pass: bool | None = None
    metric_thresholds_match = False
    if preconditions_match:
        if metric_max_thresholds or metric_min_thresholds:
            metric_snapshot = _build_candidate_entry_metric_snapshot(trade_date=trade_date, entry=normalized_entry, candidate_source=candidate_source)
            metric_gate_status = dict(metric_snapshot.get("__gate_status__") or {})
            metric_data_pass = str(metric_gate_status.get("data") or "") == "pass"
            if metric_data_pass:
                exceeds_max_threshold = any(float(metric_snapshot.get(name)) > threshold for name, threshold in metric_max_thresholds.items() if metric_snapshot.get(name) is not None)
                missing_max_metric = any(metric_snapshot.get(name) is None for name in metric_max_thresholds)
                below_min_threshold = any(float(metric_snapshot.get(name)) < threshold for name, threshold in metric_min_thresholds.items() if metric_snapshot.get(name) is not None)
                missing_min_metric = any(metric_snapshot.get(name) is None for name in metric_min_thresholds)
                metric_thresholds_match = not (exceeds_max_threshold or missing_max_metric or below_min_threshold or missing_min_metric)
        else:
            metric_thresholds_match = True
    return {
        "name": str(rule.get("name") or "unnamed_filter"),
        "candidate_source": candidate_source,
        "candidate_reason_codes": sorted(reason_codes),
        "preconditions_match": preconditions_match,
        "metric_snapshot": {
            metric_name: metric_snapshot.get(metric_name)
            for metric_name in sorted(set(metric_max_thresholds) | set(metric_min_thresholds))
        }
        if metric_snapshot
        else {},
        "metric_gate_status": metric_gate_status,
        "metric_data_pass": metric_data_pass,
        "metric_thresholds_match": metric_thresholds_match,
    }


def match_candidate_entry_filter(entry: dict[str, Any], filter_rules: list[dict[str, Any]], *, trade_date: str, default_candidate_source: str) -> dict[str, Any] | None:
    for rule in filter_rules:
        rule_evaluation = evaluate_candidate_entry_filter_rule(entry, rule, trade_date=trade_date, default_candidate_source=default_candidate_source)
        if not rule_evaluation["preconditions_match"]:
            continue
        if not rule_evaluation["metric_thresholds_match"]:
            continue
        return {
            "name": rule_evaluation["name"],
            "candidate_source": rule_evaluation["candidate_source"],
            "candidate_reason_codes": list(rule_evaluation["candidate_reason_codes"]),
            "metric_snapshot": dict(rule_evaluation.get("metric_snapshot") or {}),
            "metric_gate_status": dict(rule_evaluation.get("metric_gate_status") or {}),
        }
    return None


def summarize_candidate_entry_filter_observability(entries: list[dict[str, Any]], filter_rules: list[dict[str, Any]], *, trade_date: str, default_candidate_source: str) -> dict[str, dict[str, int]]:
    summary: dict[str, Counter[str]] = {}
    if not filter_rules:
        return {}
    for raw_entry in list(entries or []):
        for rule in filter_rules:
            rule_evaluation = evaluate_candidate_entry_filter_rule(raw_entry, rule, trade_date=trade_date, default_candidate_source=default_candidate_source)
            if not rule_evaluation["preconditions_match"]:
                continue
            rule_name = rule_evaluation["name"]
            counters = summary.setdefault(rule_name, Counter())
            counters["precondition_match_count"] += 1
            metric_data_pass = rule_evaluation.get("metric_data_pass")
            if metric_data_pass is True:
                counters["metric_data_pass_count"] += 1
            elif metric_data_pass is False:
                counters["metric_data_fail_count"] += 1
            if rule_evaluation["metric_thresholds_match"]:
                counters["metric_threshold_match_count"] += 1
    return {
        rule_name: {key: int(value) for key, value in counters.items()}
        for rule_name, counters in sorted(summary.items())
    }


def apply_candidate_entry_filters(entries: list[dict[str, Any]], filter_rules: list[dict[str, Any]], *, trade_date: str, default_candidate_source: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not filter_rules:
        return list(entries or []), []
    kept_entries: list[dict[str, Any]] = []
    filtered_entries: list[dict[str, Any]] = []
    for raw_entry in list(entries or []):
        entry = dict(raw_entry or {})
        matched_filter = match_candidate_entry_filter(entry, filter_rules, trade_date=trade_date, default_candidate_source=default_candidate_source)
        if matched_filter is None:
            kept_entries.append(entry)
            continue
        filtered_entries.append(
            {
                "ticker": str(entry.get("ticker") or ""),
                "matched_filter": matched_filter["name"],
                "candidate_source": matched_filter["candidate_source"],
                "candidate_reason_codes": list(matched_filter["candidate_reason_codes"]),
                "metric_snapshot": dict(matched_filter.get("metric_snapshot") or {}),
                "metric_gate_status": dict(matched_filter.get("metric_gate_status") or {}),
            }
        )
    return kept_entries, filtered_entries
