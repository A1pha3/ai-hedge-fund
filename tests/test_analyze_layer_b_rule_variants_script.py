from __future__ import annotations

import json
import os
from types import SimpleNamespace

import scripts.analyze_layer_b_rule_variants as analyze_layer_b_rule_variants

from scripts.analyze_layer_b_rule_variants import _run_variant, _temporary_env


def test_temporary_env_clears_layer_b_analysis_overrides_for_baseline(monkeypatch):
    monkeypatch.setenv("LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE", "inactive")
    monkeypatch.setenv("LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE", "guarded_dual_leg_033_no_hard_cliff")
    monkeypatch.setenv("LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION", "1")

    with _temporary_env({}):
        assert os.getenv("LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE") is None
        assert os.getenv("LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE") is None
        assert os.getenv("LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION") is None

    assert os.getenv("LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE") == "inactive"
    assert os.getenv("LAYER_B_ANALYSIS_NEUTRAL_MEAN_REVERSION_MODE") == "guarded_dual_leg_033_no_hard_cliff"
    assert os.getenv("LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION") == "1"


class _FakeSignal:
    def __init__(self, *, direction: int = 1, confidence: float = 60.0, completeness: float = 1.0) -> None:
        self._payload = {
            "direction": direction,
            "confidence": confidence,
            "completeness": completeness,
        }

    def model_dump(self) -> dict[str, float | int]:
        return dict(self._payload)


def test_run_variant_respects_explicit_fast_score_threshold(monkeypatch):
    monkeypatch.setattr(
        analyze_layer_b_rule_variants,
        "build_candidate_pool",
        lambda trade_date, use_cache=True: [
            SimpleNamespace(ticker="AAA", industry_sw="电子"),
            SimpleNamespace(ticker="BBB", industry_sw="通信"),
        ],
    )
    monkeypatch.setattr(analyze_layer_b_rule_variants, "detect_market_state", lambda trade_date: SimpleNamespace())
    monkeypatch.setattr(analyze_layer_b_rule_variants, "score_batch", lambda candidates, trade_date: candidates)
    monkeypatch.setattr(
        analyze_layer_b_rule_variants,
        "fuse_batch",
        lambda scored, market_state, trade_date: [
            SimpleNamespace(ticker="AAA", score_b=0.40, decision="watch", arbitration_applied=[], strategy_signals={"trend": _FakeSignal()}),
            SimpleNamespace(ticker="BBB", score_b=0.30, decision="watch", arbitration_applied=[], strategy_signals={"trend": _FakeSignal()}),
        ],
    )

    result = _run_variant(["20260406"], env_updates={}, fast_score_threshold=0.38)

    assert result["total_layer_b_passes"] == 1
    assert result["by_date"]["20260406"]["selected_tickers"] == ["AAA"]


def test_run_variant_uses_frozen_replay_input_when_report_dir_is_provided(monkeypatch, tmp_path):
    replay_input_path = tmp_path / "selection_artifacts" / "2026-04-09" / "selection_target_replay_input.json"
    replay_input_path.parent.mkdir(parents=True)
    replay_input_path.write_text(
        json.dumps(
            {
                "trade_date": "2026-04-09",
                "watchlist": [
                    {
                        "ticker": "AAA",
                        "score_b": 0.40,
                        "decision": "watch",
                        "strategy_signals": {"trend": {"direction": 1, "confidence": 80.0, "completeness": 1.0}},
                    },
                    {
                        "ticker": "BBB",
                        "score_b": 0.30,
                        "decision": "neutral",
                        "strategy_signals": {"trend": {"direction": 0, "confidence": 50.0, "completeness": 1.0}},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        analyze_layer_b_rule_variants,
        "build_candidate_pool",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("live candidate pool should not be used")),
    )

    result = _run_variant(
        ["20260409"],
        env_updates={},
        fast_score_threshold=0.38,
        replay_input_report_dir=tmp_path,
    )

    assert result["total_layer_b_passes"] == 1
    assert result["by_date"]["20260409"]["selected_tickers"] == ["AAA"]
    assert result["by_date"]["20260409"]["records"]["AAA"]["score_b"] == 0.4


def test_run_variant_includes_rejected_entries_from_frozen_replay_input(monkeypatch, tmp_path):
    replay_input_path = tmp_path / "selection_artifacts" / "2026-04-09" / "selection_target_replay_input.json"
    replay_input_path.parent.mkdir(parents=True)
    replay_input_path.write_text(
        json.dumps(
            {
                "trade_date": "2026-04-09",
                "watchlist": [],
                "rejected_entries": [
                    {
                        "ticker": "AAA",
                        "score_b": 0.40,
                        "decision": "watch",
                        "strategy_signals": {"trend": {"direction": 1, "confidence": 80.0, "completeness": 1.0}},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        analyze_layer_b_rule_variants,
        "build_candidate_pool",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("live candidate pool should not be used")),
    )

    result = _run_variant(
        ["20260409"],
        env_updates={},
        fast_score_threshold=0.38,
        replay_input_report_dir=tmp_path,
    )

    assert result["total_layer_b_passes"] == 1
    assert result["by_date"]["20260409"]["selected_tickers"] == ["AAA"]


def test_run_variant_replays_profitability_neutral_from_frozen_replay_input(monkeypatch, tmp_path):
    replay_input_path = tmp_path / "selection_artifacts" / "2026-04-09" / "selection_target_replay_input.json"
    replay_input_path.parent.mkdir(parents=True)
    replay_input_path.write_text(
        json.dumps(
            {
                "trade_date": "2026-04-09",
                "watchlist": [
                    {
                        "ticker": "AAA",
                        "score_b": 0.302,
                        "decision": "neutral",
                        "market_state": {
                            "state_type": "mixed",
                            "breadth_ratio": 0.6,
                            "position_scale": 1.0,
                            "adjusted_weights": {
                                "trend": 0.4,
                                "fundamental": 0.6,
                            },
                        },
                        "strategy_signals": {
                            "trend": {
                                "direction": 1,
                                "confidence": 95.0,
                                "completeness": 1.0,
                                "sub_factors": {},
                            },
                            "fundamental": {
                                "direction": -1,
                                "confidence": 13.0,
                                "completeness": 1.0,
                                "sub_factors": {
                                    "profitability": {
                                        "name": "profitability",
                                        "direction": -1,
                                        "confidence": 100.0,
                                        "completeness": 1.0,
                                        "weight": 0.25,
                                        "metrics": {
                                            "positive_count": 0,
                                            "available_count": 3,
                                            "zero_pass_mode": "bearish",
                                        },
                                    },
                                    "growth": {
                                        "name": "growth",
                                        "direction": 1,
                                        "confidence": 60.0,
                                        "completeness": 1.0,
                                        "weight": 0.25,
                                        "metrics": {},
                                    },
                                    "financial_health": {
                                        "name": "financial_health",
                                        "direction": 0,
                                        "confidence": 50.0,
                                        "completeness": 1.0,
                                        "weight": 0.20,
                                        "metrics": {},
                                    },
                                    "growth_valuation": {
                                        "name": "growth_valuation",
                                        "direction": 0,
                                        "confidence": 50.0,
                                        "completeness": 1.0,
                                        "weight": 0.15,
                                        "metrics": {},
                                    },
                                    "industry_pe": {
                                        "name": "industry_pe",
                                        "direction": 0,
                                        "confidence": 50.0,
                                        "completeness": 1.0,
                                        "weight": 0.15,
                                        "metrics": {},
                                    },
                                },
                            },
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        analyze_layer_b_rule_variants,
        "build_candidate_pool",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("live candidate pool should not be used")),
    )

    baseline = _run_variant(
        ["20260409"],
        env_updates={},
        fast_score_threshold=0.38,
        replay_input_report_dir=tmp_path,
    )
    variant = _run_variant(
        ["20260409"],
        env_updates={"LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE": "neutral"},
        fast_score_threshold=0.38,
        replay_input_report_dir=tmp_path,
    )

    assert baseline["by_date"]["20260409"]["selected_tickers"] == []
    assert variant["by_date"]["20260409"]["selected_tickers"] == ["AAA"]
