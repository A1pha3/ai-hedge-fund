from __future__ import annotations

import os
from typing import Any


def _resolve_payoff_review_lane_mode() -> str:
    return str(os.getenv("BTST_PAYOFF_REVIEW_LANE_MODE", "") or "").strip().lower() or "off"


def _clamp01(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return value


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _execution_quality_multiplier(label: str) -> float:
    normalized = str(label or "").strip().lower() or "unknown"
    return {
        "close_continuation": 1.00,
        "balanced_confirmation": 0.95,
        "gap_chase_risk": 0.85,
        "intraday_only": 0.80,
        "unknown": 0.90,
        "zero_follow_through": 0.50,
        "payoff_divergence_risk": 0.60,
    }.get(normalized, 0.90)


def _build_lane_components(historical_prior: dict[str, Any]) -> dict[str, Any]:
    evaluable_count = _as_int(historical_prior.get("evaluable_count"))
    next_high_hit_rate = _as_float(historical_prior.get("next_high_hit_rate_at_threshold"))
    execution_quality_label = str(historical_prior.get("execution_quality_label") or "unknown")

    reliability = _clamp01(evaluable_count / 5.0)
    quality_multiplier = _execution_quality_multiplier(execution_quality_label)

    score = _clamp01(next_high_hit_rate * reliability * quality_multiplier)

    return {
        "prior_next_high_hit_rate_at_threshold": next_high_hit_rate,
        "evaluable_count": evaluable_count,
        "execution_quality_label": execution_quality_label,
        "reliability_multiplier": reliability,
        "quality_multiplier": quality_multiplier,
        "score": score,
    }


def build_payoff_review_entries(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
    max_entries: int = 5,
) -> list[dict[str, Any]]:
    """Build a small, review-only shortlist intended to surface payoff candidates.

    v1 intentionally uses proxy priors (next-day high hit-rate @ 2% threshold) as a scoring signal.
    The lane is report-only and is gated by `BTST_PAYOFF_REVIEW_LANE_MODE=report` (default off).
    """

    if _resolve_payoff_review_lane_mode() != "report":
        return []

    max_entries = max(0, _as_int(max_entries, default=5))
    if max_entries <= 0:
        return []

    # Prefer keeping a `selected` row if both selected + near_miss show up for the same ticker.
    deduped: dict[str, dict[str, Any]] = {}
    for row in list(near_miss_entries or []):
        ticker = str((row or {}).get("ticker") or "").strip()
        if not ticker:
            continue
        deduped.setdefault(ticker, dict(row))
    for row in list(selected_entries or []):
        ticker = str((row or {}).get("ticker") or "").strip()
        if not ticker:
            continue
        deduped[ticker] = dict(row)

    scored_rows: list[dict[str, Any]] = []
    for ticker, row in deduped.items():
        historical_prior = dict(row.get("historical_prior") or {})
        comps = _build_lane_components(historical_prior)
        score = float(comps.get("score") or 0.0)
        scored_rows.append(
            {
                **row,
                "ticker": ticker,
                "review_semantics": "review_only",
                "payoff_review_lane_score": score,
                "payoff_review_lane_components": comps,
            }
        )

    # Stable ordering: score desc, then selected before near_miss, then ticker.
    def _decision_rank(decision: Any) -> int:
        normalized = str(decision or "").strip().lower()
        if normalized == "selected":
            return 0
        if normalized == "near_miss":
            return 1
        return 2

    scored_rows.sort(
        key=lambda row: (
            -(row.get("payoff_review_lane_score") or 0.0),
            _decision_rank(row.get("decision")),
            row.get("ticker") or "",
        )
    )

    limited = scored_rows[:max_entries]
    for idx, row in enumerate(limited, start=1):
        row["payoff_review_lane_rank"] = idx

    return limited
