from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from scripts.btst_latest_followup_utils import load_btst_followup_by_ticker_for_report, load_latest_btst_historical_prior_by_ticker
from src.execution.daily_pipeline import _qualifies_short_trade_boundary_candidate


SELECT_THRESHOLD = 0.58
NEAR_MISS_THRESHOLD = 0.46


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_trade_dates(raw: str | None) -> set[str]:
    if raw is None or not str(raw).strip():
        return set()
    return {token.strip() for token in str(raw).split(",") if token.strip()}


def _iter_selection_snapshots(selection_root: Path, *, trade_dates: set[str] | None = None):
    active_trade_dates = {str(value) for value in (trade_dates or set()) if str(value).strip()}
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        if active_trade_dates and day_dir.name not in active_trade_dates:
            continue
        snapshot_path = day_dir / "selection_snapshot.json"
        if snapshot_path.exists():
            yield _load_json(snapshot_path)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _compact_trade_date(value: str) -> str:
    digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    return digits if len(digits) == 8 else str(value or "").strip()


def _summarize_scores(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(mean(values), 4),
    }


def _build_example(
    *,
    trade_date: str,
    ticker: str,
    candidate_source: str,
    candidate_reason_codes: list[str],
    available_strategy_signals: list[str],
    short_trade: dict[str, Any],
    delta_classification: str | None,
) -> dict[str, Any]:
    metrics_payload = dict(short_trade.get("metrics_payload") or {})
    historical_prior = dict(short_trade.get("historical_prior") or {})
    return {
        "trade_date": trade_date,
        "ticker": ticker,
        "candidate_source": candidate_source,
        "candidate_reason_codes": candidate_reason_codes,
        "available_strategy_signals": available_strategy_signals,
        "decision": short_trade.get("decision"),
        "score_target": round(_safe_float(short_trade.get("score_target")), 4),
        "gap_to_select": round(SELECT_THRESHOLD - _safe_float(short_trade.get("score_target")), 4),
        "gap_to_near_miss": round(NEAR_MISS_THRESHOLD - _safe_float(short_trade.get("score_target")), 4),
        "blockers": list(short_trade.get("blockers") or []),
        "negative_tags": list(short_trade.get("negative_tags") or []),
        "top_reasons": list(short_trade.get("top_reasons") or []),
        "gate_status": dict(short_trade.get("gate_status") or {}),
        "score_b": metrics_payload.get("score_b"),
        "score_c": metrics_payload.get("score_c"),
        "score_final": metrics_payload.get("score_final"),
        "layer_c_alignment": metrics_payload.get("layer_c_alignment"),
        "layer_c_avoid_penalty": metrics_payload.get("layer_c_avoid_penalty"),
        "overhead_supply_penalty": metrics_payload.get("overhead_supply_penalty"),
        "historical_execution_quality_label": historical_prior.get("execution_quality_label"),
        "historical_evaluable_count": historical_prior.get("evaluable_count"),
        "historical_next_close_positive_rate": historical_prior.get("next_close_positive_rate"),
        "historical_next_open_to_close_return_mean": historical_prior.get("next_open_to_close_return_mean"),
        "filter_reason": str(short_trade.get("filter_reason") or ""),
        "delta_classification": delta_classification,
    }


def _normalize_snapshot_short_trade_row(
    *,
    trade_date: str,
    ticker: str,
    candidate_source: str,
    candidate_reason_codes: list[str],
    delta_classification: str | None,
    short_trade: dict[str, Any],
) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "ticker": ticker,
        "candidate_source": candidate_source,
        "candidate_reason_codes": candidate_reason_codes,
        "delta_classification": delta_classification,
        "short_trade": short_trade,
        "available_strategy_signals": [
            str(signal_name)
            for signal_name in list(dict(short_trade.get("explainability_payload") or {}).get("available_strategy_signals") or [])
            if str(signal_name or "").strip()
        ],
    }


def _normalize_upstream_shadow_observation_row(*, trade_date: str, row: dict[str, Any]) -> dict[str, Any]:
    recomputed_short_trade: dict[str, Any] = {}
    candidate_source = str(row.get("candidate_source") or "unknown")
    metrics_payload = dict(row.get("short_trade_boundary_metrics") or {})
    blockers = [str(blocker) for blocker in list(row.get("blockers") or metrics_payload.get("blockers") or []) if str(blocker or "").strip()]
    gate_status = dict(row.get("gate_status") or metrics_payload.get("gate_status") or {})
    if not blockers:
        _, filter_reason, recomputed_metrics_payload = _qualifies_short_trade_boundary_candidate(
            trade_date=_compact_trade_date(trade_date),
            entry=dict(row or {}),
        )
        recomputed_short_trade = {
            "filter_reason": filter_reason,
            "gate_status": dict(recomputed_metrics_payload.get("gate_status") or {}),
            "blockers": list(recomputed_metrics_payload.get("blockers") or []),
            "metrics_payload": recomputed_metrics_payload,
        }
        blockers = [str(blocker) for blocker in list(recomputed_short_trade["blockers"] or []) if str(blocker or "").strip()]
        if recomputed_short_trade["gate_status"]:
            gate_status = dict(recomputed_short_trade["gate_status"])
            metrics_payload = dict(recomputed_short_trade["metrics_payload"] or metrics_payload)
    return {
        "trade_date": trade_date,
        "ticker": str(row.get("ticker") or ""),
        "candidate_source": candidate_source,
        "candidate_reason_codes": [str(reason) for reason in list(row.get("candidate_reason_codes") or []) if str(reason or "").strip()],
        "delta_classification": None,
        "short_trade": {
            "decision": str(row.get("decision") or "observation"),
            "score_target": row.get("score_target"),
            "blockers": blockers,
            "negative_tags": list(row.get("negative_tags") or []),
            "top_reasons": list(row.get("top_reasons") or []),
            "gate_status": gate_status,
            "metrics_payload": metrics_payload,
            "historical_prior": dict(row.get("historical_prior") or {}),
            **({"filter_reason": recomputed_short_trade["filter_reason"]} if recomputed_short_trade.get("filter_reason") else {}),
        },
        "available_strategy_signals": [
            str(signal_name)
            for signal_name in dict(row.get("strategy_signals") or {}).keys()
            if str(signal_name or "").strip()
        ],
    }


def _load_historical_prior_by_ticker(report_path: Path) -> dict[str, dict[str, Any]]:
    rows_by_ticker = load_btst_followup_by_ticker_for_report(report_path)
    priors_by_ticker = {
        ticker: dict(row.get("historical_prior") or {})
        for ticker, row in rows_by_ticker.items()
        if dict(row.get("historical_prior") or {})
    }
    if priors_by_ticker:
        return priors_by_ticker
    return load_latest_btst_historical_prior_by_ticker(report_path.parent)


def _iter_short_trade_rows(selection_root: Path, *, trade_dates: set[str] | None = None):
    active_trade_dates = {str(value) for value in (trade_dates or set()) if str(value).strip()}
    report_path = selection_root.parent
    historical_prior_by_ticker = _load_historical_prior_by_ticker(report_path)
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        if active_trade_dates and day_dir.name not in active_trade_dates:
            continue
        snapshot_path = day_dir / "selection_snapshot.json"
        if not snapshot_path.exists():
            continue
        snapshot = _load_json(snapshot_path)
        trade_date = str(snapshot.get("trade_date") or day_dir.name)
        selection_targets = dict(snapshot.get("selection_targets") or {})
        for ticker, evaluation in selection_targets.items():
            short_trade = dict((evaluation or {}).get("short_trade") or {})
            if not short_trade:
                continue
            yield _normalize_snapshot_short_trade_row(
                trade_date=trade_date,
                ticker=str(ticker),
                candidate_source=str((evaluation or {}).get("candidate_source") or "unknown"),
                candidate_reason_codes=[str(reason) for reason in list((evaluation or {}).get("candidate_reason_codes") or []) if str(reason or "").strip()],
                delta_classification=str((evaluation or {}).get("delta_classification") or "").strip() or None,
                short_trade=short_trade,
            )

        replay_input_path = day_dir / "selection_target_replay_input.json"
        if not replay_input_path.exists():
            continue
        replay_input = _load_json(replay_input_path)
        for row in list(replay_input.get("upstream_shadow_observation_entries") or []):
            ticker = str(dict(row or {}).get("ticker") or "")
            if ticker and not dict(dict(row or {}).get("historical_prior") or {}) and dict(historical_prior_by_ticker.get(ticker) or {}):
                row = {**dict(row or {}), "historical_prior": dict(historical_prior_by_ticker.get(ticker) or {})}
            normalized = _normalize_upstream_shadow_observation_row(trade_date=trade_date, row=dict(row or {}))
            if normalized["ticker"]:
                yield normalized


def _classify_failure_mechanism(*, decision: str, candidate_source: str, blockers: list[str], gate_status: dict[str, Any]) -> str:
    normalized_blockers = {str(blocker) for blocker in blockers if str(blocker or "").strip()}
    normalized_gate_status = {str(key): str(value) for key, value in gate_status.items()}

    if decision == "selected":
        return "selected"
    if decision == "near_miss":
        return "near_miss"
    if normalized_gate_status.get("data") == "fail":
        return "blocked_data_gate"
    if "layer_c_bearish_conflict" in normalized_blockers:
        return "blocked_structural_bearish_conflict"
    if "trend_not_constructive" in normalized_blockers:
        return "blocked_trend_not_constructive"
    if decision == "blocked":
        return f"blocked_{candidate_source}"
    if decision == "rejected":
        return f"rejected_{candidate_source}_score_fail"
    return f"other_{decision}"


def _extract_filter_reason(short_trade: dict[str, Any]) -> str:
    direct_reason = str(short_trade.get("filter_reason") or "").strip()
    if direct_reason:
        return direct_reason
    for reason in list(short_trade.get("top_reasons") or []):
        normalized_reason = str(reason or "").strip()
        if normalized_reason.startswith("filter_reason="):
            return normalized_reason.split("=", 1)[1].strip()
    return ""


def _is_supportive_catalyst_shadow_example(example: dict[str, Any]) -> bool:
    return (
        str(example.get("historical_execution_quality_label") or "").strip() == "close_continuation"
        and int(example.get("historical_evaluable_count") or 0) >= 2
        and _safe_float(example.get("historical_next_close_positive_rate"), default=-1.0) >= 0.5
        and _safe_float(example.get("historical_next_open_to_close_return_mean"), default=-1.0) >= 0.0
    )


def _build_supportive_catalyst_shadow_summary(examples: list[dict[str, Any]]) -> dict[str, Any]:
    catalyst_examples = [
        dict(example)
        for example in examples
        if str(example.get("candidate_source") or "").strip() in {"upstream_liquidity_corridor_shadow", "post_gate_liquidity_competition_shadow"}
        and str(example.get("filter_reason") or "").strip() == "catalyst_freshness_below_short_trade_boundary_floor"
    ]
    execution_quality_counts = Counter(
        str(example.get("historical_execution_quality_label") or "none").strip() or "none"
        for example in catalyst_examples
    )
    support_bucket_counts = Counter(
        "supportive_close_continuation" if _is_supportive_catalyst_shadow_example(example) else "unsupported_or_missing"
        for example in catalyst_examples
    )
    catalyst_examples.sort(key=lambda item: (item["score_target"], item["trade_date"], item["ticker"]), reverse=True)
    supportive_examples = [dict(example) for example in catalyst_examples if _is_supportive_catalyst_shadow_example(example)]
    return {
        "count": len(catalyst_examples),
        "execution_quality_label_counts": dict(execution_quality_counts.most_common()),
        "support_bucket_counts": dict(support_bucket_counts.most_common()),
        "top_examples": catalyst_examples[:8],
        "supportive_examples": supportive_examples[:8],
    }


def _boundary_failure_cluster_count(failure_mechanism_counts: Counter[str]) -> int:
    return int(failure_mechanism_counts.get("rejected_layer_b_boundary_score_fail", 0)) + int(failure_mechanism_counts.get("rejected_short_trade_boundary_score_fail", 0))


def _build_recommended_focus_areas(
    *,
    failure_mechanism_counts: Counter[str],
    candidate_source_breakdown: dict[str, dict[str, Any]],
    supportive_catalyst_shadow_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []

    layer_b_rejected = _boundary_failure_cluster_count(failure_mechanism_counts)
    watchlist_rejected = int(failure_mechanism_counts.get("rejected_watchlist_filter_diagnostics_score_fail", 0))
    trend_not_constructive_blocked = int(failure_mechanism_counts.get("blocked_trend_not_constructive", 0))
    structural_blocked = int(failure_mechanism_counts.get("blocked_structural_bearish_conflict", 0))
    supportive_catalyst_count = int((supportive_catalyst_shadow_summary.get("support_bucket_counts") or {}).get("supportive_close_continuation", 0))
    catalyst_shadow_count = int(supportive_catalyst_shadow_summary.get("count") or 0)

    if supportive_catalyst_count:
        recommendations.append(
            {
                "priority": 1,
                "focus_area": "supportive_catalyst_shadow_release_probe",
                "why": f"{supportive_catalyst_count} 个 catalyst-blocked shadow 样本已具备 close_continuation 历史支持，可优先做 replay / live probe 验证，而不是泛化放宽催化门。",
                "evidence": {
                    "failure_mechanism": "catalyst_freshness_below_short_trade_boundary_floor",
                    "count": supportive_catalyst_count,
                    "cluster_count": catalyst_shadow_count,
                    "top_examples": list(supportive_catalyst_shadow_summary.get('supportive_examples') or [])[:3],
                },
            }
        )

    if layer_b_rejected:
        recommendations.append(
            {
                "priority": len(recommendations) + 1,
                "focus_area": "short_trade_boundary_candidate_quality",
                "why": f"{layer_b_rejected} 个样本停在 short-trade boundary family 且直接因 score fail 被拒绝，是当前窗口里最大的失败簇。",
                "evidence": {
                    "failure_mechanism": ["rejected_layer_b_boundary_score_fail", "rejected_short_trade_boundary_score_fail"],
                    "count": layer_b_rejected,
                    "candidate_source_breakdown": {
                        "layer_b_boundary": candidate_source_breakdown.get("layer_b_boundary", {}),
                        "short_trade_boundary": candidate_source_breakdown.get("short_trade_boundary", {}),
                    },
                },
            }
        )

    if trend_not_constructive_blocked:
        recommendations.append(
            {
                "priority": len(recommendations) + 1,
                "focus_area": "trend_not_constructive_shadow_review",
                "why": f"{trend_not_constructive_blocked} 个样本被 trend_not_constructive 卡在 upstream shadow / 结构门前，应先验证这类逆势样本是否存在稳定的次日 continuation 例外。",
                "evidence": {
                    "failure_mechanism": "blocked_trend_not_constructive",
                    "count": trend_not_constructive_blocked,
                    "candidate_source_breakdown": {
                        key: candidate_source_breakdown.get(key, {})
                        for key in ("upstream_liquidity_corridor_shadow", "post_gate_liquidity_competition_shadow")
                    },
                },
            }
        )

    if structural_blocked:
        recommendations.append(
            {
                "priority": len(recommendations) + 1,
                "focus_area": "layer_c_bearish_conflict_review",
                "why": f"{structural_blocked} 个样本被 layer_c_bearish_conflict 直接阻断，其中包含接近 near-miss 的高分 blocked 样本。",
                "evidence": {
                    "failure_mechanism": "blocked_structural_bearish_conflict",
                    "count": structural_blocked,
                },
            }
        )

    if watchlist_rejected:
        recommendations.append(
            {
                "priority": len(recommendations) + 1,
                "focus_area": "watchlist_candidate_entry_semantics",
                "why": f"{watchlist_rejected} 个样本来自 watchlist_filter_diagnostics 边界入口但最终只停在 score fail，应优先收紧或重定义这类候选入口语义。",
                "evidence": {
                    "failure_mechanism": "rejected_watchlist_filter_diagnostics_score_fail",
                    "count": watchlist_rejected,
                    "candidate_source_breakdown": candidate_source_breakdown.get("watchlist_filter_diagnostics", {}),
                },
            }
        )

    return recommendations


def render_short_trade_blocker_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Short Trade Blocker Analysis")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- trade_day_count: {analysis['trade_day_count']}")
    lines.append(f"- target_mode: {analysis.get('target_mode') or 'unknown'}")
    lines.append(f"- short_trade_target_count: {analysis['short_trade_target_count']}")
    lines.append(f"- short_trade_decision_counts: {analysis['short_trade_decision_counts']}")
    lines.append("")
    lines.append("## Blocker Summary")
    lines.append(f"- blocker_counts: {analysis['blocker_counts']}")
    lines.append(f"- negative_tag_counts: {analysis['negative_tag_counts']}")
    lines.append(f"- candidate_source_counts: {analysis['candidate_source_counts']}")
    lines.append(f"- candidate_reason_code_counts: {analysis['candidate_reason_code_counts']}")
    lines.append(f"- failure_mechanism_counts: {analysis['failure_mechanism_counts']}")
    lines.append(f"- signal_availability: {analysis['signal_availability']}")
    lines.append(f"- available_strategy_signal_counts: {analysis['available_strategy_signal_counts']}")
    lines.append("")
    lines.append("## Supportive Catalyst Shadow Summary")
    lines.append(f"- summary: {analysis['supportive_catalyst_shadow_summary']}")
    lines.append("")
    lines.append("## Candidate Source Breakdown")
    for candidate_source, breakdown in analysis["candidate_source_breakdown"].items():
        lines.append(
            f"- {candidate_source}: total={breakdown['count']}, decisions={breakdown['decision_counts']}, blockers={breakdown['blocker_counts']}, reasons={breakdown['candidate_reason_code_counts']}, score_mean={breakdown['score_distribution']['mean']}"
        )
    lines.append("")
    lines.append("## Recommended Focus Areas")
    for row in analysis["recommended_focus_areas"]:
        lines.append(f"- P{row['priority']}: {row['focus_area']} -> {row['why']}")
    lines.append("")
    lines.append("## Score Distribution")
    lines.append(f"- all_scores: {analysis['score_distribution']['all']}")
    lines.append(f"- blocked_scores: {analysis['score_distribution']['blocked']}")
    lines.append(f"- rejected_scores: {analysis['score_distribution']['rejected']}")
    lines.append(f"- near_miss_scores: {analysis['score_distribution']['near_miss']}")
    lines.append(f"- selected_scores: {analysis['score_distribution']['selected']}")
    lines.append("")
    lines.append("## Day Breakdown")
    for row in analysis["day_breakdown"]:
        lines.append(
            f"- {row['trade_date']}: total={row['short_trade_target_count']}, selected={row['selected_count']}, near_miss={row['near_miss_count']}, blocked={row['blocked_count']}, rejected={row['rejected_count']}"
        )
    lines.append("")
    lines.append("## Representative Cases")
    for row in analysis["top_blocked_examples"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: score_short={row['score_target']}, source={row['candidate_source']}, blockers={row['blockers']}, top_reasons={row['top_reasons']}"
        )
    return "\n".join(lines) + "\n"


def analyze_short_trade_blockers(report_dir: str | Path, *, trade_dates: set[str] | None = None) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    selection_root = report_path / "selection_artifacts"
    session_summary_path = report_path / "session_summary.json"
    session_summary = _load_json(session_summary_path) if session_summary_path.exists() else {}
    active_trade_dates = {str(value) for value in (trade_dates or set()) if str(value).strip()}

    short_trade_decision_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    negative_tag_counts: Counter[str] = Counter()
    candidate_source_counts: Counter[str] = Counter()
    candidate_reason_code_counts: Counter[str] = Counter()
    failure_mechanism_counts: Counter[str] = Counter()
    available_strategy_signal_counts: Counter[str] = Counter()
    signal_availability_counts: Counter[str] = Counter()
    delta_classification_counts: Counter[str] = Counter()
    gate_status_counts: dict[str, Counter[str]] = defaultdict(Counter)
    score_distribution_by_decision: dict[str, list[float]] = defaultdict(list)
    candidate_source_breakdown: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "count": 0,
        "decision_counts": Counter(),
        "blocker_counts": Counter(),
        "candidate_reason_code_counts": Counter(),
        "scores": [],
    })
    top_blocked_examples: list[dict[str, Any]] = []
    top_near_threshold_examples: list[dict[str, Any]] = []
    day_breakdown: list[dict[str, Any]] = []
    all_examples: list[dict[str, Any]] = []

    day_counters: dict[str, Counter[str]] = defaultdict(Counter)

    for row in _iter_short_trade_rows(selection_root, trade_dates=active_trade_dates):
        trade_date = str(row.get("trade_date") or "")
        ticker = str(row.get("ticker") or "")
        short_trade = dict(row.get("short_trade") or {})
        if not short_trade:
            continue

        decision = str(short_trade.get("decision") or "unknown")
        score_target = _safe_float(short_trade.get("score_target"))
        candidate_source = str(row.get("candidate_source") or "unknown")
        candidate_reason_codes = [str(reason) for reason in list(row.get("candidate_reason_codes") or []) if str(reason or "").strip()]
        delta_classification = row.get("delta_classification")
        available_strategy_signals = [str(signal_name) for signal_name in list(row.get("available_strategy_signals") or []) if str(signal_name or "").strip()]

        short_trade_decision_counts[decision] += 1
        day_counters[trade_date][decision] += 1
        candidate_source_counts[candidate_source] += 1
        candidate_reason_code_counts.update(candidate_reason_codes)
        failure_mechanism = _classify_failure_mechanism(
            decision=decision,
            candidate_source=candidate_source,
            blockers=list(short_trade.get("blockers") or []),
            gate_status=dict(short_trade.get("gate_status") or {}),
        )
        failure_mechanism_counts[failure_mechanism] += 1
        available_strategy_signal_counts.update(available_strategy_signals)
        signal_availability_counts["missing_all"] += 1 if not available_strategy_signals else 0
        signal_availability_counts["has_any"] += 1 if available_strategy_signals else 0
        score_distribution_by_decision[decision].append(score_target)
        score_distribution_by_decision["all"].append(score_target)

        source_row = candidate_source_breakdown[candidate_source]
        source_row["count"] += 1
        source_row["decision_counts"][decision] += 1
        source_row["candidate_reason_code_counts"].update(candidate_reason_codes)
        source_row["scores"].append(score_target)

        if delta_classification:
            delta_classification_counts[str(delta_classification)] += 1

        for blocker in list(short_trade.get("blockers") or []):
            blocker_counts[str(blocker)] += 1
            source_row["blocker_counts"][str(blocker)] += 1
        for tag in list(short_trade.get("negative_tags") or []):
            negative_tag_counts[str(tag)] += 1
        for gate_name, gate_value in dict(short_trade.get("gate_status") or {}).items():
            gate_status_counts[str(gate_name)][str(gate_value)] += 1

        example = _build_example(
            trade_date=trade_date,
            ticker=ticker,
            candidate_source=candidate_source,
            candidate_reason_codes=candidate_reason_codes,
            available_strategy_signals=available_strategy_signals,
            short_trade=short_trade,
            delta_classification=str(delta_classification) if delta_classification else None,
        )
        example["filter_reason"] = _extract_filter_reason(short_trade)
        all_examples.append(example)
        if decision == "blocked":
            top_blocked_examples.append(example)
        if decision in {"blocked", "rejected", "near_miss", "observation"} and score_target >= 0.15:
            top_near_threshold_examples.append(example)

    for trade_date, day_counts in sorted(day_counters.items()):
        day_breakdown.append(
            {
                "trade_date": trade_date,
                "short_trade_target_count": sum(day_counts.values()),
                "selected_count": day_counts.get("selected", 0),
                "near_miss_count": day_counts.get("near_miss", 0),
                "blocked_count": day_counts.get("blocked", 0),
                "rejected_count": day_counts.get("rejected", 0),
            }
        )

    top_blocked_examples.sort(key=lambda item: (item["score_target"], item["trade_date"], item["ticker"]), reverse=True)
    top_near_threshold_examples.sort(key=lambda item: (item["score_target"], item["trade_date"], item["ticker"]), reverse=True)

    normalized_candidate_source_breakdown = {
        candidate_source: {
            "count": int(row["count"]),
            "decision_counts": dict(row["decision_counts"].most_common()),
            "blocker_counts": dict(row["blocker_counts"].most_common()),
            "candidate_reason_code_counts": dict(row["candidate_reason_code_counts"].most_common()),
            "score_distribution": _summarize_scores(list(row["scores"])),
        }
        for candidate_source, row in sorted(candidate_source_breakdown.items(), key=lambda item: item[0])
    }

    supportive_catalyst_shadow_summary = _build_supportive_catalyst_shadow_summary(all_examples)
    recommended_focus_areas = _build_recommended_focus_areas(
        failure_mechanism_counts=failure_mechanism_counts,
        candidate_source_breakdown=normalized_candidate_source_breakdown,
        supportive_catalyst_shadow_summary=supportive_catalyst_shadow_summary,
    )

    analysis = {
        "report_dir": str(report_path),
        "selection_artifact_root": str(selection_root),
        "trade_day_count": len(day_breakdown),
        "trade_dates_filter": sorted(active_trade_dates),
        "target_mode": ((session_summary.get("plan_generation") or {}).get("selection_target") or session_summary.get("target_mode") or None),
        "session_dual_target_summary": dict(session_summary.get("dual_target_summary") or {}),
        "short_trade_target_count": sum(short_trade_decision_counts.values()),
        "short_trade_decision_counts": dict(short_trade_decision_counts),
        "blocker_counts": dict(blocker_counts.most_common()),
        "negative_tag_counts": dict(negative_tag_counts.most_common()),
        "candidate_source_counts": dict(candidate_source_counts.most_common()),
        "candidate_reason_code_counts": dict(candidate_reason_code_counts.most_common()),
        "failure_mechanism_counts": dict(failure_mechanism_counts.most_common()),
        "candidate_source_breakdown": normalized_candidate_source_breakdown,
        "signal_availability": dict(signal_availability_counts.most_common()),
        "available_strategy_signal_counts": dict(available_strategy_signal_counts.most_common()),
        "delta_classification_counts": dict(delta_classification_counts.most_common()),
        "gate_status_counts": {gate_name: dict(counter.most_common()) for gate_name, counter in gate_status_counts.items()},
        "recommended_focus_areas": recommended_focus_areas,
        "supportive_catalyst_shadow_summary": supportive_catalyst_shadow_summary,
        "score_distribution": {
            "all": _summarize_scores(score_distribution_by_decision["all"]),
            "blocked": _summarize_scores(score_distribution_by_decision["blocked"]),
            "rejected": _summarize_scores(score_distribution_by_decision["rejected"]),
            "near_miss": _summarize_scores(score_distribution_by_decision["near_miss"]),
            "selected": _summarize_scores(score_distribution_by_decision["selected"]),
        },
        "day_breakdown": day_breakdown,
        "top_blocked_examples": top_blocked_examples[:8],
        "top_near_threshold_examples": top_near_threshold_examples[:8],
    }
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze short trade blocker distribution for a dual-target report directory.")
    parser.add_argument("--report-dir", required=True, help="Paper trading report directory containing selection_artifacts")
    parser.add_argument("--trade-dates", default="", help="Optional comma-separated trade_date filter, e.g. 2026-03-23,2026-03-24")
    parser.add_argument("--output-json", default="", help="Optional output JSON path")
    parser.add_argument("--output-md", default="", help="Optional output Markdown path")
    args = parser.parse_args()

    analysis = analyze_short_trade_blockers(args.report_dir, trade_dates=_parse_trade_dates(args.trade_dates))
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_blocker_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
