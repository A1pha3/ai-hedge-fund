from __future__ import annotations

from typing import Any

from src.targets.explainability import clamp_unit_interval

DEFAULT_PRIOR_STRENGTH = 3.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_quality_label_baseline(*, execution_quality_label: str, entry_timing_bias: str) -> dict[str, float]:
    baseline_by_quality = {
        "close_continuation": {
            "next_close_positive_rate": 0.58,
            "next_high_hit_rate_at_threshold": 0.68,
            "next_open_to_close_return_mean": 0.014,
        },
        "intraday_only": {
            "next_close_positive_rate": 0.44,
            "next_high_hit_rate_at_threshold": 0.62,
            "next_open_to_close_return_mean": 0.004,
        },
        "gap_chase_risk": {
            "next_close_positive_rate": 0.42,
            "next_high_hit_rate_at_threshold": 0.60,
            "next_open_to_close_return_mean": 0.006,
        },
        "zero_follow_through": {
            "next_close_positive_rate": 0.35,
            "next_high_hit_rate_at_threshold": 0.55,
            "next_open_to_close_return_mean": 0.0,
        },
    }
    baseline = dict(
        baseline_by_quality.get(
            execution_quality_label,
            {
                "next_close_positive_rate": 0.50,
                "next_high_hit_rate_at_threshold": 0.60,
                "next_open_to_close_return_mean": 0.010,
            },
        )
    )
    if entry_timing_bias == "confirm_then_hold":
        baseline["next_close_positive_rate"] = clamp_unit_interval(baseline["next_close_positive_rate"] + 0.02)
        baseline["next_open_to_close_return_mean"] += 0.002
    elif entry_timing_bias in {"confirm_then_review", "avoid_open_chase", "avoid_open_chase_confirmation"}:
        baseline["next_high_hit_rate_at_threshold"] = clamp_unit_interval(baseline["next_high_hit_rate_at_threshold"] - 0.02)
    return baseline


def _shrink_rate(*, raw_value: float, evidence_count: int, baseline: float, prior_strength: float) -> float:
    if evidence_count <= 0:
        return clamp_unit_interval(baseline)
    numerator = (raw_value * float(evidence_count)) + (baseline * float(prior_strength))
    denominator = float(evidence_count) + float(prior_strength)
    return clamp_unit_interval(numerator / denominator) if denominator > 0 else clamp_unit_interval(baseline)


def _shrink_mean(*, raw_value: float, evidence_count: int, baseline: float, prior_strength: float) -> float:
    if evidence_count <= 0:
        return float(baseline)
    numerator = (raw_value * float(evidence_count)) + (baseline * float(prior_strength))
    denominator = float(evidence_count) + float(prior_strength)
    return (numerator / denominator) if denominator > 0 else float(baseline)


def calibrate_short_trade_historical_prior(historical_prior: dict[str, Any] | None) -> dict[str, Any]:
    prior = dict(historical_prior or {})
    if not prior:
        return {}

    execution_quality_label = str(prior.get("execution_quality_label") or "unknown").strip()
    entry_timing_bias = str(prior.get("entry_timing_bias") or "unknown").strip()
    evaluable_count = max(0, _safe_int(prior.get("evaluable_count"), 0))
    same_ticker_sample_count = max(0, _safe_int(prior.get("same_ticker_sample_count"), evaluable_count))
    evidence_count = max(evaluable_count, same_ticker_sample_count)
    prior_strength = float(prior.get("prior_shrinkage_strength") or DEFAULT_PRIOR_STRENGTH)
    baseline = _resolve_quality_label_baseline(
        execution_quality_label=execution_quality_label,
        entry_timing_bias=entry_timing_bias,
    )

    raw_next_close_positive_rate = clamp_unit_interval(_safe_float(prior.get("next_close_positive_rate"), baseline["next_close_positive_rate"]))
    raw_next_high_hit_rate = clamp_unit_interval(_safe_float(prior.get("next_high_hit_rate_at_threshold"), baseline["next_high_hit_rate_at_threshold"]))
    raw_next_open_to_close_return_mean = _safe_float(prior.get("next_open_to_close_return_mean"), baseline["next_open_to_close_return_mean"])

    calibrated_next_close_positive_rate = _shrink_rate(
        raw_value=raw_next_close_positive_rate,
        evidence_count=evidence_count,
        baseline=baseline["next_close_positive_rate"],
        prior_strength=prior_strength,
    )
    calibrated_next_high_hit_rate = _shrink_rate(
        raw_value=raw_next_high_hit_rate,
        evidence_count=evidence_count,
        baseline=baseline["next_high_hit_rate_at_threshold"],
        prior_strength=prior_strength,
    )
    calibrated_next_open_to_close_return_mean = _shrink_mean(
        raw_value=raw_next_open_to_close_return_mean,
        evidence_count=evidence_count,
        baseline=baseline["next_open_to_close_return_mean"],
        prior_strength=prior_strength,
    )
    evidence_weight = (float(evidence_count) / (float(evidence_count) + prior_strength)) if (float(evidence_count) + prior_strength) > 0 else 0.0

    prior.update(
        {
            "raw_next_close_positive_rate": round(raw_next_close_positive_rate, 6),
            "raw_next_high_hit_rate_at_threshold": round(raw_next_high_hit_rate, 6),
            "raw_next_open_to_close_return_mean": round(raw_next_open_to_close_return_mean, 6),
            "calibrated_next_close_positive_rate": round(calibrated_next_close_positive_rate, 6),
            "calibrated_next_high_hit_rate_at_threshold": round(calibrated_next_high_hit_rate, 6),
            "calibrated_next_open_to_close_return_mean": round(calibrated_next_open_to_close_return_mean, 6),
            "prior_baseline_next_close_positive_rate": round(float(baseline["next_close_positive_rate"]), 6),
            "prior_baseline_next_high_hit_rate_at_threshold": round(float(baseline["next_high_hit_rate_at_threshold"]), 6),
            "prior_baseline_next_open_to_close_return_mean": round(float(baseline["next_open_to_close_return_mean"]), 6),
            "prior_evidence_count": evidence_count,
            "prior_evidence_weight": round(evidence_weight, 6),
            "prior_shrinkage_strength": round(prior_strength, 6),
            "prior_shrinkage_gap_next_close_positive_rate": round(raw_next_close_positive_rate - calibrated_next_close_positive_rate, 6),
            "prior_shrinkage_gap_next_high_hit_rate_at_threshold": round(raw_next_high_hit_rate - calibrated_next_high_hit_rate, 6),
            "prior_shrinkage_gap_next_open_to_close_return_mean": round(raw_next_open_to_close_return_mean - calibrated_next_open_to_close_return_mean, 6),
            "historical_prior_calibrated": True,
        }
    )
    return prior


def score_short_trade_historical_continuation_prior(historical_prior: dict[str, Any] | None) -> dict[str, Any]:
    prior = calibrate_short_trade_historical_prior(historical_prior)
    if not prior:
        return {
            "enabled": False,
            "score": 0.0,
            "quality_label": "unknown",
            "entry_timing_bias": "unknown",
            "evidence_weight": 0.0,
            "next_close_positive_rate": 0.0,
            "next_high_hit_rate_at_threshold": 0.0,
            "next_open_to_close_return_mean": 0.0,
        }

    quality_label = str(prior.get("execution_quality_label") or "unknown").strip()
    entry_timing_bias = str(prior.get("entry_timing_bias") or "unknown").strip()
    next_close_positive_rate = clamp_unit_interval(_safe_float(prior.get("calibrated_next_close_positive_rate"), 0.0))
    next_high_hit_rate_at_threshold = clamp_unit_interval(_safe_float(prior.get("calibrated_next_high_hit_rate_at_threshold"), 0.0))
    next_open_to_close_return_mean = _safe_float(prior.get("calibrated_next_open_to_close_return_mean"), 0.0)
    evidence_weight = clamp_unit_interval(_safe_float(prior.get("prior_evidence_weight"), 0.0))
    normalized_open_to_close_return = clamp_unit_interval((next_open_to_close_return_mean + 0.01) / 0.04)
    quality_label_bonus = {
        "close_continuation": 0.05,
        "intraday_only": -0.01,
        "gap_chase_risk": -0.06,
        "zero_follow_through": -0.10,
    }.get(quality_label, 0.0)
    entry_timing_bonus = {
        "confirm_then_hold": 0.02,
        "confirm_then_review": 0.0,
        "avoid_open_chase": -0.02,
        "avoid_open_chase_confirmation": -0.03,
    }.get(entry_timing_bias, 0.0)
    score = clamp_unit_interval(
        (0.50 * next_close_positive_rate)
        + (0.25 * next_high_hit_rate_at_threshold)
        + (0.15 * normalized_open_to_close_return)
        + (0.10 * evidence_weight)
        + quality_label_bonus
        + entry_timing_bonus
    )
    return {
        "enabled": True,
        "score": round(score, 6),
        "quality_label": quality_label or "unknown",
        "entry_timing_bias": entry_timing_bias or "unknown",
        "evidence_weight": round(evidence_weight, 6),
        "next_close_positive_rate": round(next_close_positive_rate, 6),
        "next_high_hit_rate_at_threshold": round(next_high_hit_rate_at_threshold, 6),
        "next_open_to_close_return_mean": round(next_open_to_close_return_mean, 6),
        "normalized_open_to_close_return": round(normalized_open_to_close_return, 6),
    }
