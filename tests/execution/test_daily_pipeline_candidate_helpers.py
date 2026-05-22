from __future__ import annotations

from src.execution.daily_pipeline_candidate_helpers import build_short_trade_boundary_metrics_payload


def test_build_short_trade_boundary_metrics_payload_includes_continuation_and_reversal_from_snapshot() -> None:
    metrics_payload = build_short_trade_boundary_metrics_payload(
        snapshot={
            "breakout_freshness": 0.83,
            "trend_acceleration": 0.76,
            "volume_expansion_quality": 0.54,
            "catalyst_freshness": 0.31,
            "close_strength": 0.64,
            "sector_resonance": 0.33,
            "trend_continuation": 0.88,
            "short_term_reversal": 0.12,
            "gate_status": {"data": "pass"},
            "blockers": [],
        },
        compute_candidate_score_fn=lambda snapshot: 0.51,
    )

    assert metrics_payload["trend_continuation"] == 0.88
    assert metrics_payload["short_term_reversal"] == 0.12


def test_build_short_trade_boundary_metrics_payload_uses_raw_candidate_metric_fallbacks_for_missing_snapshot_keys() -> None:
    metrics_payload = build_short_trade_boundary_metrics_payload(
        snapshot={
            "breakout_freshness": 0.83,
            "trend_acceleration": 0.76,
            "volume_expansion_quality": 0.54,
            "catalyst_freshness": 0.31,
            "close_strength": 0.64,
            "sector_resonance": 0.33,
            "gate_status": {"data": "pass"},
            "blockers": [],
        },
        compute_candidate_score_fn=lambda snapshot: 0.51,
        raw_candidate_metrics={
            "trend_continuation": 0.66,
            "short_term_reversal": 0.34,
        },
    )

    assert metrics_payload["trend_continuation"] == 0.66
    assert metrics_payload["short_term_reversal"] == 0.34


def test_build_short_trade_boundary_metrics_payload_keeps_snapshot_values_over_raw_candidate_metrics() -> None:
    metrics_payload = build_short_trade_boundary_metrics_payload(
        snapshot={
            "breakout_freshness": 0.83,
            "trend_acceleration": 0.76,
            "volume_expansion_quality": 0.54,
            "catalyst_freshness": 0.31,
            "close_strength": 0.64,
            "sector_resonance": 0.33,
            "trend_continuation": 0.88,
            "short_term_reversal": 0.12,
            "gate_status": {"data": "pass"},
            "blockers": [],
        },
        compute_candidate_score_fn=lambda snapshot: 0.51,
        raw_candidate_metrics={
            "trend_continuation": 0.66,
            "short_term_reversal": 0.34,
        },
    )

    assert metrics_payload["trend_continuation"] == 0.88
    assert metrics_payload["short_term_reversal"] == 0.12
