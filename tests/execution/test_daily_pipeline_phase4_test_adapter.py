"""Regression tests for the explicit Phase 4 daily_pipeline test adapter."""

from __future__ import annotations

from typing import Any

import src.execution.daily_pipeline_phase4_test_adapter as adapter_module
import src.execution.daily_pipeline_short_trade_diagnostics_helpers as short_trade_helpers
import src.execution.daily_pipeline_upstream_shadow_helpers as upstream_shadow_helpers


def _capture_phase4_target_state() -> list[tuple[object, str, Any]]:
    return [(binding.target_module, binding.target_name or binding.source_name, getattr(binding.target_module, binding.target_name or binding.source_name)) for binding in adapter_module.PHASE4_TEST_OVERRIDE_BINDINGS]


def _restore_phase4_target_state(state: list[tuple[object, str, Any]]) -> None:
    for target_module, name, value in state:
        setattr(target_module, name, value)


def _build_phase4_override_payload() -> tuple[dict[str, Any], object]:
    sentinel_builder = lambda trade_date, entry: {"trade_date": trade_date, "ticker": entry.get("ticker")}  # noqa: E731
    payload = {
        "build_short_trade_target_snapshot_from_entry": sentinel_builder,
        "UPSTREAM_SHADOW_RELEASE_MAX_TICKERS": 2,
        "UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS": {"layer_a_liquidity_corridor": 0.31},
        "UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS": {"layer_a_liquidity_corridor": 1},
        "UPSTREAM_SHADOW_RELEASE_PRIORITY_TICKERS_BY_LANE": {"layer_a_liquidity_corridor": ["300683"]},
        "UPSTREAM_SHADOW_WATCHLIST_PROMOTION_LANES": {"post_gate_liquidity_competition"},
        "UPSTREAM_SHADOW_WATCHLIST_PROMOTION_MAX_TICKERS": 1,
    }
    return payload, sentinel_builder


def test_sync_phase4_test_overrides_mirrors_daily_pipeline_exports_into_helper_modules():
    original_state = _capture_phase4_target_state()
    payload, sentinel_builder = _build_phase4_override_payload()

    try:
        adapter_module.sync_phase4_test_overrides(payload)

        assert short_trade_helpers.build_short_trade_target_snapshot_from_entry is sentinel_builder
        assert short_trade_helpers.UPSTREAM_SHADOW_RELEASE_MAX_TICKERS == 2
        assert short_trade_helpers.UPSTREAM_SHADOW_RELEASE_LANE_SCORE_MINS == {"layer_a_liquidity_corridor": 0.31}
        assert upstream_shadow_helpers.UPSTREAM_SHADOW_RELEASE_LANE_MAX_TICKERS == {"layer_a_liquidity_corridor": 1}
        assert upstream_shadow_helpers.UPSTREAM_SHADOW_RELEASE_PRIORITY_TICKERS_BY_LANE == {"layer_a_liquidity_corridor": ["300683"]}
        assert upstream_shadow_helpers.UPSTREAM_SHADOW_WATCHLIST_PROMOTION_LANES == {"post_gate_liquidity_competition"}
        assert upstream_shadow_helpers.UPSTREAM_SHADOW_WATCHLIST_PROMOTION_MAX_TICKERS == 1
    finally:
        _restore_phase4_target_state(original_state)


def test_run_with_phase4_test_overrides_syncs_before_invoking_callback():
    original_state = _capture_phase4_target_state()
    payload, sentinel_builder = _build_phase4_override_payload()

    try:
        def callback(prefix: str) -> str:
            assert short_trade_helpers.build_short_trade_target_snapshot_from_entry is sentinel_builder
            assert upstream_shadow_helpers.UPSTREAM_SHADOW_RELEASE_MAX_TICKERS == 2
            assert upstream_shadow_helpers.UPSTREAM_SHADOW_WATCHLIST_PROMOTION_LANES == {"post_gate_liquidity_competition"}
            return f"{prefix}:ok"

        result = adapter_module.run_with_phase4_test_overrides(callback, payload, "phase4")

        assert result == "phase4:ok"
    finally:
        _restore_phase4_target_state(original_state)