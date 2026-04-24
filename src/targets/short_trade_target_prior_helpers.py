from __future__ import annotations

import os
from typing import Any

from src.targets.explainability import clamp_unit_interval

DEFAULT_PRIOR_STRENGTH = 3.0
DEFAULT_P4_PRIOR_SHRINKAGE_K = 8.0
BTST_0422_P4_PRIOR_SHRINKAGE_MODE_ENV = "BTST_0422_P4_PRIOR_SHRINKAGE_MODE"
BTST_0422_P4_PRIOR_SHRINKAGE_MODES = frozenset({"off", "enforce"})


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


def _safe_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return default


def _resolve_quality_label_baseline(*, execution_quality_label: str, entry_timing_bias: str, btst_regime_gate: str) -> dict[str, float]:
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

    normalized_gate = str(btst_regime_gate or "normal_trade").strip().lower()
    if normalized_gate == "aggressive_trade":
        baseline["next_close_positive_rate"] = clamp_unit_interval(baseline["next_close_positive_rate"] + 0.03)
        baseline["next_high_hit_rate_at_threshold"] = clamp_unit_interval(baseline["next_high_hit_rate_at_threshold"] + 0.03)
        baseline["next_open_to_close_return_mean"] += 0.003
    elif normalized_gate == "shadow_only":
        baseline["next_close_positive_rate"] = clamp_unit_interval(baseline["next_close_positive_rate"] - 0.03)
        baseline["next_high_hit_rate_at_threshold"] = clamp_unit_interval(baseline["next_high_hit_rate_at_threshold"] - 0.03)
        baseline["next_open_to_close_return_mean"] -= 0.002
    elif normalized_gate == "halt":
        baseline["next_close_positive_rate"] = clamp_unit_interval(baseline["next_close_positive_rate"] - 0.05)
        baseline["next_high_hit_rate_at_threshold"] = clamp_unit_interval(baseline["next_high_hit_rate_at_threshold"] - 0.05)
        baseline["next_open_to_close_return_mean"] -= 0.004
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


def resolve_btst_prior_shrinkage_p4_mode() -> str:
    normalized_mode = str(os.getenv(BTST_0422_P4_PRIOR_SHRINKAGE_MODE_ENV, "off") or "off").strip().lower()
    return normalized_mode if normalized_mode in BTST_0422_P4_PRIOR_SHRINKAGE_MODES else "off"


def _resolve_p4_shrinkage_k(prior: dict[str, Any]) -> float:
    shrinkage_k = _safe_float(prior.get("p4_prior_shrinkage_k"), DEFAULT_P4_PRIOR_SHRINKAGE_K)
    return shrinkage_k if shrinkage_k > 0 else DEFAULT_P4_PRIOR_SHRINKAGE_K


def _sample_reliability(*, evidence_count: int, shrinkage_k: float) -> float:
    denominator = float(evidence_count) + float(shrinkage_k)
    if denominator <= 0:
        return 0.0
    return clamp_unit_interval(float(evidence_count) / denominator)


def _resolve_effective_prior_metrics_from_calibrated(prior: dict[str, Any] | None) -> dict[str, Any]:
    prior = dict(prior or {})
    if not prior:
        return {
            "mode": resolve_btst_prior_shrinkage_p4_mode(),
            "rate_source": "none",
            "reliability_source": "none",
            "next_close_positive_rate": 0.0,
            "next_high_hit_rate_at_threshold": 0.0,
            "reliability": 0.0,
        }

    use_shrunk_prior_rates = _safe_bool(prior.get("selected_use_shrunk_prior_rates"), True)

    if resolve_btst_prior_shrinkage_p4_mode() == "enforce" and use_shrunk_prior_rates:
        return {
            "mode": "enforce",
            "rate_source": "shrunk",
            "reliability_source": "sample_reliability",
            "next_close_positive_rate": clamp_unit_interval(_safe_float(prior.get("shrunk_close_positive_rate"), 0.0)),
            "next_high_hit_rate_at_threshold": clamp_unit_interval(_safe_float(prior.get("shrunk_high_hit_rate"), 0.0)),
            "reliability": clamp_unit_interval(_safe_float(prior.get("sample_reliability"), 0.0)),
        }

    return {
        "mode": "enforce" if resolve_btst_prior_shrinkage_p4_mode() == "enforce" else "off",
        "rate_source": "calibrated",
        "reliability_source": "prior_evidence_weight",
        "next_close_positive_rate": clamp_unit_interval(_safe_float(prior.get("calibrated_next_close_positive_rate"), 0.0)),
        "next_high_hit_rate_at_threshold": clamp_unit_interval(_safe_float(prior.get("calibrated_next_high_hit_rate_at_threshold"), 0.0)),
        "reliability": clamp_unit_interval(_safe_float(prior.get("prior_evidence_weight"), 0.0)),
    }


def resolve_effective_prior_metrics(historical_prior: dict[str, Any] | None) -> dict[str, Any]:
    return _resolve_effective_prior_metrics_from_calibrated(calibrate_short_trade_historical_prior(historical_prior))


def calibrate_short_trade_historical_prior(historical_prior: dict[str, Any] | None) -> dict[str, Any]:
    prior = dict(historical_prior or {})
    if not prior:
        return {}

    execution_quality_label = str(prior.get("execution_quality_label") or "unknown").strip()
    entry_timing_bias = str(prior.get("entry_timing_bias") or "unknown").strip()
    btst_regime_gate = str(prior.get("btst_regime_gate") or "normal_trade").strip()
    evaluable_count = max(0, _safe_int(prior.get("evaluable_count"), 0))
    same_ticker_sample_count = max(0, _safe_int(prior.get("same_ticker_sample_count"), evaluable_count))
    evidence_count = max(evaluable_count, same_ticker_sample_count)
    prior_strength = float(prior.get("prior_shrinkage_strength") or DEFAULT_PRIOR_STRENGTH)
    baseline = _resolve_quality_label_baseline(
        execution_quality_label=execution_quality_label,
        entry_timing_bias=entry_timing_bias,
        btst_regime_gate=btst_regime_gate,
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
    p4_shrinkage_k = _resolve_p4_shrinkage_k(prior)
    use_shrunk_prior_rates = _safe_bool(prior.get("selected_use_shrunk_prior_rates"), True)
    sample_reliability = _sample_reliability(evidence_count=evidence_count, shrinkage_k=p4_shrinkage_k)
    shrunk_next_close_positive_rate = _shrink_rate(
        raw_value=raw_next_close_positive_rate,
        evidence_count=evidence_count,
        baseline=baseline["next_close_positive_rate"],
        prior_strength=p4_shrinkage_k,
    )
    shrunk_next_high_hit_rate = _shrink_rate(
        raw_value=raw_next_high_hit_rate,
        evidence_count=evidence_count,
        baseline=baseline["next_high_hit_rate_at_threshold"],
        prior_strength=p4_shrinkage_k,
    )

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
            "prior_baseline_btst_regime_gate": btst_regime_gate,
            "prior_evidence_count": evidence_count,
            "prior_evidence_weight": round(evidence_weight, 6),
            "prior_shrinkage_strength": round(prior_strength, 6),
            "p4_prior_shrinkage_k": round(p4_shrinkage_k, 6),
            "selected_use_shrunk_prior_rates": use_shrunk_prior_rates,
            "sample_reliability": round(sample_reliability, 6),
            "shrunk_close_positive_rate": round(shrunk_next_close_positive_rate, 6),
            "shrunk_high_hit_rate": round(shrunk_next_high_hit_rate, 6),
            "prior_shrinkage_gap_next_close_positive_rate": round(raw_next_close_positive_rate - calibrated_next_close_positive_rate, 6),
            "prior_shrinkage_gap_next_high_hit_rate_at_threshold": round(raw_next_high_hit_rate - calibrated_next_high_hit_rate, 6),
            "prior_shrinkage_gap_next_open_to_close_return_mean": round(raw_next_open_to_close_return_mean - calibrated_next_open_to_close_return_mean, 6),
            "p4_prior_shrinkage_gap_next_close_positive_rate": round(raw_next_close_positive_rate - shrunk_next_close_positive_rate, 6),
            "p4_prior_shrinkage_gap_next_high_hit_rate_at_threshold": round(raw_next_high_hit_rate - shrunk_next_high_hit_rate, 6),
            "historical_prior_calibrated": True,
        }
    )
    effective_metrics = _resolve_effective_prior_metrics_from_calibrated(prior)
    prior["effective_next_close_positive_rate"] = round(float(effective_metrics["next_close_positive_rate"]), 6)
    prior["effective_next_high_hit_rate_at_threshold"] = round(float(effective_metrics["next_high_hit_rate_at_threshold"]), 6)
    prior["effective_prior_reliability"] = round(float(effective_metrics["reliability"]), 6)
    prior["effective_prior_rate_source"] = str(effective_metrics["rate_source"])
    prior["effective_prior_reliability_source"] = str(effective_metrics["reliability_source"])
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
            "rate_source": "none",
        }

    quality_label = str(prior.get("execution_quality_label") or "unknown").strip()
    entry_timing_bias = str(prior.get("entry_timing_bias") or "unknown").strip()
    effective_metrics = resolve_effective_prior_metrics(prior)
    next_close_positive_rate = clamp_unit_interval(_safe_float(effective_metrics.get("next_close_positive_rate"), 0.0))
    next_high_hit_rate_at_threshold = clamp_unit_interval(_safe_float(effective_metrics.get("next_high_hit_rate_at_threshold"), 0.0))
    next_open_to_close_return_mean = _safe_float(prior.get("calibrated_next_open_to_close_return_mean"), 0.0)
    evidence_weight = clamp_unit_interval(_safe_float(effective_metrics.get("reliability"), 0.0))
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
    score = clamp_unit_interval((0.50 * next_close_positive_rate) + (0.25 * next_high_hit_rate_at_threshold) + (0.15 * normalized_open_to_close_return) + (0.10 * evidence_weight) + quality_label_bonus + entry_timing_bonus)
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
        "rate_source": str(effective_metrics.get("rate_source") or "calibrated"),
    }
