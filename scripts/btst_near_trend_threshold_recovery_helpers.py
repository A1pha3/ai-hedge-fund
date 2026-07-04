from __future__ import annotations

from typing import Any

from scripts.btst_analysis_utils import safe_float


def build_near_trend_recovery_candidate(row: dict[str, Any]) -> dict[str, Any]:
    trend = safe_float(row.get("trend_acceleration"))
    close = safe_float(row.get("close_strength"))
    is_target_bucket = str(row.get("bucket") or "") == "near_trend_threshold"
    is_recovery_candidate = is_target_bucket and trend is not None and close is not None and 0.50 <= trend < 0.55 and 0.55 <= close < 0.60 and row.get("beta_tradeable") is True and row.get("gamma_closed_cycle") is True
    return {
        **row,
        "is_recovery_candidate": is_recovery_candidate,
        "recovery_reason": "near_trend_threshold_window" if is_recovery_candidate else None,
    }


def summarize_near_trend_recovery_governance_verdict(
    *,
    recovered_hit_rate: float | None,
    recovered_mean_return: float | None,
    recovered_tradeable_rate: float | None,
    recovered_row_count: int,
    minimum_required_row_count: int = 3,
    baseline_hit_rate: float | None,
    baseline_mean_return: float | None,
) -> str:
    if recovered_row_count < minimum_required_row_count:
        return "hold_recovery_too_small_or_noisy"
    if recovered_hit_rate is None or recovered_mean_return is None or recovered_tradeable_rate is None:
        return "hold_recovery_too_small_or_noisy"
    if recovered_tradeable_rate < 0.70:
        return "abandon_recovery_line"
    if recovered_hit_rate > float(baseline_hit_rate or 0.0) and recovered_mean_return > float(baseline_mean_return or 0.0):
        return "advance_recovery_validation"
    return "abandon_recovery_line"
