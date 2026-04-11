from __future__ import annotations

from typing import Any


def _build_upstream_shadow_observation_top_reasons(*, candidate_score: float, filter_reason: str, metrics_payload: dict[str, Any]) -> list[str]:
    return [
        f"candidate_score={candidate_score:.2f}",
        f"filter_reason={filter_reason}",
        f"breakout_freshness={float(metrics_payload.get('breakout_freshness', 0.0) or 0.0):.2f}",
    ]


def _build_upstream_shadow_observation_score_fields(candidate_score: float) -> dict[str, Any]:
    return {
        "decision": "observation",
        "score_target": candidate_score,
        "confidence": round(min(1.0, max(0.0, candidate_score)), 4),
    }


def _build_upstream_shadow_observation_metrics(metrics_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "breakout_freshness": metrics_payload.get("breakout_freshness"),
        "trend_acceleration": metrics_payload.get("trend_acceleration"),
        "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
        "close_strength": metrics_payload.get("close_strength"),
        "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
    }


def _build_upstream_shadow_observation_status_fields(
    *,
    filter_reason: str,
    gate_status: dict[str, Any],
    blockers: list[Any],
) -> dict[str, Any]:
    return {
        "rejection_reasons": [filter_reason],
        "filter_reason": filter_reason,
        "gate_status": gate_status,
        "blockers": blockers,
    }


def _build_upstream_shadow_observation_promotion_fields(metrics_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "promotion_trigger": "仅作上游影子补票观察；只有盘中新强度确认后才允许升级到 near-miss 或 selected 观察层。",
        "short_trade_boundary_metrics": metrics_payload,
    }


def _build_upstream_shadow_observation_payload(*, filter_reason: str, metrics_payload: dict[str, Any]) -> dict[str, Any]:
    candidate_score = round(float(metrics_payload.get("candidate_score", 0.0) or 0.0), 4)
    gate_status = dict(metrics_payload.get("gate_status") or {})
    gate_status.setdefault("score", "shadow_observation")
    blockers = list(metrics_payload.get("blockers") or [])
    return {
        **_build_upstream_shadow_observation_score_fields(candidate_score),
        "top_reasons": _build_upstream_shadow_observation_top_reasons(
            candidate_score=candidate_score,
            filter_reason=filter_reason,
            metrics_payload=metrics_payload,
        ),
        **_build_upstream_shadow_observation_status_fields(
            filter_reason=filter_reason,
            gate_status=gate_status,
            blockers=blockers,
        ),
        "metrics": _build_upstream_shadow_observation_metrics(metrics_payload),
        **_build_upstream_shadow_observation_promotion_fields(metrics_payload),
    }


def _build_upstream_shadow_observation_entry(*, candidate_entry: dict[str, Any], filter_reason: str, metrics_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **candidate_entry,
        **_build_upstream_shadow_observation_payload(
            filter_reason=filter_reason,
            metrics_payload=metrics_payload,
        ),
    }


def _build_short_trade_boundary_reason_codes(*, reason: str, candidate_reason_codes: list[str] | None) -> list[str]:
    resolved_reason_codes = [str(code) for code in list(candidate_reason_codes or [reason, "short_trade_prequalified"]) if str(code or "").strip()]
    if reason not in resolved_reason_codes:
        resolved_reason_codes.insert(0, reason)
    return resolved_reason_codes


def _build_short_trade_boundary_score_fields(item: Any) -> dict[str, float]:
    return {
        "score_b": round(float(item.score_b), 4),
        "score_c": 0.0,
        "score_final": round(float(item.score_b), 4),
        "quality_score": 0.5,
    }


def _build_short_trade_boundary_strategy_signals(item: Any) -> dict[str, Any]:
    return {
        name: signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal or {})
        for name, signal in dict(item.strategy_signals or {}).items()
    }


def _build_short_trade_boundary_reason_fields(
    *,
    reason: str,
    candidate_source: str,
    upstream_candidate_source: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "reason": reason,
        "reasons": reason_codes,
        "candidate_source": candidate_source,
        "upstream_candidate_source": upstream_candidate_source,
        "candidate_reason_codes": reason_codes,
    }


def _build_short_trade_boundary_metadata_fields(
    *,
    rank: int,
    candidate_pool_rank: int | None,
    candidate_pool_lane: str | None,
    candidate_pool_shadow_reason: str | None,
    candidate_pool_avg_amount_share_of_cutoff: float | None,
    candidate_pool_avg_amount_share_of_min_gate: float | None,
    shadow_visibility_gap_selected: bool,
    shadow_visibility_gap_relaxed_band: bool,
) -> dict[str, Any]:
    return {
        "rank": rank,
        "candidate_pool_rank": candidate_pool_rank,
        "candidate_pool_lane": candidate_pool_lane,
        "candidate_pool_shadow_reason": candidate_pool_shadow_reason,
        "candidate_pool_avg_amount_share_of_cutoff": candidate_pool_avg_amount_share_of_cutoff,
        "candidate_pool_avg_amount_share_of_min_gate": candidate_pool_avg_amount_share_of_min_gate,
        "shadow_visibility_gap_selected": shadow_visibility_gap_selected,
        "shadow_visibility_gap_relaxed_band": shadow_visibility_gap_relaxed_band,
    }


def _build_short_trade_boundary_strategy_context_fields(item: Any) -> dict[str, Any]:
    return {
        "decision": str(item.decision or "neutral"),
        "strategy_signals": _build_short_trade_boundary_strategy_signals(item),
        "agent_contribution_summary": _build_short_trade_boundary_agent_summary(),
    }


def _build_short_trade_boundary_core_fields(
    *,
    item: Any,
    reason: str,
    candidate_source: str,
    upstream_candidate_source: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        **_build_short_trade_boundary_reason_fields(
            reason=reason,
            candidate_source=candidate_source,
            upstream_candidate_source=upstream_candidate_source,
            reason_codes=reason_codes,
        ),
        **_build_short_trade_boundary_strategy_context_fields(item),
    }


def _build_short_trade_boundary_agent_summary() -> dict[str, Any]:
    return {}


def _build_short_trade_boundary_entry_payload(
    *,
    item: Any,
    reason: str,
    candidate_source: str,
    upstream_candidate_source: str,
    candidate_reason_codes: list[str] | None,
    rank: int,
    candidate_pool_rank: int | None,
    candidate_pool_lane: str | None,
    candidate_pool_shadow_reason: str | None,
    candidate_pool_avg_amount_share_of_cutoff: float | None,
    candidate_pool_avg_amount_share_of_min_gate: float | None,
    shadow_visibility_gap_selected: bool,
    shadow_visibility_gap_relaxed_band: bool,
) -> dict[str, Any]:
    resolved_reason_codes = _build_short_trade_boundary_reason_codes(
        reason=reason,
        candidate_reason_codes=candidate_reason_codes,
    )
    return _build_short_trade_boundary_payload(
        item=item,
        reason=reason,
        candidate_source=candidate_source,
        upstream_candidate_source=upstream_candidate_source,
        reason_codes=resolved_reason_codes,
        rank=rank,
        candidate_pool_rank=candidate_pool_rank,
        candidate_pool_lane=candidate_pool_lane,
        candidate_pool_shadow_reason=candidate_pool_shadow_reason,
        candidate_pool_avg_amount_share_of_cutoff=candidate_pool_avg_amount_share_of_cutoff,
        candidate_pool_avg_amount_share_of_min_gate=candidate_pool_avg_amount_share_of_min_gate,
        shadow_visibility_gap_selected=shadow_visibility_gap_selected,
        shadow_visibility_gap_relaxed_band=shadow_visibility_gap_relaxed_band,
    )


def _build_short_trade_boundary_payload(
    *,
    item: Any,
    reason: str,
    candidate_source: str,
    upstream_candidate_source: str,
    reason_codes: list[str],
    rank: int,
    candidate_pool_rank: int | None,
    candidate_pool_lane: str | None,
    candidate_pool_shadow_reason: str | None,
    candidate_pool_avg_amount_share_of_cutoff: float | None,
    candidate_pool_avg_amount_share_of_min_gate: float | None,
    shadow_visibility_gap_selected: bool,
    shadow_visibility_gap_relaxed_band: bool,
) -> dict[str, Any]:
    payload = _build_short_trade_boundary_score_fields(item)
    payload.update(
        _build_short_trade_boundary_core_fields(
            item=item,
            reason=reason,
            candidate_source=candidate_source,
            upstream_candidate_source=upstream_candidate_source,
            reason_codes=reason_codes,
        )
    )
    payload.update(
        _build_short_trade_boundary_metadata_fields(
            rank=rank,
            candidate_pool_rank=candidate_pool_rank,
            candidate_pool_lane=candidate_pool_lane,
            candidate_pool_shadow_reason=candidate_pool_shadow_reason,
            candidate_pool_avg_amount_share_of_cutoff=candidate_pool_avg_amount_share_of_cutoff,
            candidate_pool_avg_amount_share_of_min_gate=candidate_pool_avg_amount_share_of_min_gate,
            shadow_visibility_gap_selected=shadow_visibility_gap_selected,
            shadow_visibility_gap_relaxed_band=shadow_visibility_gap_relaxed_band,
        )
    )
    return payload


def _build_short_trade_boundary_entry(
    *,
    item: Any,
    reason: str,
    rank: int,
    candidate_source: str = "short_trade_boundary",
    upstream_candidate_source: str = "layer_b_boundary",
    candidate_reason_codes: list[str] | None = None,
    candidate_pool_rank: int | None = None,
    candidate_pool_lane: str | None = None,
    candidate_pool_shadow_reason: str | None = None,
    candidate_pool_avg_amount_share_of_cutoff: float | None = None,
    candidate_pool_avg_amount_share_of_min_gate: float | None = None,
    shadow_visibility_gap_selected: bool = False,
    shadow_visibility_gap_relaxed_band: bool = False,
) -> dict[str, Any]:
    return {
        "ticker": item.ticker,
        **_build_short_trade_boundary_entry_payload(
            item=item,
            reason=reason,
            candidate_source=candidate_source,
            upstream_candidate_source=upstream_candidate_source,
            candidate_reason_codes=candidate_reason_codes,
            rank=rank,
            candidate_pool_rank=candidate_pool_rank,
            candidate_pool_lane=candidate_pool_lane,
            candidate_pool_shadow_reason=candidate_pool_shadow_reason,
            candidate_pool_avg_amount_share_of_cutoff=candidate_pool_avg_amount_share_of_cutoff,
            candidate_pool_avg_amount_share_of_min_gate=candidate_pool_avg_amount_share_of_min_gate,
            shadow_visibility_gap_selected=shadow_visibility_gap_selected,
            shadow_visibility_gap_relaxed_band=shadow_visibility_gap_relaxed_band,
        ),
    }
