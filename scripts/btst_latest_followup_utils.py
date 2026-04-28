from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def _safe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        token = str(value or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _compact_trade_date(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:8]


def _decision_rank(decision: str | None) -> int:
    normalized = str(decision or "").strip()
    return {
        "blocked": 4,
        "selected": 3,
        "near_miss": 2,
        "opportunity_pool": 1,
        "rejected": 0,
    }.get(normalized, -1)


def _report_candidate_rank(
    *,
    trade_date: str,
    report_mtime_ns: int,
    selection_target_rank: int,
    has_upstream_shadow_summary: bool,
    max_decision_rank: int,
    selected_count: int,
    near_miss_count: int,
    rejected_count: int,
    report_dir_name: str,
) -> tuple[Any, ...]:
    return (
        trade_date,
        report_mtime_ns,
        selection_target_rank,
        1 if has_upstream_shadow_summary else 0,
        max_decision_rank,
        selected_count,
        near_miss_count,
        -rejected_count,
        report_dir_name,
    )


def _historical_prior_int(prior: dict[str, Any], key: str) -> int:
    value = prior.get(key)
    if value in (None, "", [], {}):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _historical_prior_scope_rank(prior: dict[str, Any]) -> int:
    scope = str(prior.get("applied_scope") or "").strip()
    return {
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
    }.get(scope, 0)


def _historical_prior_risk_rank(prior: dict[str, Any]) -> int:
    label = str(prior.get("execution_quality_label") or "").strip()
    return {
        "zero_follow_through": 5,
        "intraday_only": 4,
        "gap_chase_risk": 3,
        "balanced_confirmation": 2,
        "close_continuation": 1,
    }.get(label, 0)


def _historical_prior_merge_rank(prior: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        _historical_prior_int(prior, "evaluable_count"),
        _historical_prior_int(prior, "sample_count"),
        _historical_prior_scope_rank(prior),
        _historical_prior_risk_rank(prior),
    )


def _choose_preferred_historical_prior(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if not current:
        return dict(incoming)
    if not incoming:
        return dict(current)
    current_rank = _historical_prior_merge_rank(current)
    incoming_rank = _historical_prior_merge_rank(incoming)
    if incoming_rank > current_rank:
        return dict(incoming)
    return dict(current)


def _apply_historical_prior_fields(current: dict[str, Any], historical_prior: dict[str, Any]) -> None:
    if not historical_prior:
        return
    current["historical_prior"] = dict(historical_prior)
    historical_sample_count = historical_prior.get("sample_count")
    if historical_sample_count not in (None, "", [], {}):
        current["historical_sample_count"] = historical_sample_count
    historical_next_close_positive_rate = historical_prior.get("next_close_positive_rate")
    if historical_next_close_positive_rate not in (None, "", [], {}):
        current["historical_next_close_positive_rate"] = historical_next_close_positive_rate
    historical_next_close_return_mean = historical_prior.get("next_close_return_mean")
    if historical_next_close_return_mean not in (None, "", [], {}):
        current["historical_next_close_return_mean"] = historical_next_close_return_mean
    historical_execution_quality_label = historical_prior.get("execution_quality_label")
    if historical_execution_quality_label not in (None, "", [], {}):
        current["historical_execution_quality_label"] = historical_execution_quality_label
    historical_entry_timing_bias = historical_prior.get("entry_timing_bias")
    if historical_entry_timing_bias not in (None, "", [], {}):
        current["historical_entry_timing_bias"] = historical_entry_timing_bias
    historical_execution_note = historical_prior.get("execution_note")
    if historical_execution_note not in (None, "", [], {}):
        current["historical_execution_note"] = historical_execution_note


def _discover_report_dirs(reports_root: Path) -> list[Path]:
    if not reports_root.exists():
        return []
    return [path for path in reports_root.iterdir() if path.is_dir()]


def _extract_btst_candidate(report_dir: Path) -> dict[str, Any] | None:
    session_summary = _safe_load_json(report_dir / "session_summary.json")
    if not session_summary:
        return None

    followup = dict(session_summary.get("btst_followup") or {})
    artifacts = dict(session_summary.get("artifacts") or {})
    selection_target = str(session_summary.get("plan_generation", {}).get("selection_target") or session_summary.get("selection_target") or "").strip()
    brief_json_path = followup.get("brief_json") or artifacts.get("btst_next_day_trade_brief_json")
    brief_json = _safe_load_json(brief_json_path)
    if not brief_json:
        return None

    followup_summary = build_upstream_shadow_followup_summary(brief_json)
    upstream_shadow_summary = dict(brief_json.get("upstream_shadow_summary") or brief_json.get("upstream_shadow_recall_summary") or {})

    compact_trade_date = _compact_trade_date(followup.get("trade_date") or session_summary.get("end_date"))
    selection_target_rank = 2 if selection_target == "short_trade_only" else 1
    report_mtime_ns = report_dir.stat().st_mtime_ns
    selected_count = int(followup_summary.get("decision_counts", {}).get("selected") or 0)
    near_miss_count = int(followup_summary.get("decision_counts", {}).get("near_miss") or 0)
    rejected_count = int(followup_summary.get("decision_counts", {}).get("rejected") or 0)
    max_decision_rank = max((_decision_rank(row.get("decision")) for row in list(followup_summary.get("rows") or [])), default=-1)
    return {
        "report_dir": report_dir.resolve().as_posix(),
        "report_dir_name": report_dir.name,
        "selection_target": selection_target or None,
        "trade_date": compact_trade_date,
        "brief_json": brief_json,
        "brief_json_path": str(Path(brief_json_path).expanduser().resolve()) if brief_json_path else None,
        "selection_target_rank": selection_target_rank,
        "report_mtime_ns": report_mtime_ns,
        "upstream_shadow_followup_row_count": len(list(followup_summary.get("rows") or [])),
        "rank": _report_candidate_rank(
            trade_date=compact_trade_date,
            report_mtime_ns=report_mtime_ns,
            selection_target_rank=selection_target_rank,
            has_upstream_shadow_summary=bool(upstream_shadow_summary),
            max_decision_rank=max_decision_rank,
            selected_count=selected_count,
            near_miss_count=near_miss_count,
            rejected_count=rejected_count,
            report_dir_name=report_dir.name,
        ),
    }


def load_btst_followup_by_ticker_for_report(report_dir: str | Path) -> dict[str, dict[str, Any]]:
    candidate = _extract_btst_candidate(Path(report_dir).expanduser().resolve())
    if not candidate:
        return {}
    brief_json = dict(candidate.get("brief_json") or {})
    if not brief_json:
        return {}
    return _merge_ticker_rows(brief_json)


def select_latest_btst_followup_candidate(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    candidates = [candidate for candidate in (_extract_btst_candidate(path) for path in _discover_report_dirs(resolved_reports_root)) if candidate]
    if not candidates:
        return {}
    return max(candidates, key=lambda candidate: candidate["rank"])


def select_latest_upstream_shadow_followup_candidate(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    candidates = [
        candidate
        for candidate in (_extract_btst_candidate(path) for path in _discover_report_dirs(resolved_reports_root))
        if candidate and int(candidate.get("upstream_shadow_followup_row_count") or 0) > 0
    ]
    if not candidates:
        return {}
    return max(candidates, key=lambda candidate: candidate["rank"])


def _iter_ticker_rows(node: Any):
    if isinstance(node, dict):
        ticker = str(node.get("ticker") or "").strip()
        decision = str(node.get("decision") or "").strip()
        if ticker and decision:
            yield node
        for value in node.values():
            yield from _iter_ticker_rows(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_ticker_rows(item)


def _resolve_formal_decision(row: dict[str, Any]) -> str:
    return str(row.get("reporting_decision") or row.get("decision") or "").strip()


def _iter_followup_brief_rows(brief: dict[str, Any]):
    sections: list[Any] = []
    for key in (
        "primary_entry",
        "selected_entries",
        "near_miss_entries",
        "opportunity_pool_entries",
        "no_history_observer_entries",
        "risky_observer_entries",
        "priority_rows",
        "upstream_shadow_entries",
    ):
        value = brief.get(key)
        if value:
            sections.append(value)

    for summary_key in ("upstream_shadow_summary", "upstream_shadow_recall_summary"):
        summary = dict(brief.get(summary_key) or {})
        for key in ("released_shadow_entries", "validated_rows", "observation_entries"):
            value = summary.get(key)
            if value:
                sections.append(value)

    if not sections:
        yield from _iter_ticker_rows(brief)
        return

    for section in sections:
        yield from _iter_ticker_rows(section)


def _merge_ticker_rows(brief: dict[str, Any]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in _iter_followup_brief_rows(brief):
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        current = dict(merged.get(ticker) or {"ticker": ticker})
        historical_prior = dict(row.get("historical_prior") or {})
        if historical_prior:
            chosen_historical_prior = _choose_preferred_historical_prior(dict(current.get("historical_prior") or {}), historical_prior)
            _apply_historical_prior_fields(current, chosen_historical_prior)
        formal_decision = _resolve_formal_decision(row)
        if formal_decision:
            current["decision"] = formal_decision
            current["reporting_decision"] = formal_decision
        source_decision = str(row.get("decision") or "").strip()
        if source_decision:
            current["source_decision"] = source_decision
        for key in (
            "candidate_source",
            "preferred_entry_mode",
            "promotion_trigger",
            "score_target",
            "confidence",
            "candidate_pool_lane",
            "candidate_pool_lane_display",
            "candidate_pool_rank",
            "candidate_pool_avg_amount_share_of_cutoff",
            "candidate_pool_avg_amount_share_of_min_gate",
            "upstream_candidate_source",
        ):
            value = row.get(key)
            if value not in (None, "", [], {}):
                current[key] = value
        for key in ("gate_status", "metrics"):
            value = row.get(key)
            if isinstance(value, dict) and value:
                current[key] = dict(value)
        for key in ("positive_tags", "top_reasons", "candidate_reason_codes", "rejection_reasons"):
            current[key] = _unique_strings(list(current.get(key) or []) + [str(value) for value in list(row.get(key) or []) if str(value or "").strip()])
        merged[ticker] = current
    return merged


def _ticker_row_rank(row: dict[str, Any]) -> tuple[Any, ...]:
    historical_prior = dict(row.get("historical_prior") or {})
    return (
        _compact_trade_date(row.get("trade_date")),
        int(row.get("report_mtime_ns") or 0),
        int(row.get("selection_target_rank") or 0),
        _decision_rank(row.get("decision")),
        _historical_prior_merge_rank(historical_prior),
        str(row.get("report_dir_name") or ""),
    )


def _upstream_shadow_row_rank(row: dict[str, Any], candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _compact_trade_date(candidate.get("trade_date")),
        int(candidate.get("report_mtime_ns") or 0),
        int(candidate.get("selection_target_rank") or 0),
        _decision_rank(row.get("decision")),
        str(candidate.get("report_dir_name") or ""),
    )


def load_latest_btst_followup_by_ticker(reports_root: str | Path) -> dict[str, dict[str, Any]]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    merged_by_ticker: dict[str, dict[str, Any]] = {}
    for candidate in (_extract_btst_candidate(path) for path in _discover_report_dirs(resolved_reports_root)):
        if not candidate:
            continue
        brief_json = dict(candidate.get("brief_json") or {})
        if not brief_json:
            continue
        rows_by_ticker = _merge_ticker_rows(brief_json)
        for ticker, row in rows_by_ticker.items():
            enriched_row = {
                **row,
                "report_dir": candidate.get("report_dir"),
                "report_dir_name": candidate.get("report_dir_name"),
                "trade_date": candidate.get("trade_date"),
                "selection_target": candidate.get("selection_target"),
                "selection_target_rank": candidate.get("selection_target_rank"),
                "report_mtime_ns": candidate.get("report_mtime_ns"),
            }
            current = merged_by_ticker.get(ticker)
            if current is None or _ticker_row_rank(enriched_row) > _ticker_row_rank(current):
                merged_by_ticker[ticker] = enriched_row
    return merged_by_ticker


def load_latest_btst_historical_prior_by_ticker(reports_root: str | Path) -> dict[str, dict[str, Any]]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    priors_by_ticker: dict[str, dict[str, Any]] = {}
    ranked_rows_by_ticker: dict[str, tuple[Any, ...]] = {}
    for candidate in (_extract_btst_candidate(path) for path in _discover_report_dirs(resolved_reports_root)):
        if not candidate:
            continue
        brief_json = dict(candidate.get("brief_json") or {})
        if not brief_json:
            continue
        rows_by_ticker = _merge_ticker_rows(brief_json)
        for ticker, row in rows_by_ticker.items():
            historical_prior = dict(row.get("historical_prior") or {})
            if not historical_prior:
                continue
            enriched_row = {
                **row,
                "report_dir": candidate.get("report_dir"),
                "report_dir_name": candidate.get("report_dir_name"),
                "trade_date": candidate.get("trade_date"),
                "selection_target": candidate.get("selection_target"),
                "selection_target_rank": candidate.get("selection_target_rank"),
                "report_mtime_ns": candidate.get("report_mtime_ns"),
            }
            rank = _ticker_row_rank(enriched_row)
            if ticker not in ranked_rows_by_ticker or rank > ranked_rows_by_ticker[ticker]:
                ranked_rows_by_ticker[ticker] = rank
                priors_by_ticker[ticker] = historical_prior
    return priors_by_ticker


def _is_upstream_shadow_followup_row(ticker: str, row: dict[str, Any], *, focus_tickers: list[str]) -> bool:
    candidate_source = str(row.get("candidate_source") or "").strip()
    tags = {str(value or "").strip() for value in list(row.get("positive_tags") or []) if str(value or "").strip()}
    reasons = {str(value or "").strip() for value in list(row.get("top_reasons") or []) if str(value or "").strip()}
    reason_codes = {str(value or "").strip() for value in list(row.get("candidate_reason_codes") or []) if str(value or "").strip()}
    if ticker in set(focus_tickers):
        return True
    if "shadow" in candidate_source or "upstream" in candidate_source:
        return True
    if any(token.startswith("upstream_shadow") for token in tags | reasons | reason_codes):
        return True
    if "upstream_base_liquidity_uplift_shadow" in reason_codes:
        return True
    return False


def build_upstream_shadow_followup_summary(
    brief: dict[str, Any],
    *,
    report_dir: str | None = None,
    trade_date: str | None = None,
) -> dict[str, Any]:
    merged_rows = _merge_ticker_rows(brief)
    upstream_shadow_summary = dict(brief.get("upstream_shadow_summary") or brief.get("upstream_shadow_recall_summary") or {})
    focus_tickers = _unique_strings(list(upstream_shadow_summary.get("top_focus_tickers") or []))
    rows = _build_upstream_shadow_followup_rows(
        merged_rows,
        focus_tickers=focus_tickers,
        report_dir=report_dir,
        trade_date=trade_date,
    )
    if not rows:
        return _build_unavailable_upstream_shadow_followup_summary(report_dir=report_dir, trade_date=trade_date)
    ticker_groups = _build_upstream_shadow_followup_ticker_groups(rows)

    return {
        "status": "validated_upstream_shadow_followup_available",
        "report_dir": report_dir,
        "trade_date": trade_date,
        "validated_tickers": ticker_groups["validated_tickers"],
        "selected_tickers": ticker_groups["selected_tickers"],
        "near_miss_tickers": ticker_groups["near_miss_tickers"],
        "rejected_profitability_tickers": ticker_groups["rejected_profitability_tickers"],
        "decision_counts": ticker_groups["decision_counts"],
        "rows": rows,
        "recommendation": _build_upstream_shadow_followup_recommendation(ticker_groups),
    }


def _build_upstream_shadow_followup_rows(
    merged_rows: dict[str, dict[str, Any]],
    *,
    focus_tickers: list[str],
    report_dir: str | None,
    trade_date: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidate_tickers = focus_tickers or list(merged_rows.keys())
    for ticker in candidate_tickers:
        row = dict(merged_rows.get(ticker) or {})
        if not row:
            continue
        if not _is_upstream_shadow_followup_row(ticker, row, focus_tickers=focus_tickers):
            continue
        decision = str(row.get("decision") or "").strip()
        if decision not in {"blocked", "selected", "near_miss", "rejected"}:
            continue
        top_reasons = _unique_strings(list(row.get("top_reasons") or []))
        rejection_reasons = _unique_strings(list(row.get("rejection_reasons") or []))
        positive_tags = _unique_strings(list(row.get("positive_tags") or []))
        rows.append(
            {
                **row,
                "ticker": ticker,
                "report_dir": report_dir,
                "trade_date": trade_date,
                "top_reasons": top_reasons,
                "rejection_reasons": rejection_reasons,
                "positive_tags": positive_tags,
                "validated_by_upstream_shadow_recall": True,
                "downstream_bottleneck": _resolve_upstream_shadow_downstream_bottleneck(
                    decision=decision,
                    top_reasons=top_reasons,
                    rejection_reasons=rejection_reasons,
                    positive_tags=positive_tags,
                ),
                "historical_execution_quality_label": row.get("historical_execution_quality_label"),
                "historical_entry_timing_bias": row.get("historical_entry_timing_bias"),
                "historical_execution_note": row.get("historical_execution_note"),
            }
        )
    rows.sort(
        key=lambda row: (
            0 if str(row.get("decision") or "") == "near_miss" else 1,
            0 if str(row.get("downstream_bottleneck") or "") == "profitability_hard_cliff" else 1,
            str(row.get("ticker") or ""),
        )
    )
    return rows


def _resolve_upstream_shadow_downstream_bottleneck(
    *,
    decision: str,
    top_reasons: list[str],
    rejection_reasons: list[str],
    positive_tags: list[str],
) -> str | None:
    if decision == "selected":
        return "selected"
    if "profitability_hard_cliff" in set(top_reasons) | set(rejection_reasons):
        return "profitability_hard_cliff"
    if "upstream_shadow_catalyst_relief" in top_reasons or "upstream_shadow_catalyst_relief_applied" in positive_tags:
        return "catalyst_relief_validated"
    return None


def _build_upstream_shadow_followup_ticker_groups(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts = Counter(str(row.get("decision") or "unknown") for row in rows)
    validated_tickers = [str(row.get("ticker") or "") for row in rows if str(row.get("ticker") or "").strip()]
    blocked_tickers = [str(row.get("ticker") or "") for row in rows if str(row.get("decision") or "") == "blocked"]
    selected_tickers = [str(row.get("ticker") or "") for row in rows if str(row.get("decision") or "") == "selected"]
    near_miss_tickers = [str(row.get("ticker") or "") for row in rows if str(row.get("decision") or "") == "near_miss"]
    rejected_profitability_tickers = [
        str(row.get("ticker") or "")
        for row in rows
        if str(row.get("decision") or "") == "rejected" and str(row.get("downstream_bottleneck") or "") == "profitability_hard_cliff"
    ]
    generic_rejected_tickers = [
        str(row.get("ticker") or "")
        for row in rows
        if str(row.get("decision") or "") == "rejected" and str(row.get("downstream_bottleneck") or "") != "profitability_hard_cliff"
    ]
    return {
        "decision_counts": {key: int(value) for key, value in decision_counts.items()},
        "validated_tickers": validated_tickers,
        "blocked_tickers": blocked_tickers,
        "selected_tickers": selected_tickers,
        "near_miss_tickers": near_miss_tickers,
        "rejected_profitability_tickers": rejected_profitability_tickers,
        "generic_rejected_tickers": generic_rejected_tickers,
    }


def _build_unavailable_upstream_shadow_followup_summary(
    *,
    report_dir: str | None,
    trade_date: str | None,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "report_dir": report_dir,
        "trade_date": trade_date,
        "validated_tickers": [],
        "decision_counts": {},
        "rows": [],
        "recommendation": None,
    }


def _build_upstream_shadow_followup_recommendation(ticker_groups: dict[str, Any]) -> str:
    recommendation_parts: list[str] = []
    if ticker_groups["blocked_tickers"]:
        recommendation_parts.append(
            f"最新正式 shadow rerun 已验证 {ticker_groups['blocked_tickers']} 属于 blocked truth，当前应从 formal execution 名单移除。"
        )
    if ticker_groups["selected_tickers"]:
        recommendation_parts.append(
            f"最新正式 shadow rerun 已验证 {ticker_groups['selected_tickers']} 可进入 selected，当前不应再按 upstream absence 处理。"
        )
    if ticker_groups["near_miss_tickers"]:
        recommendation_parts.append(
            f"最新正式 shadow rerun 已验证 {ticker_groups['near_miss_tickers']} 可进入 near_miss，当前不应再按 upstream absence 处理。"
        )
    if ticker_groups["rejected_profitability_tickers"]:
        recommendation_parts.append(
            f"{ticker_groups['rejected_profitability_tickers']} 已完成上游召回验证，但当前主矛盾转为 profitability_hard_cliff。"
        )
    if ticker_groups["generic_rejected_tickers"]:
        recommendation_parts.append(
            f"{ticker_groups['generic_rejected_tickers']} 已完成上游召回验证，但仍停留在 recalled-shadow rejected 层。"
        )
    if not recommendation_parts:
        recommendation_parts.append("最新正式 shadow rerun 已形成 upstream recall 下游验证样本，应按当前 short-trade decision 分层处理。")
    return " ".join(recommendation_parts)


def load_latest_upstream_shadow_followup_summary(reports_root: str | Path) -> dict[str, Any]:
    latest_candidate = select_latest_upstream_shadow_followup_candidate(reports_root)
    if not latest_candidate:
        return {
            "status": "unavailable",
            "report_dir": None,
            "trade_date": None,
            "validated_tickers": [],
            "selected_tickers": [],
            "decision_counts": {},
            "rows": [],
            "recommendation": None,
        }
    return build_upstream_shadow_followup_summary(
        dict(latest_candidate.get("brief_json") or {}),
        report_dir=latest_candidate.get("report_dir"),
        trade_date=latest_candidate.get("trade_date"),
    )


def load_latest_upstream_shadow_followup_by_ticker(reports_root: str | Path) -> dict[str, dict[str, Any]]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    candidates = [candidate for candidate in (_extract_btst_candidate(path) for path in _discover_report_dirs(resolved_reports_root)) if candidate]
    rows_by_ticker: dict[str, dict[str, Any]] = {}
    ranks_by_ticker: dict[str, tuple[Any, ...]] = {}
    for candidate in candidates:
        summary = build_upstream_shadow_followup_summary(
            dict(candidate.get("brief_json") or {}),
            report_dir=candidate.get("report_dir"),
            trade_date=candidate.get("trade_date"),
        )
        for row in list(summary.get("rows") or []):
            ticker = str(row.get("ticker") or "").strip()
            if not ticker:
                continue
            candidate_rank = _upstream_shadow_row_rank(row, candidate)
            current_rank = ranks_by_ticker.get(ticker)
            if current_rank is None or candidate_rank > current_rank:
                rows_by_ticker[ticker] = dict(row)
                ranks_by_ticker[ticker] = candidate_rank
    return rows_by_ticker


def load_upstream_shadow_followup_history_by_ticker(reports_root: str | Path) -> dict[str, list[dict[str, Any]]]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    candidates = [candidate for candidate in (_extract_btst_candidate(path) for path in _discover_report_dirs(resolved_reports_root)) if candidate]
    grouped: dict[str, list[tuple[tuple[Any, ...], dict[str, Any]]]] = {}
    for candidate in candidates:
        summary = build_upstream_shadow_followup_summary(
            dict(candidate.get("brief_json") or {}),
            report_dir=candidate.get("report_dir"),
            trade_date=candidate.get("trade_date"),
        )
        for row in list(summary.get("rows") or []):
            ticker = str(row.get("ticker") or "").strip()
            if not ticker:
                continue
            candidate_rank = _upstream_shadow_row_rank(row, candidate)
            grouped.setdefault(ticker, []).append((candidate_rank, dict(row)))

    return {
        ticker: [row for _rank, row in sorted(items, key=lambda item: item[0], reverse=True)]
        for ticker, items in grouped.items()
    }
