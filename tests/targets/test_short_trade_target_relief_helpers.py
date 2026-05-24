from __future__ import annotations

from src.targets.short_trade_target_profile_data import SHORT_TRADE_TARGET_PROFILES
from src.targets.short_trade_target_relief_helpers import resolve_historical_execution_relief
from src.targets.models import TargetEvaluationInput


def test_historical_execution_relief_recovers_upstream_corridor_source_from_catalyst_theme_bucket() -> None:
    result = resolve_historical_execution_relief(
        input_data=TargetEvaluationInput(
            trade_date="20260403",
            ticker="300683",
            replay_context={
                "source": "catalyst_theme",
                "upstream_candidate_source": "upstream_liquidity_corridor_shadow",
                "candidate_reason_codes": [
                    "upstream_base_liquidity_uplift_shadow",
                    "candidate_pool_truncated_after_filters",
                    "layer_a_liquidity_corridor",
                    "upstream_shadow_release_candidate",
                    "catalyst_theme_research_candidate",
                ],
                "historical_prior": {
                    "execution_quality_label": "close_continuation",
                    "evaluable_count": 3,
                    "next_close_positive_rate": 0.67,
                    "next_high_hit_rate_at_threshold": 0.67,
                    "next_open_to_close_return_mean": 0.021,
                },
            },
        ),
        profitability_hard_cliff=True,
        profile=SHORT_TRADE_TARGET_PROFILES["btst_precision_v2"],
        historical_prior_getter=lambda input_data: dict(input_data.replay_context.get("historical_prior") or {}),
        normalized_reason_codes=lambda values: [str(value) for value in list(values or []) if str(value or "").strip()],
        is_catalyst_theme_carryover_candidate=lambda **_: False,
        strong_carryover_history_min_evaluable_count=3,
    )

    assert result["candidate_source"] == "upstream_liquidity_corridor_shadow"
    assert result["eligible"] is True
    assert result["gate_hits"]["candidate_source"] is True
