from __future__ import annotations

from typing import Any

from scripts.btst_analysis_utils import safe_float


def classify_unclassified_bucket(row: dict[str, Any]) -> str:
    breakout = safe_float(row.get("breakout_freshness"))
    trend = safe_float(row.get("trend_acceleration"))
    volume = safe_float(row.get("volume_expansion_quality"))
    close = safe_float(row.get("close_strength"))
    candidate_source = str(row.get("candidate_source") or "")
    decision = str(row.get("decision") or "")

    if all(value is None for value in (breakout, trend, volume, close)):
        return "missing_all_core_features"
    if breakout is None and trend is not None and close is not None:
        return "missing_breakout_inputs_only"
    if trend is None and breakout is not None and volume is not None:
        return "missing_trend_inputs_only"
    if trend is not None and close is not None and 0.5 <= trend < 0.55 and 0.55 <= close < 0.60:
        return "near_trend_threshold"
    if breakout is not None and volume is not None and 0.5 <= breakout < 0.55 and 0.5 <= volume < 0.55:
        return "near_breakout_threshold"
    if decision == "blocked":
        return "blocked_before_structure_matures"
    if candidate_source == "layer_c_watchlist":
        return "watchlist_only_low_signal"
    return "other_unclassified"


def summarize_unclassified_recoverability(row: dict[str, Any]) -> str:
    bucket = str(row.get("bucket") or "")
    if bucket in {"near_trend_threshold", "near_breakout_threshold"}:
        return "recover_threshold_near_miss"
    if bucket in {"missing_breakout_inputs_only", "missing_trend_inputs_only"}:
        return "inspect_candidate_source_contract"
    if bucket == "blocked_before_structure_matures":
        return "revisit_blocker_family"
    return "ignore_noise"
