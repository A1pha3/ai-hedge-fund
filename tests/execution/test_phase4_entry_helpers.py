from __future__ import annotations

from src.execution.daily_pipeline_phase4_entry_helpers import _build_short_trade_boundary_entry
from src.execution.daily_pipeline_short_trade_diagnostics_helpers import _qualifies_short_trade_boundary_candidate
from src.execution.models import LayerCResult


def test_build_short_trade_boundary_entry_preserves_item_metrics() -> None:
    entry = _build_short_trade_boundary_entry(
        item=LayerCResult(
            ticker="300999",
            score_b=0.78,
            score_c=0.24,
            score_final=0.56,
            quality_score=0.70,
            decision="watch",
            metrics={
                "failed_breakout_10": 3,
                "close_structure": 0.30,
                "retention_proxy": 0.78,
            },
        ),
        reason="short_trade_candidate_score_ranked",
        rank=1,
    )

    assert entry["metrics"] == {
        "failed_breakout_10": 3,
        "close_structure": 0.30,
        "retention_proxy": 0.78,
    }


def test_boundary_candidate_metrics_payload_preserves_item_raw_metrics() -> None:
    entry = _build_short_trade_boundary_entry(
        item=LayerCResult(
            ticker="300999",
            score_b=0.78,
            score_c=0.24,
            score_final=0.56,
            quality_score=0.70,
            decision="watch",
            metrics={
                "failed_breakout_10": 3,
                "close_structure": 0.30,
                "retention_proxy": 0.78,
            },
        ),
        reason="short_trade_candidate_score_ranked",
        rank=1,
    )

    _, _, metrics_payload = _qualifies_short_trade_boundary_candidate(
        trade_date="20260328",
        entry=entry,
    )

    assert metrics_payload["failed_breakout_10"] == 3
    assert metrics_payload["close_structure"] == 0.30
    assert metrics_payload["retention_proxy"] == 0.78
