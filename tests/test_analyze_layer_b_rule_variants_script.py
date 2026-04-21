from __future__ import annotations

import os

from scripts.analyze_layer_b_rule_variants import _temporary_env


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
