from __future__ import annotations

from src.execution.daily_pipeline_candidate_helpers import (
    build_short_trade_boundary_metrics_payload,
    rank_scored_entries,
)


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


def test_build_short_trade_boundary_metrics_payload_backfills_boundary_contract_core_keys_from_raw_candidate_metrics() -> None:
    payload = build_short_trade_boundary_metrics_payload(
        snapshot={
            "breakout_freshness": 0.71,
            "trend_acceleration": 0.66,
            "volume_expansion_quality": 0.63,
            "close_strength": 0.68,
            "catalyst_freshness": 0.55,
            "sector_resonance": 0.44,
            "gate_status": {"data": "pass"},
            "blockers": [],
        },
        compute_candidate_score_fn=lambda snapshot: 0.77,
        raw_candidate_metrics={
            "trend_continuation": 0.57,
            "short_term_reversal": 0.21,
        },
    )

    assert payload["trend_continuation"] == 0.57
    assert payload["short_term_reversal"] == 0.21


def test_build_short_trade_boundary_metrics_payload_keeps_explicit_snapshot_values_authoritative() -> None:
    payload = build_short_trade_boundary_metrics_payload(
        snapshot={
            "breakout_freshness": 0.71,
            "trend_acceleration": 0.66,
            "volume_expansion_quality": 0.63,
            "close_strength": 0.68,
            "trend_continuation": 0.61,
            "short_term_reversal": 0.19,
            "catalyst_freshness": 0.55,
            "sector_resonance": 0.44,
            "gate_status": {"data": "pass"},
            "blockers": [],
        },
        compute_candidate_score_fn=lambda snapshot: 0.77,
        raw_candidate_metrics={
            "trend_continuation": 0.57,
            "short_term_reversal": 0.21,
        },
    )

    assert payload["trend_continuation"] == 0.61
    assert payload["short_term_reversal"] == 0.19


def test_rank_scored_entries_does_not_mutate_input_rows() -> None:
    entry_a = {"ticker": "000001"}
    entry_b = {"ticker": "000002"}
    rows = [
        (0.8, entry_a),
        (0.9, entry_b),
    ]

    ranked = rank_scored_entries(rows, limit=2)

    assert rows == [
        (0.8, {"ticker": "000001"}),
        (0.9, {"ticker": "000002"}),
    ]
    assert ranked[0]["rank"] == 1
    assert ranked[1]["rank"] == 2


def test_rank_scored_entries_uses_ascending_ticker_as_tie_breaker() -> None:
    rows = [
        (0.8, {"ticker": "000002"}),
        (0.8, {"ticker": "000001"}),
    ]

    ranked = rank_scored_entries(rows, limit=2)

    assert [entry["ticker"] for entry in ranked] == ["000001", "000002"]
    assert [entry["rank"] for entry in ranked] == [1, 2]
