from __future__ import annotations

from types import SimpleNamespace

from src.execution.daily_pipeline_catalyst_diagnostics_helpers import (
    _build_catalyst_theme_entry,
    _build_catalyst_theme_shadow_entry,
)


def _build_item() -> SimpleNamespace:
    return SimpleNamespace(
        ticker="300683",
        score_b=0.44,
        score_c=0.0,
        candidate_source="upstream_liquidity_corridor_shadow",
        candidate_reason_codes=[
            "upstream_base_liquidity_uplift_shadow",
            "candidate_pool_truncated_after_filters",
            "layer_a_liquidity_corridor",
            "upstream_shadow_release_candidate",
        ],
        strategy_signals={},
        market_state={},
        theme_name="corridor",
        theme_category="shadow",
        is_new_theme=False,
    )


def test_build_catalyst_theme_entry_preserves_corridor_origin_metadata() -> None:
    entry = _build_catalyst_theme_entry(
        item=_build_item(),
        reason="catalyst_freshness_below_catalyst_theme_floor",
        rank=0,
    )

    assert entry["candidate_source"] == "catalyst_theme"
    assert entry["upstream_candidate_source"] == "upstream_liquidity_corridor_shadow"
    assert "upstream_shadow_release_candidate" in entry["candidate_reason_codes"]


def test_build_catalyst_theme_shadow_entry_preserves_corridor_origin_metadata() -> None:
    entry = _build_catalyst_theme_shadow_entry(
        item=_build_item(),
        filter_reason="catalyst_freshness_below_catalyst_theme_floor",
        metrics_payload={
            "candidate_score": 0.3883,
            "breakout_freshness": 0.4,
            "trend_acceleration": 0.7543,
            "close_strength": 0.8775,
            "sector_resonance": 0.1508,
            "catalyst_freshness": 0.0,
            "threshold_checks": {
                "candidate_score": 0.44,
                "catalyst_freshness": 0.05,
            },
            "gate_status": {"data": "pass", "execution": "fail", "structural": "pass", "score": "fail"},
        },
    )

    assert entry["candidate_source"] == "catalyst_theme_shadow"
    assert entry["upstream_candidate_source"] == "upstream_liquidity_corridor_shadow"
    assert "upstream_shadow_release_candidate" in entry["candidate_reason_codes"]
